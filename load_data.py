"""
Build the SQLite runtime database from the supplied JSON.

Usage:
  python load_data.py data/jobs_raw.json
  python load_data.py data/jobs_raw.json --reset

The JSON is the source dataset; SQLite is only a derived query layer.

MEMORY NOTE: for a ~57k-row / ~380MB-uncompressed dataset, doing
`json.load()` on the whole file at once peaks around 1.6-1.7GB RSS (the
raw parsed structure + the normalized copies existing simultaneously).
That reliably OOM-kills a build on Render's free/starter tiers (512MB
RAM). We stream-parse with ijson instead, one record at a time, so peak
memory stays in the tens of MB regardless of dataset size.
"""
import json, sys, argparse, gzip, os
from database import init_db, replace_jobs
from utils.tagger import enrich_job

try:
    import ijson
except ImportError:
    ijson = None

def normalize(raw):
    # Accept both the supplied Google Drive schema and common alternate schemas.
    aliases={
        "id":["id","job_id","jobId","listing_id"],
        "source":["source","platform","site","via"],
        "title":["title","job_title","jobTitle","role","position"],
        "company":["company","company_name","companyName","employer"],
        "location":["location","job_location","city"],
        "experience":["experience","experience_required","exp","minExperienceRequired"],
        "description":["description","job_description","jobDescription","details","summary","formattedDescription"],
        "url":["url","job_url","link","apply_link"],
        "posted_date":["posted_date","postedDate","date_posted","posted_on","posted_at","publishedAt","createdAt"],
    }
    def first(names):
        for n in names:
            v=raw.get(n)
            if v not in (None,"",[]): return v
        return None
    source=first(aliases["source"]) or "Unknown"
    if isinstance(source,str) and source.lower().startswith("via "): source=source[4:].strip()
    low=str(source).lower()
    for p,name in [("linkedin","LinkedIn"),("naukri","Naukri"),("indeed","Indeed"),("internshala","Internshala")]:
        if p in low: source=name; break

    skills=raw.get("skills", raw.get("skills_raw", []))
    if isinstance(skills,str): skills=[s.strip() for s in skills.split(",") if s.strip()]
    if not isinstance(skills,list): skills=[]

    url=first(aliases["url"]) or ""
    if not url and raw.get("apply_options"):
        try:
            opts=json.loads(raw["apply_options"]) if isinstance(raw["apply_options"],str) else raw["apply_options"]
            if isinstance(opts,list) and opts and isinstance(opts[0],dict): url=opts[0].get("link","")
        except Exception: pass

    out={
        "id":str(first(aliases["id"]) or ""),
        "source":str(source),
        "title":str(first(aliases["title"]) or "").strip(),
        "company":str(first(aliases["company"]) or "").strip(),
        "location":str(first(aliases["location"]) or "").strip(),
        "experience":str(first(aliases["experience"]) or "").strip(),
        "description":str(first(aliases["description"]) or "").strip(),
        "url":str(url),
        "posted_date":str(first(aliases["posted_date"]) or "").strip(),
        "skills":skills,
        "employment_type":raw.get("employmentType"),
        "schedule_type":raw.get("schedule_type"),
        "domain":raw.get("domain"),
        "min_experience":raw.get("minExperienceRequired", raw.get("min_experience")),
        "max_experience":raw.get("maxExperienceRequired", raw.get("max_experience")),
        "min_salary":raw.get("minSalary", raw.get("salary_min")),
        "max_salary":raw.get("maxSalary", raw.get("salary_max")),
        "location_requirement":raw.get("locationRequirement"),
        "thumbnail":raw.get("thumbnail"),
        "role_category":raw.get("role_category"),
        "experience_level":raw.get("experience_level"),
    }
    return out

def _iter_raw_records(path):
    """Stream records one at a time instead of materializing the whole
    parsed JSON array in memory. Falls back to json.load only if ijson
    isn't installed (small files / dev convenience) or if the file turns
    out to be a JSON object wrapping the array (e.g. {"jobs": [...]}) —
    ijson's item-streaming needs to know the array's location, so wrapped
    shapes fall back to the simple loader (fine: wrapped exports tend to
    be much smaller test fixtures, not the 57k-row production dataset)."""
    opener = gzip.open if path.lower().endswith((".gz", ".gzip")) else open

    if ijson is not None:
        try:
            with opener(path, "rb") as f:
                # Peek at the first non-whitespace byte to decide array vs object,
                # without reading the whole file.
                head = f.read(2048)
            first_char = next((c for c in head.decode("utf-8", "ignore") if not c.isspace()), "")
            if first_char == "[":
                with opener(path, "rb") as f:
                    for item in ijson.items(f, "item"):
                        yield item
                return
        except Exception:
            pass  # fall through to the non-streaming loader below

    with opener(path, "rt", encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        raw = raw.get("jobs") or raw.get("data") or []
    if not isinstance(raw, list):
        raise ValueError("Expected a JSON array of job records.")
    for item in raw:
        yield item


def main(path, reset=False):
    # Best-effort total count for progress logging only (read from the
    # bundled manifest if present — cheap and avoids a second full pass
    # over a 380MB file just to print "x/y").
    total_hint = None
    manifest_path = os.path.join(os.path.dirname(os.path.abspath(path)), "manifest.json")
    try:
        with open(manifest_path) as mf:
            total_hint = json.load(mf).get("raw_records")
    except Exception:
        pass

    def job_stream():
        i = 0
        for item in _iter_raw_records(path):
            i += 1
            if not isinstance(item, dict):
                continue
            j = normalize(item)
            if not j["title"] or not j["company"]:
                continue
            if not j.get("skills") or not j.get("role_category") or not j.get("experience_level"):
                j = enrich_job(j)
            if i % 5000 == 0:
                if total_hint:
                    print(f"Processed {i:,}/{total_hint:,} records...", flush=True)
                else:
                    print(f"Processed {i:,} records...", flush=True)
            yield j

    init_db(reset=reset)
    stats = replace_jobs(job_stream())
    print(f"Input records: {stats['input']:,}")
    print(f"Unique jobs stored: {stats['stored']:,}")
    print(f"Duplicates merged: {stats['duplicates_removed']:,}")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("path",nargs="?",default="data/jobs_normalized.json.gz")
    ap.add_argument("--reset",action="store_true")
    a=ap.parse_args()
    main(a.path,a.reset)
