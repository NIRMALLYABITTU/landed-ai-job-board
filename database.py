"""SQLite runtime store for the supplied job JSON dataset."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "jobboard.db"

def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())

def dedup_key(title, company, location):
    raw = f"{_norm(title)}|{_norm(company)}|{_norm(location)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

@contextmanager
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db(reset=False):
    with get_conn() as c:
        if reset:
            c.execute("DROP TABLE IF EXISTS jobs")
            c.execute("DROP TABLE IF EXISTS resumes")
        c.execute("""
        CREATE TABLE IF NOT EXISTS jobs(
            dedup_key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT,
            experience TEXT,
            description TEXT,
            posted_date TEXT,
            skills TEXT,
            role_category TEXT,
            experience_level TEXT,
            sources_json TEXT NOT NULL DEFAULT '[]',
            source_ids_json TEXT NOT NULL DEFAULT '{}',
            source_urls_json TEXT NOT NULL DEFAULT '{}',
            source_count INTEGER NOT NULL DEFAULT 1,
            employment_type TEXT,
            schedule_type TEXT,
            domain TEXT,
            min_experience REAL,
            max_experience REAL,
            min_salary REAL,
            max_salary REAL,
            location_requirement TEXT,
            thumbnail TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS resumes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            raw_text TEXT,
            skills TEXT,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_role ON jobs(role_category)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_experience ON jobs(experience_level)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_domain ON jobs(domain)",
        ]:
            c.execute(sql)

def _json(value, default):
    try:
        return json.loads(value or default)
    except Exception:
        return json.loads(default)

def _row_to_job(r, selected_source=None):
    if not r:
        return None
    d = dict(r)
    d["skills"] = _json(d.pop("skills"), "[]")
    d["sources"] = _json(d.pop("sources_json"), "[]")
    d["source_ids"] = _json(d.pop("source_ids_json"), "{}")
    d["source_urls"] = _json(d.pop("source_urls_json"), "{}")
    available_sources = d["sources"]
    chosen = selected_source if selected_source and selected_source in available_sources else (available_sources[0] if available_sources else "Unknown")
    d["content_hash"] = d["dedup_key"]
    d["source"] = chosen
    d["also_posted_on"] = [s for s in available_sources if s != chosen]
    d["url"] = d["source_urls"].get(chosen) or (next(iter(d["source_urls"].values()), "") if d["source_urls"] else "")
    return d

def _merge_json_list(raw, incoming):
    a = raw if isinstance(raw, list) else []
    b = incoming if isinstance(incoming, list) else []
    return sorted({str(x).strip() for x in a + b if str(x).strip()}, key=str.lower)

def replace_jobs(jobs):
    with get_conn() as c:
        c.execute("DELETE FROM jobs")
        insert_sql = """INSERT OR IGNORE INTO jobs
        (dedup_key,title,company,location,experience,description,posted_date,skills,role_category,
         experience_level,sources_json,source_ids_json,source_urls_json,source_count,employment_type,
         schedule_type,domain,min_experience,max_experience,min_salary,max_salary,location_requirement,thumbnail)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        inserted = merged = total = 0
        for j in jobs:
            total += 1
            if not j.get("title") or not j.get("company"):
                continue
            key = dedup_key(j["title"], j["company"], j.get("location"))
            source = j.get("source") or "Unknown"
            cur = c.execute(insert_sql, (
                key, j["title"], j["company"], j.get("location"), j.get("experience"), j.get("description"),
                j.get("posted_date"), json.dumps(j.get("skills", []), ensure_ascii=False), j.get("role_category"),
                j.get("experience_level"), json.dumps([source]),
                json.dumps({source: j.get("id")} if j.get("id") else {}),
                json.dumps({source: j.get("url")} if j.get("url") else {}), 1, j.get("employment_type"),
                j.get("schedule_type"), j.get("domain"), j.get("min_experience"), j.get("max_experience"),
                j.get("min_salary"), j.get("max_salary"), j.get("location_requirement"), j.get("thumbnail")
            ))
            if cur.rowcount:
                inserted += 1
                continue

            merged += 1
            old = c.execute("SELECT * FROM jobs WHERE dedup_key=?", (key,)).fetchone()
            sources = _json(old["sources_json"], "[]")
            if source not in sources:
                sources.append(source)
            ids = _json(old["source_ids_json"], "{}")
            urls = _json(old["source_urls_json"], "{}")
            if j.get("id"):
                ids[source] = j["id"]
            if j.get("url"):
                urls[source] = j["url"]
            skills = _merge_json_list(_json(old["skills"], "[]"), j.get("skills", []))
            old_desc = old["description"] or ""
            new_desc = j.get("description") or ""
            desc = new_desc if len(new_desc) > len(old_desc) else old_desc
            posted = max(old["posted_date"] or "", j.get("posted_date") or "")
            c.execute("""UPDATE jobs SET description=?,posted_date=?,skills=?,sources_json=?,source_ids_json=?,
                source_urls_json=?,source_count=?,role_category=COALESCE(role_category,?),experience_level=COALESCE(experience_level,?)
                WHERE dedup_key=?""", (desc, posted, json.dumps(skills, ensure_ascii=False), json.dumps(sources),
                                          json.dumps(ids), json.dumps(urls), len(sources), j.get("role_category"),
                                          j.get("experience_level"), key))
        return {"input": total, "stored": inserted, "duplicates_removed": merged}

def _where(source=None, search=None, role_category=None, experience_level=None, skill=None):
    w = ["1=1"]
    p = []
    if source and source.lower() != "all":
        # JSON arrays are stored as strings; normalize both sides so case does not matter.
        w.append("LOWER(sources_json) LIKE ?")
        p.append('%"' + source.lower() + '"%')
    if role_category and role_category.lower() != "all":
        w.append("role_category=?")
        p.append(role_category)
    if experience_level and experience_level.lower() != "all":
        w.append("experience_level=?")
        p.append(experience_level)
    if skill:
        w.append("LOWER(skills) LIKE ?")
        p.append(f"%{skill.lower()}%")
    if search:
        like = f"%{search.lower()}%"
        w.append("(LOWER(title) LIKE ? OR LOWER(company) LIKE ? OR LOWER(location) LIKE ? OR LOWER(description) LIKE ? OR LOWER(skills) LIKE ? OR LOWER(role_category) LIKE ? OR LOWER(domain) LIKE ? OR LOWER(location_requirement) LIKE ?)")
        p.extend([like] * 8)
    return " WHERE " + " AND ".join(w), p

def get_jobs(source=None, search=None, skill=None, role_category=None, experience_level=None, limit=20, offset=0):
    w, p = _where(source, search, role_category, experience_level, skill)
    with get_conn() as c:
        rows = c.execute("SELECT * FROM jobs" + w + " ORDER BY CASE WHEN posted_date IS NULL OR posted_date='' THEN 1 ELSE 0 END, posted_date DESC LIMIT ? OFFSET ?", p + [limit, offset]).fetchall()
        return [_row_to_job(r, source if source and source.lower() != "all" else None) for r in rows]

def count_jobs(source=None, search=None, skill=None, role_category=None, experience_level=None):
    w, p = _where(source, search, role_category, experience_level, skill)
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) FROM jobs" + w, p).fetchone()[0]

def get_job_by_hash(key):
    with get_conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE dedup_key=?", (key,)).fetchone()
        return _row_to_job(r) if r else None

def get_stats():
    """Return user-facing job-board statistics using fixed IST (UTC+05:30).

    A fixed offset is intentional here: the application only needs the current
    India calendar date for the "jobs added today" metric. This avoids any
    dependency on an external/system IANA timezone database on Windows.
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    today_ist = datetime.now(ist).date().isoformat()
    with get_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        companies = c.execute("SELECT COUNT(DISTINCT company) FROM jobs").fetchone()[0]
        rows = c.execute("SELECT sources_json FROM jobs").fetchall()
        sources = sorted({s for r in rows for s in _json(r[0], "[]")})
        latest = c.execute("SELECT MAX(posted_date) FROM jobs").fetchone()[0]
        today_count = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE substr(posted_date, 1, 10) = ?",
            (today_ist,),
        ).fetchone()[0]
        latest_date_count = 0
        latest_date = (latest or "")[:10]
        if latest_date:
            latest_date_count = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE substr(posted_date, 1, 10) = ?",
                (latest_date,),
            ).fetchone()[0]
        return {
            "total_jobs": total,
            "companies": companies,
            "sources": len(sources),
            "source_names": sources,
            "latest_posted": latest,
            "jobs_added_today": today_count,
            "jobs_on_latest_date": latest_date_count,
            "today": today_ist,
        }

def get_sources():
    with get_conn() as c:
        rows = c.execute("SELECT sources_json FROM jobs").fetchall()
        return sorted({s for r in rows for s in _json(r[0], "[]")})

def get_role_categories():
    with get_conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT role_category FROM jobs WHERE role_category IS NOT NULL AND role_category<>'' ORDER BY role_category")]

def get_experience_levels():
    with get_conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT experience_level FROM jobs WHERE experience_level IS NOT NULL AND experience_level<>'' ORDER BY experience_level")]

def get_all_jobs(limit=None):
    with get_conn() as c:
        q = "SELECT * FROM jobs ORDER BY posted_date DESC"
        if limit is not None:
            q += " LIMIT ?"
            rows = c.execute(q, (int(limit),)).fetchall()
        else:
            rows = c.execute(q).fetchall()
        return [_row_to_job(r) for r in rows]


def get_recommendation_candidates(skills, limit=5000):
    """Return a bounded candidate pool using explicit skill overlap.

    This avoids loading the full 45k+ inventory into memory for every resume
    upload or assistant request. If no tagged skill overlaps, fall back to the
    most recently posted jobs so the recommender still returns useful results.
    """
    clean = [str(x).strip().lower() for x in (skills or []) if str(x).strip()]
    limit = max(1, min(int(limit), 10000))
    with get_conn() as c:
        if clean:
            clauses = ["LOWER(skills) LIKE ?" for _ in clean]
            params = [f"%\"{x}\"%" for x in clean]
            q = ("SELECT * FROM jobs WHERE " + " OR ".join(clauses) +
                 " ORDER BY CASE WHEN posted_date IS NULL OR posted_date='' THEN 1 ELSE 0 END, posted_date DESC LIMIT ?")
            rows = c.execute(q, params + [limit]).fetchall()
            if rows:
                return [_row_to_job(r) for r in rows]
        rows = c.execute(
            "SELECT * FROM jobs ORDER BY CASE WHEN posted_date IS NULL OR posted_date='' THEN 1 ELSE 0 END, posted_date DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [_row_to_job(r) for r in rows]

def save_resume(filename, raw_text, skills):
    with get_conn() as c:
        return c.execute("INSERT INTO resumes(filename,raw_text,skills) VALUES(?,?,?)", (filename, raw_text, json.dumps(skills))).lastrowid
