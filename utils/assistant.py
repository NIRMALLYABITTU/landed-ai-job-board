"""Grounded LANDED AI job assistant.

The assistant supports the seven assignment intents and uses Gemini only as an
optional language-generation layer. The structured job/resume data supplied to
Gemini is the source of truth. If Gemini is unavailable, deterministic fallback
answers are returned so the application remains usable.

API-key handling:
- GEMINI_API_KEY from the server environment is used as the deployment default.
- A user-provided key may be supplied per request via ``answer(..., api_key=...)``.
- User-provided keys are never written to disk, the database, or the session.
"""
from __future__ import annotations

import os
import re
from typing import Iterable

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_PLACEHOLDERS = {"", "PASTE_YOUR_GEMINI_API_KEY_HERE", "YOUR_REAL_GEMINI_KEY"}

INTENT_PATTERNS = [
    ("suitability", [
        r"am i suitable", r"good fit", r"suited for", r"qualify for",
        r"whether.*fit", r"whether.*suitable", r"fit for (?:this|the) job",
        r"fit for.*role", r"match.*my skills", r"am i a match",
    ]),
    ("missing_skills", [
        r"what skills am i missing", r"skills.*missing", r"missing skills",
        r"skill gap", r"what do i need to learn", r"what am i missing",
    ]),
    ("explain_jd", [
        r"explain this job", r"explain the job", r"explain this role",
        r"what does this job", r"summari[sz]e.*job", r"break down.*job",
    ]),
    ("which_to_apply", [
        r"which jobs", r"which roles", r"what jobs should i apply",
        r"which should i apply", r"best jobs for me", r"recommend.*jobs",
    ]),
    ("prep_guidance", [
        r"how should i prepare", r"prepare for", r"prep for", r"interview",
        r"how do i prepare",
    ]),
    ("compare_jobs", [r"compare", r"versus", r"vs\.?"] ),
    ("resume_improve", [
        r"improve.*resume", r"resume.*improve", r"what should i add",
        r"improve my cv", r"what should i change.*resume",
    ]),
]


def detect_intent(question: str) -> str:
    q = (question or "").lower().strip()
    for intent, patterns in INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, q):
                return intent
    return "general"


def _normalise_skill_set(skills: Iterable[str] | None) -> set[str]:
    return {str(s).strip().lower() for s in (skills or []) if str(s).strip()}


def _fmt_skills(skills: Iterable[str] | None) -> str:
    values = [str(s).strip() for s in (skills or []) if str(s).strip()]
    return ", ".join(values) if values else "no specific tagged skills"


def _job_context(job: dict | None) -> str:
    if not job:
        return ""
    return (
        f"Title: {job.get('title')}\n"
        f"Company: {job.get('company')}\n"
        f"Source: {job.get('source')}\n"
        f"Location: {job.get('location')}\n"
        f"Role category: {job.get('role_category')}\n"
        f"Experience level: {job.get('experience_level') or job.get('experience')}\n"
        f"Work mode: {job.get('location_requirement') or job.get('schedule_type') or 'Not specified'}\n"
        f"Skills/tags: {', '.join(job.get('skills') or [])}\n"
        f"Description: {(job.get('description') or '')[:7000]}"
    )


def _effective_key(request_key: str | None) -> str:
    candidate = (request_key or "").strip()
    if candidate and candidate not in _PLACEHOLDERS:
        return candidate
    return GEMINI_API_KEY if GEMINI_API_KEY not in _PLACEHOLDERS else ""


def _gemini_answer(api_key: str | None, question: str, grounded_context: str, fallback: str) -> str:
    """Generate a grounded answer with Gemini; fall back safely on failure."""
    key = _effective_key(api_key)
    if not key:
        return fallback

    try:
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
        model_url = "https://generativelanguage.googleapis.com/v1beta/models"
        models_response = requests.get(model_url, headers=headers, timeout=10)
        models_response.raise_for_status()
        models = models_response.json().get("models", [])

        preferred = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        chosen = None
        available = {
            str(m.get("name", "")).split("/")[-1]: m
            for m in models
            if "generateContent" in (m.get("supportedGenerationMethods") or [])
        }
        for name in preferred:
            if name in available:
                chosen = name
                break
        if not chosen:
            for name in available:
                if name.startswith("gemini"):
                    chosen = name
                    break
        if not chosen:
            return fallback

        prompt = (
            "You are LANDED, an AI job-board assistant. Use ONLY the supplied structured context. "
            "Never invent job facts, companies, salaries, dates, locations, requirements, skills, or candidate facts. "
            "Treat the selected job and computed candidate metrics as the source of truth. Be concise, structured, "
            "and practical. For suitability, preserve the supplied match percentage and gap percentage exactly, list "
            "matched skills and missing skills, and never tell a candidate to falsely claim a skill. If no resume is "
            "provided, say that a resume is required for candidate-specific fit analysis.\n\n"
            f"STRUCTURED CONTEXT:\n{grounded_context}\n\n"
            f"USER QUESTION:\n{question}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{chosen}:generateContent",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = "\n".join(str(p.get("text", "")).strip() for p in parts if p.get("text")).strip()
        return text or fallback
    except Exception:
        return fallback


def _answer_rule_based(
    question: str,
    resume_skills=None,
    job=None,
    jobs_all=None,
    compare_job=None,
    api_key=None,
) -> str:
    resume_skills = resume_skills or []
    has_resume = bool(resume_skills)
    resume_set = _normalise_skill_set(resume_skills)
    intent = detect_intent(question)

    if intent == "suitability" and job:
        if not has_resume:
            return (
                f"I can assess '{job.get('title')}' at {job.get('company')}, but no resume is loaded yet. "
                "Upload your resume first and I’ll compare your skills and experience with this specific job."
            )

        job_skills = list(job.get("skills") or [])
        job_set = _normalise_skill_set(job_skills)
        overlap = resume_set & job_set
        matched = [s for s in job_skills if str(s).strip().lower() in overlap]
        missing = [s for s in job_skills if str(s).strip().lower() not in resume_set]
        pct = round(100 * len(overlap) / max(len(job_set), 1))
        gap_pct = max(0, 100 - pct)

        verdict = (
            "Strong skills match. Review the full description and experience requirement before applying."
            if pct >= 70 else
            "Partial skills match. Your background has relevant overlap, but there are important gaps to address."
            if pct >= 40 else
            "Lower current skills match. Apply selectively unless your resume contains relevant experience not captured by the tags."
        )

        fallback = (
            f"CV match: {pct}%\n"
            f"CV skill gap: {gap_pct}%\n"
            f"Already covered: {_fmt_skills(matched)}\n"
            f"Skills not currently shown on your CV: {_fmt_skills(missing)}\n\n"
            f"The remaining {gap_pct}% represents tagged skills not currently detected in your CV. "
            "Only add a missing skill when you genuinely have it and can support it with work experience, "
            "projects, coursework, certification, or another verifiable example.\n\n"
            f"Overall: {verdict}"
        )
        context = (
            f"SELECTED JOB:\n{_job_context(job)}\n\n"
            f"CANDIDATE RESUME SKILLS: {', '.join(resume_skills)}\n\n"
            f"COMPUTED CV MATCH: {pct}%\n"
            f"COMPUTED CV GAP: {gap_pct}%\n"
            f"MATCHED SKILLS: {', '.join(matched)}\n"
            f"MISSING SKILLS: {', '.join(missing)}"
        )
        ai = _gemini_answer(api_key, question, context, fallback)
        return f"Fit analysis for '{job.get('title')}' at {job.get('company')}\n\n{ai}"

    if intent == "missing_skills" and job:
        if not has_resume:
            return f"Upload your resume first and I’ll identify the missing skills for '{job.get('title')}'."
        missing = [s for s in (job.get("skills") or []) if str(s).strip().lower() not in resume_set]
        fallback = (
            f"For '{job.get('title')}' at {job.get('company')}, the main tagged skills not found in your resume are: "
            f"{_fmt_skills(missing)}. Prioritize the most relevant gaps first."
            if missing else
            f"Your resume currently covers all tagged skills for '{job.get('title')}'. Focus on evidence and quantified impact."
        )
        return _gemini_answer(api_key, question, _job_context(job) + f"\nResume skills: {', '.join(resume_skills)}", fallback)

    if intent == "explain_jd" and job:
        fallback = (
            f"'{job.get('title')}' at {job.get('company')}\n"
            f"Role: {job.get('role_category') or 'Uncategorized'}\n"
            f"Experience: {job.get('experience_level') or job.get('experience') or 'Not specified'}\n"
            f"Location: {job.get('location') or 'Not specified'}\n"
            f"Key skills: {_fmt_skills(job.get('skills'))}\n\n"
            f"{(job.get('description') or 'No description provided.')[:1200]}"
        )
        return _gemini_answer(api_key, question, _job_context(job), fallback)

    if intent == "which_to_apply":
        if not has_resume:
            return "Upload your resume first. I’ll rank jobs using your skills, experience and role relevance."
        jobs = jobs_all or []
        ranked = []
        for j in jobs:
            jset = _normalise_skill_set(j.get("skills"))
            overlap = len(resume_set & jset)
            if overlap:
                ranked.append((overlap / max(len(resume_set), 1), j))
        ranked.sort(key=lambda x: x[0], reverse=True)
        top = ranked[:5]
        if not top:
            return "I couldn't find strong skill overlap yet. Try a broader resume or search by role category."
        return "Strongest current skill matches:\n" + "\n".join(
            f"- {j.get('title')} at {j.get('company')} ({j.get('source')}) — {round(score * 100)}% skill coverage"
            for score, j in top
        )

    if intent == "prep_guidance" and job:
        skills = list(job.get("skills") or [])
        missing = [s for s in skills if str(s).strip().lower() not in resume_set] if has_resume else skills
        fallback = (
            f"Prepare for '{job.get('title')}' by focusing on: {_fmt_skills(skills)}.\n"
            f"Priority gaps: {_fmt_skills(missing)}.\n"
            "Prepare two or three concrete project/work examples that demonstrate the relevant skills."
        )
        context = _job_context(job) + f"\nCandidate resume skills: {', '.join(resume_skills)}"
        return _gemini_answer(api_key, question, context, fallback)

    if intent == "compare_jobs" and job and compare_job:
        a = _normalise_skill_set(job.get("skills"))
        b = _normalise_skill_set(compare_job.get("skills"))
        shared = sorted(a & b)
        only_a = sorted(a - b)
        only_b = sorted(b - a)
        fallback = (
            f"{job.get('title')} @ {job.get('company')} vs {compare_job.get('title')} @ {compare_job.get('company')}\n\n"
            f"Shared skills: {_fmt_skills(shared)}\n"
            f"Only in first role: {_fmt_skills(only_a)}\n"
            f"Only in second role: {_fmt_skills(only_b)}\n"
            f"Experience: {job.get('experience_level') or 'Not specified'} vs {compare_job.get('experience_level') or 'Not specified'}"
        )
        context = f"JOB A:\n{_job_context(job)}\n\nJOB B:\n{_job_context(compare_job)}"
        return _gemini_answer(api_key, question, context, fallback)

    if intent == "resume_improve" and job:
        if not has_resume:
            return "Upload your resume first. I’ll identify specific improvements for this opportunity."
        missing = [s for s in (job.get("skills") or []) if str(s).strip().lower() not in resume_set]
        fallback = (
            f"For '{job.get('title')}', strengthen your resume around these relevant gaps: {_fmt_skills(missing)}. "
            "Also quantify outcomes, show project scope, and place the strongest matching skills near the top. "
            "Only include skills you genuinely have and can support with evidence."
        )
        context = f"SELECTED JOB:\n{_job_context(job)}\n\nCANDIDATE SKILLS:\n{', '.join(resume_skills)}"
        return _gemini_answer(api_key, question, context, fallback)

    # General / no selected job: still use grounded candidate inventory if available.
    context = ""
    if job:
        context += f"Selected job:\n{_job_context(job)}\n\n"
    if resume_skills:
        context += f"Candidate resume skills: {', '.join(resume_skills)}\n\n"
    if jobs_all:
        context += "Available job titles:\n" + "\n".join(
            f"- {j.get('title')} at {j.get('company')}" for j in jobs_all[:20]
        )
    fallback = (
        "I can help with a selected job, your resume, skill gaps, preparation, comparisons, or application strategy. "
        "Open a job or upload your resume for a more specific answer."
    )
    return _gemini_answer(api_key, question, context, fallback)


def answer(
    question: str,
    resume_skills=None,
    job=None,
    jobs_all=None,
    compare_job=None,
    api_key: str | None = None,
) -> str:
    """Return a grounded assistant answer.

    ``api_key`` is request-scoped input only. It is never persisted.
    """
    return _answer_rule_based(
        question=question,
        resume_skills=resume_skills,
        job=job,
        jobs_all=jobs_all,
        compare_job=compare_job,
        api_key=api_key,
    )
