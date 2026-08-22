"""
AI Job Assistant — conversational experience WITHOUT requiring any paid
API key (Gemini/OpenAI/etc).

Design (explainable in interview):
- Intent detection: lightweight keyword/regex matching over the question
  to route to one of the 7 supported intents from the brief (suitability,
  missing skills, explain JD, which jobs to apply, prep guidance, compare
  two jobs, resume improvement).
- Each intent handler is *grounded*: it pulls real structured data (the
  job's tags/skills/role_category and the user's parsed resume skills)
  and composes a templated-but-dynamic natural-language answer — never a
  hallucinated generic answer.
- This keeps the assistant 100% local/offline and free, and every answer
  is traceable back to concrete data, which is important since the brief
  explicitly asks for explainability.
- OPTIONAL UPGRADE: if the user pip-installs `transformers` + `torch` and
  a local instruction-tuned model (e.g. google/flan-t5-base, no API key
  needed, downloaded once from Hugging Face) is available, `generate()`
  will use it to phrase the final answer more fluently using the same
  grounded context as the prompt. If unavailable, we transparently fall
  back to the rule-based composer below — the app never breaks or
  requires a key either way.
"""
import re
import json
import os
import requests

# Optional: set the GEMINI_API_KEY environment variable to have the
# assistant call Gemini for more fluent answers. Completely optional —
# if unset (or left as this placeholder), the assistant uses the local
# grounded rule-based composer below and never makes a network call, so
# the app works fully with zero API keys and zero cost.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
_GEMINI_PLACEHOLDER_VALUES = {"", "PASTE_YOUR_GEMINI_API_KEY_HERE", "your_gemini_api_key_here"}

_LOCAL_LLM = None
_LOCAL_LLM_TRIED = False


def _try_load_local_llm():
    """Best-effort load of a small local (no-API-key) instruction model.
    Returns None silently if transformers/torch/model aren't available —
    this keeps the whole app fully functional without it."""
    global _LOCAL_LLM, _LOCAL_LLM_TRIED
    if _LOCAL_LLM_TRIED:
        return _LOCAL_LLM
    _LOCAL_LLM_TRIED = True
    try:
        from transformers import pipeline
        _LOCAL_LLM = pipeline("text2text-generation", model="google/flan-t5-small")
    except Exception:
        _LOCAL_LLM = None
    return _LOCAL_LLM


def _llm_polish(context: str, question: str, fallback: str) -> str:
    """If a local model is available, use it to phrase a nicer answer
    grounded in `context`; otherwise return the rule-based fallback."""
    llm = _try_load_local_llm()
    if llm is None:
        return fallback
    try:
        prompt = (
            f"Answer the user's question using ONLY the context below. "
            f"Be concise and specific.\n\nContext: {context}\n\n"
            f"Question: {question}\n\nAnswer:"
        )
        out = llm(prompt, max_new_tokens=150)[0]["generated_text"].strip()
        return out if out else fallback
    except Exception:
        return fallback


INTENT_PATTERNS = [
    ("suitability", [
        r"am i suitable", r"good fit", r"suited for", r"qualify for",
        r"whether.*fit", r"whether.*suitable", r"fit for (?:this|the) job",
        r"fit for.*role", r"match.*my skills"
    ]),
    ("missing_skills", [r"missing", r"skill gap", r"what skills"]),
    ("explain_jd", [r"explain this job", r"explain the job", r"what does this job", r"summar"]),
    ("which_to_apply", [r"which jobs? should i apply", r"best jobs? for me", r"recommend"]),
    ("prep_guidance", [r"how should i prepare", r"prepare for", r"prep for", r"interview"]),
    ("compare_jobs", [r"compare"]),
    ("resume_improve", [r"improve.*resume", r"resume.*improve", r"what should i add"]),
]


def detect_intent(question: str) -> str:
    q = question.lower()
    for intent, patterns in INTENT_PATTERNS:
        for p in patterns:
            if re.search(p, q):
                return intent
    return "general"


def _fmt_skills(skills):
    return ", ".join(skills) if skills else "no specific tagged skills"


def _gemini_answer(api_key, question, grounded_context, fallback):
    """Use a user-supplied Gemini key for this request only.

    The API is treated as an enhancement: if the key is absent or the network/API
    rejects a request, the grounded local assistant still answers. The code first
    discovers an available generateContent model instead of hard-coding a model name
    that may have been retired or renamed.
    """
    if not api_key or api_key.strip() in _GEMINI_PLACEHOLDER_VALUES:
        return fallback
    try:
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        models_url = "https://generativelanguage.googleapis.com/v1beta/models"
        models_response = requests.get(models_url, headers=headers, timeout=12)
        models_response.raise_for_status()
        models = models_response.json().get("models", [])

        preferred = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
        chosen = None
        for wanted in preferred:
            for m in models:
                name = str(m.get("name", "")).split("/")[-1]
                methods = m.get("supportedGenerationMethods", []) or []
                if name == wanted and "generateContent" in methods:
                    chosen = name
                    break
            if chosen:
                break
        if not chosen:
            for m in models:
                name = str(m.get("name", "")).split("/")[-1]
                if name.startswith("gemini") and "generateContent" in (m.get("supportedGenerationMethods", []) or []):
                    chosen = name
                    break
        if not chosen:
            return fallback

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{chosen}:generateContent"
        prompt = (
            "You are the LANDED Job Assistant. Answer using only the supplied job-board context. "
            "Do not invent job facts, skills, companies, salaries, dates, or requirements. "
            "Use the selected job as the primary source of truth. Distinguish between job requirements, "
            "candidate skills, missing skills, and your recommendation. If no resume is loaded, explicitly "
            "say that candidate-specific fit analysis requires a resume. For suitability questions, always "
            "report the computed tagged-skill match percentage and the remaining gap percentage. List the "
            "missing skills that explain the gap, and tell the user to add them to the CV only when they "
            "genuinely have the skill and can support it with evidence. Never encourage inventing or falsely "
            "claiming skills. Be concise, structured, and practical.\n\n"
            f"JOB-BOARD CONTEXT:\n{grounded_context}\n\nUSER QUESTION:\n{question}"
        )
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        body = response.json()
        parts = (body.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if p.get("text")).strip()
        return text or fallback
    except Exception:
        return fallback

def _normalise_skill_set(skills):
    return {str(s).strip().lower() for s in (skills or []) if str(s).strip()}


def _job_context(job):
    if not job:
        return ""
    return (
        f"Title: {job.get('title')}\n"
        f"Company: {job.get('company')}\n"
        f"Source: {job.get('source')}\n"
        f"Location: {job.get('location')}\n"
        f"Role category: {job.get('role_category')}\n"
        f"Experience level: {job.get('experience_level') or job.get('experience')}\n"
        f"Skills/tags: {', '.join(job.get('skills') or [])}\n"
        f"Description: {(job.get('description') or '')[:6000]}"
    )


def _answer_rule_based(question: str, resume_skills=None, job=None, jobs_all=None, compare_job=None) -> str:
    has_resume = bool(resume_skills)
    resume_skills = resume_skills or []
    intent = detect_intent(question)
    resume_set = _normalise_skill_set(resume_skills)

    if intent == "suitability" and job:
        if not has_resume:
            return (
                f"I can assess '{job.get('title')}' at {job.get('company')}, but no resume is loaded yet. "
                "Upload your resume first and I’ll compare your skills and experience with this specific job."
            )

        job_skills = list(job.get("skills") or [])
        job_set = _normalise_skill_set(job_skills)
        overlap = resume_set & job_set
        missing = sorted(job_set - resume_set)
        pct = round(100 * len(overlap) / max(len(job_set), 1))
        matched = [s for s in job_skills if str(s).strip().lower() in overlap]
        missing_display = [s for s in job_skills if str(s).strip().lower() in set(missing)]

        if pct >= 70:
            verdict = "Strong skills match. Review the full description and experience requirements before applying."
        elif pct >= 40:
            verdict = "Partial skills match. Your background has relevant overlap, but there are important gaps to address."
        else:
            verdict = "Lower current skills match. Apply selectively unless your resume contains relevant experience that is not captured by the extracted tags."

        gap_pct = max(0, 100 - pct)
        if missing_display:
            gap_guidance = (
                f"The remaining {gap_pct}% represents tagged skills not currently detected in your resume: "
                f"{_fmt_skills(missing_display)}.\n"
                "Only add a missing skill to your CV if you genuinely have that skill through work, projects, "
                "coursework, certification, or other verifiable experience. Add evidence rather than listing it "
                "without proof."
            )
        else:
            gap_guidance = (
                "No tagged skill gaps were detected. Focus on strengthening evidence, quantified impact, and "
                "role-specific experience instead of adding unsupported skills."
            )

        summary = (
            f"CV match: {pct}%\n"
            f"CV skill gap: {gap_pct}%\n"
            f"Already covered: {_fmt_skills(matched)}\n"
            f"Skills not currently shown on your CV: {_fmt_skills(missing_display)}"
        )
        fallback = (
            f"What to improve:\n{gap_guidance}\n\n"
            f"{verdict}"
        )
        context = (
            f"Selected job:\n{_job_context(job)}\n\n"
            f"Candidate resume skills: {', '.join(resume_skills)}\n\n"
            f"Computed tagged-skill match: {pct}%\n"
            f"Computed tagged-skill gap: {gap_pct}%\n"
            f"Matched skills: {', '.join(matched)}\n"
            f"Missing tagged skills: {', '.join(missing_display)}"
        )
        ai_analysis = _gemini_answer(
            GEMINI_API_KEY if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("PASTE_YOUR_") else "",
            question,
            context,
            fallback,
        )
        return (
            f"Fit analysis for '{job.get('title')}' at {job.get('company')}\n\n"
            f"{summary}\n\n"
            f"{ai_analysis}"
        )

    if intent == "missing_skills" and job:
        if not has_resume:
            return (
                f"To identify your missing skills for '{job.get('title')}', I need your resume. "
                "Upload it first and I’ll compare it with the selected job."
            )
        job_skills = list(job.get("skills") or [])
        missing = [s for s in job_skills if str(s).strip().lower() not in resume_set]
        if not missing:
            fallback = f"Your resume currently covers all tagged skills for '{job.get('title')}'."
        else:
            fallback = (
                f"For '{job.get('title')}' at {job.get('company')}, the main tagged skills not found in your resume are: "
                f"{_fmt_skills(missing)}. Focus on the most relevant gaps first."
            )
        context = f"Selected job:\n{_job_context(job)}\n\nCandidate resume skills: {', '.join(resume_skills)}"
        return _gemini_answer(GEMINI_API_KEY if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("PASTE_YOUR_") else "", question, context, fallback)

    if intent == "explain_jd" and job:
        fallback = (
            f"'{job.get('title')}' at {job.get('company')} ({job.get('location')}, {job.get('source')}). "
            f"Role category: {job.get('role_category')}. Experience: {job.get('experience_level')}. "
            f"Key skills: {_fmt_skills(job.get('skills'))}. "
            f"Summary: {(job.get('description') or 'No description provided.')[:500]}"
        )
        return _gemini_answer(GEMINI_API_KEY if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("PASTE_YOUR_") else "", question, _job_context(job), fallback)

    if intent == "which_to_apply" and jobs_all:
        if not has_resume:
            return "Upload your resume first. I’ll rank relevant jobs using your extracted skills and the job descriptions."
        job_set_scores = []
        for j in jobs_all:
            j_set = _normalise_skill_set(j.get("skills"))
            overlap = len(resume_set & j_set)
            if overlap > 0:
                job_set_scores.append((overlap, j))
        job_set_scores.sort(key=lambda x: x[0], reverse=True)
        top = job_set_scores[:5]
        if not top:
            return "I couldn't find strong skill overlaps yet. Try uploading a more detailed resume or browse by role category."
        lines = [f"- {j['title']} at {j['company']} ({j['source']}) — {n} shared skills" for n, j in top]
        return "Based on your uploaded resume, these currently look like your strongest skill matches:\n" + "\n".join(lines)

    if intent == "prep_guidance" and job:
        job_skills = list(job.get("skills") or [])
        missing = [s for s in job_skills if str(s).strip().lower() not in resume_set] if has_resume else job_skills
        fallback = (
            f"To prepare for '{job.get('title')}', focus on the core skills tagged for the role: {_fmt_skills(job_skills)}. "
        )
        if missing:
            fallback += f"Priority gaps to review: {_fmt_skills(missing)}. "
        fallback += "Use the job description to prepare concrete examples from your projects or work experience."
        return _gemini_answer(GEMINI_API_KEY if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("PASTE_YOUR_") else "", question, _job_context(job) + f"\n\nCandidate resume skills: {', '.join(resume_skills)}", fallback)

    if intent == "compare_jobs" and job and compare_job:
        set_a = _normalise_skill_set(job.get("skills"))
        set_b = _normalise_skill_set(compare_job.get("skills"))
        shared = set_a & set_b
        only_a = set_a - set_b
        only_b = set_b - set_a
        return (
            f"'{job.get('title')}' ({job.get('company')}) vs '{compare_job.get('title')}' ({compare_job.get('company')}):\n"
            f"- Shared skills: {_fmt_skills(sorted(shared))}\n"
            f"- Unique to {job.get('title')}: {_fmt_skills(sorted(only_a))}\n"
            f"- Unique to {compare_job.get('title')}: {_fmt_skills(sorted(only_b))}\n"
            f"- Experience level: {job.get('experience_level')} vs {compare_job.get('experience_level')}"
        )

    if intent == "resume_improve" and job:
        if not has_resume:
            return "Upload your resume first. Then I can suggest specific changes for this selected job."
        job_set = _normalise_skill_set(job.get("skills"))
        missing = [s for s in (job.get("skills") or []) if str(s).strip().lower() not in resume_set]
        if not missing:
            fallback = f"Your resume currently covers the key tagged skills for '{job.get('title')}'. Consider quantifying project or work impact and tailoring the summary to this role."
        else:
            fallback = f"To improve your fit for '{job.get('title')}', add credible evidence for: {_fmt_skills(missing)}. Use projects, work experience or coursework where applicable."
        context = _job_context(job) + f"\n\nCandidate resume skills: {', '.join(resume_skills)}"
        return _gemini_answer(GEMINI_API_KEY if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("PASTE_YOUR_") else "", question, context, fallback)

    if not job and intent in ("suitability", "missing_skills", "explain_jd", "prep_guidance", "resume_improve"):
        return "Select a specific job first (click a job card) and I can answer that precisely using the selected job and your uploaded resume."
    if intent == "compare_jobs" and not compare_job:
        return "To compare two jobs, select a second job after opening the first one, then ask me to compare them."

    return (
        "I can help with job suitability, missing skills, job-description explanations, job recommendations, "
        "interview preparation, job comparisons, and resume improvements. Open a specific job for the most precise answer."
    )


def answer(question, resume_skills=None, job=None, jobs_all=None, compare_job=None, gemini_api_key=None):
    # Supported intents have their own grounded handlers. They may call Gemini
    # with richer, intent-specific context exactly once.
    intent = detect_intent(question)
    if intent != "general":
        return _answer_rule_based(question, resume_skills, job, jobs_all, compare_job)

    fallback = _answer_rule_based(question, resume_skills, job, jobs_all, compare_job)
    api_key = GEMINI_API_KEY if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("PASTE_YOUR_") else ""
    context = {
        "resume_loaded": bool(resume_skills),
        "resume_skills": resume_skills or [],
        "selected_job": job,
        "comparison_job": compare_job,
    }
    return _gemini_answer(
        api_key,
        question,
        json.dumps(context, ensure_ascii=False)[:30000],
        fallback,
    )
