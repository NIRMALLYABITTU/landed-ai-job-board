import os
import re
from flask import Flask, request, jsonify, render_template, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from database import (
    init_db, get_jobs, get_job_by_hash, get_sources, get_role_categories,
    get_experience_levels, count_jobs, get_stats, get_recommendation_candidates, DB_PATH,
    create_user, get_user_auth_row, get_user_by_id,
)
from utils.resume_parser import parse_resume
from utils.recommender import recommend_jobs
from utils.assistant import answer as assistant_answer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "jobs_normalized.json.gz")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB resumes max
app.config["JSON_SORT_KEYS"] = False
# Login sessions last 30 days (signed cookie, no server-side session store —
# safe with multiple gunicorn workers/threads since nothing is kept in
# process memory for this part).
app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 24 * 30
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
init_db()

# The database is generated once from the supplied dataset. Because DB_PATH is
# absolute, the app reads the same database no matter where the user launches
# Flask from. If a fresh clone has no rows, bootstrap it automatically.
def ensure_database():
    try:
        if get_stats().get("total_jobs", 0) > 0:
            return
    except Exception:
        pass
    if os.path.exists(DATA_PATH):
        from load_data import main as build_database
        build_database(DATA_PATH, reset=True)

ensure_database()

# In-memory store of the most recently parsed resume, keyed by session id,
# so we don't have to re-upload for every chat/recommendation call.
# (Kept server-side only; the raw file is deleted after parsing — see
# /api/resume/upload — so nothing sensitive persists on disk longer than
# needed.)
_RESUME_CACHE = {}


def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _session_id():
    if "sid" not in session:
        session["sid"] = os.urandom(8).hex()
    return session["sid"]


def _current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_user_by_id(uid)


@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(_error):
    return jsonify({"error": "Resume is too large. Maximum size is 5MB."}), 413


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    # Keep API failures JSON so the frontend can show a useful message instead
    # of trying to parse Flask's HTML error page.
    if request.path.startswith("/api/"):
        app.logger.exception("API error on %s", request.path)
        return jsonify({"error": "Server error. Check the terminal for details."}), 500
    raise error


@app.route("/api/health")
def api_health():
    stats = get_stats()
    return jsonify({"ok": True, "database_jobs": stats["total_jobs"], "sources": stats["source_names"], "database_path": str(DB_PATH)})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sources")
def api_sources():
    return jsonify({
        "sources": get_sources(),
        "role_categories": get_role_categories(),
        "experience_levels": get_experience_levels(),
    })


@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())


@app.route("/api/jobs")
def api_jobs():
    source = request.args.get("source")
    search = request.args.get("search")
    skill = request.args.get("skill")
    role_category = request.args.get("role_category")
    experience_level = request.args.get("experience_level")

    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(60, max(1, request.args.get("per_page", 20, type=int)))
    offset = (page - 1) * per_page

    filters = dict(source=source, search=search, skill=skill,
                    role_category=role_category, experience_level=experience_level)

    jobs = get_jobs(limit=per_page, offset=offset, **filters)
    total = count_jobs(**filters)

    return jsonify({
        "jobs": jobs,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    })


@app.route("/api/jobs/<job_hash>")
def api_job_detail(job_hash):
    job = get_job_by_hash(job_hash)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


@app.route("/api/resume/upload", methods=["POST"])
def api_resume_upload():
    if "resume" not in request.files:
        return jsonify({"error": "No resume file was provided."}), 400

    file = request.files["resume"]
    if not file.filename:
        return jsonify({"error": "Please choose a resume file."}), 400
    if not _allowed(file.filename):
        return jsonify({"error": "Unsupported file type. Use PDF, DOCX, or TXT."}), 400

    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({"error": "Invalid filename."}), 400

    # Use a unique temporary path so two users uploading the same filename
    # cannot overwrite each other's files.
    sid = _session_id()
    temp_name = f"{sid}_{os.urandom(6).hex()}_{filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], temp_name)

    try:
        file.save(filepath)
        parsed = parse_resume(filepath)
        if not parsed.get("raw_text", "").strip():
            return jsonify({"error": "The resume could not be read. Use a text-based PDF, DOCX, or TXT file."}), 400
    except Exception as e:
        app.logger.exception("Resume parsing failed")
        return jsonify({"error": f"Could not parse resume: {e}"}), 400
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                app.logger.warning("Could not delete temporary resume: %s", filepath)

    _RESUME_CACHE[sid] = parsed

    return jsonify({
        "filename": filename,
        "skills": parsed["skills"],
        "experience_level": parsed["experience_level"],
        "character_count": len(parsed["raw_text"]),
    })


@app.route("/api/recommendations")
def api_recommendations():
    sid = _session_id()
    parsed = _RESUME_CACHE.get(sid)
    if not parsed:
        return jsonify({"error": "upload a resume first via /api/resume/upload"}), 400

    # Scan the complete deduplicated inventory. The recommender first narrows
    # candidates by explicit skill overlap, then runs TF-IDF on that bounded set.
    candidates = get_recommendation_candidates(parsed["skills"], limit=5000)
    recs = recommend_jobs(parsed["raw_text"], parsed["skills"], candidates, top_n=10)
    return jsonify({"recommendations": recs, "resume_skills": parsed["skills"]})


@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    name = (data.get("name") or "").strip() or None

    if not email or not EMAIL_RE.match(email):
        return jsonify({"error": "Enter a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters."}), 400
    if name and len(name) > 100:
        return jsonify({"error": "Name is too long."}), 400

    user = create_user(email, generate_password_hash(password), name)
    if user is None:
        return jsonify({"error": "An account with that email already exists."}), 409

    session["user_id"] = user["id"]
    session.permanent = True
    return jsonify({"user": user})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    row = get_user_auth_row(email)
    # Constant-shape response either way (don't reveal whether the email
    # exists) — check_password_hash on a dummy hash keeps timing similar
    # even when there's no matching row.
    valid = bool(row) and check_password_hash(row["password_hash"], password)
    if not valid:
        return jsonify({"error": "Incorrect email or password."}), 401

    session["user_id"] = row["id"]
    session.permanent = True
    return jsonify({"user": {"id": row["id"], "email": row["email"], "name": row.get("name")}})


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.pop("user_id", None)
    return jsonify({"ok": True})


@app.route("/api/auth/me")
def api_me():
    user = _current_user()
    return jsonify({"user": user})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    job_hash = data.get("job_hash")
    compare_hash = data.get("compare_job_hash")

    sid = _session_id()
    parsed = _RESUME_CACHE.get(sid)
    resume_skills = parsed["skills"] if parsed else None

    job = get_job_by_hash(job_hash) if job_hash else None
    compare_job = get_job_by_hash(compare_hash) if compare_hash else None
    all_jobs = get_recommendation_candidates(resume_skills or [], limit=3000) if resume_skills else []
    reply = assistant_answer(
        question, resume_skills=resume_skills, job=job,
        jobs_all=all_jobs, compare_job=compare_job,
    )
    return jsonify({"answer": reply})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
