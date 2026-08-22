"""Offline verification for the Fielded job-board core."""
from database import get_stats, get_jobs, count_jobs, get_sources, get_recommendation_candidates
from utils.resume_parser import parse_resume
from utils.recommender import recommend_jobs
import tempfile, os

s = get_stats()
assert s["total_jobs"] > 0, "Database has no jobs"
assert count_jobs(search="Python") > 0, "Python search returned no jobs"
assert count_jobs(source="LinkedIn") > 0, "LinkedIn filter returned no jobs"
jobs = get_jobs(search="Data Scientist", limit=5)
assert jobs, "Data Scientist search returned no jobs"
assert all(j.get("content_hash") for j in jobs), "Job hashes missing"
assert get_sources(), "No sources found"

with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
    f.write("Data Analyst with Python SQL Power BI Tableau and Statistics. 3 years experience.")
    path = f.name
try:
    resume = parse_resume(path)
    assert resume["skills"], "Resume skills not detected"
    candidates = get_recommendation_candidates(resume["skills"], 500)
    assert candidates, "No recommendation candidates"
    recs = recommend_jobs(resume["raw_text"], resume["skills"], candidates, top_n=5)
    assert recs, "No recommendations generated"
finally:
    os.remove(path)

print("PASS: database", s["total_jobs"], "jobs")
print("PASS: Python search", count_jobs(search="Python"))
print("PASS: LinkedIn filter", count_jobs(source="LinkedIn"))
print("PASS: Data Scientist search", count_jobs(search="Data Scientist"))
print("PASS: resume parsing and recommendations")
print("ALL CORE CHECKS PASSED")
