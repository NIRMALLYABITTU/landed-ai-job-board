"""Explainable resume-to-job recommendation engine.

Scoring model:
- 35% TF-IDF semantic similarity over title + description + skills
- 30% skill coverage
- 20% experience fit
- 15% role relevance

The weighting is explicit so the recommendation remains explainable during
an interview and can be tuned without changing the API contract.
"""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from utils.tagger import classify_role_category, extract_experience

BAND_ORDER = {
    "Fresher": 0,
    "0-1 years": 1,
    "1-3 years": 2,
    "3-5 years": 3,
    "5-8 years": 4,
    "8+ years": 5,
}


def _norm_set(values):
    return {str(v).strip().lower() for v in (values or []) if str(v).strip()}


def _job_document(job):
    skills = " ".join(job.get("skills") or [])
    return f"{job.get('title','')} {job.get('role_category','')} {job.get('description','')} {skills}"


def _band_score(candidate_band, job_band):
    if not candidate_band or not job_band:
        return 0.5
    if candidate_band == "Not specified" or job_band == "Not specified":
        return 0.5
    c = BAND_ORDER.get(candidate_band)
    j = BAND_ORDER.get(job_band)
    if c is None or j is None:
        return 0.5
    if c == j:
        return 1.0
    if c > j:
        return 0.9
    distance = j - c
    if distance == 1:
        return 0.65
    if distance == 2:
        return 0.4
    return 0.2


def _role_score(resume_text, candidate_role, job):
    if not resume_text:
        return 0.5
    resume_role = classify_role_category("", resume_text)
    job_role = str(job.get("role_category") or "").strip()
    if resume_role != "General" and job_role and resume_role == job_role:
        return 1.0
    if job_role and job_role.lower() in resume_text.lower():
        return 0.85

    title = str(job.get("title") or "").lower()
    role_terms = [t for t in re.findall(r"[a-zA-Z]{4,}", title) if t not in {"senior", "junior", "engineer", "developer", "analyst"}]
    if role_terms and sum(1 for t in role_terms if t in resume_text.lower()) >= max(1, len(role_terms) // 3):
        return 0.7
    return 0.3 if resume_role != "General" and job_role and resume_role != job_role else 0.5


def recommend_jobs(resume_text, resume_skills, jobs, top_n=10, candidate_limit=3000):
    if not jobs:
        return []

    resume_set = _norm_set(resume_skills)
    candidate_band = extract_experience(resume_text or "", None)
    candidate_role = classify_role_category("", resume_text or "")

    ranked = []
    for job in jobs[:candidate_limit]:
        job_set = _norm_set(job.get("skills"))
        overlap = resume_set & job_set
        skill_score = len(overlap) / max(len(resume_set), 1)
        exp_score = _band_score(candidate_band, job.get("experience_level"))
        role_score = _role_score(resume_text or "", candidate_role, job)
        ranked.append((skill_score, exp_score, role_score, job, overlap))

    # Keep the candidate pool bounded before TF-IDF.
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3].get("posted_date") or ""), reverse=True)
    candidates = [row[3] for row in ranked[:candidate_limit]]

    docs = [_job_document(j) for j in candidates]
    docs.append(resume_text or " ".join(resume_skills or []))
    vectorizer = TfidfVectorizer(stop_words="english", max_features=12000)
    matrix = vectorizer.fit_transform(docs)
    similarities = cosine_similarity(matrix[-1], matrix[:-1])[0]

    scored = []
    for job, semantic in zip(candidates, similarities):
        job_set = _norm_set(job.get("skills"))
        overlap = resume_set & job_set
        skill_score = len(overlap) / max(len(resume_set), 1)
        exp_score = _band_score(candidate_band, job.get("experience_level"))
        role_score = _role_score(resume_text or "", candidate_role, job)

        final = (
            0.35 * float(semantic)
            + 0.30 * skill_score
            + 0.20 * exp_score
            + 0.15 * role_score
        )

        scored.append({
            **job,
            "match_score": round(final * 100, 1),
            "semantic_score": round(float(semantic) * 100, 1),
            "skill_score": round(skill_score * 100, 1),
            "experience_score": round(exp_score * 100, 1),
            "role_score": round(role_score * 100, 1),
            "matched_skills": sorted(overlap),
            "candidate_experience_band": candidate_band,
            "candidate_role_category": candidate_role,
        })

    scored.sort(
        key=lambda x: (x["match_score"], x.get("posted_date") or ""),
        reverse=True,
    )
    return scored[:top_n]
