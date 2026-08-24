"""
Job enrichment utilities with deterministic validation/fallback.

AI/LLM enrichment is supported by ``enrich_with_gemini.py`` during dataset
preparation. This module provides the deterministic validation/fallback layer
used when an enriched field is missing, malformed, or needs normalization.
That separation keeps the runtime job board reproducible and avoids making a
network call for every search request.

Approach:
- Validate/augment skills with a curated, word-boundary-safe dictionary.
- Normalize role categories into stable application-facing buckets.
- Normalize experience into candidate-facing bands.
- Preserve source-provided structured metadata rather than discarding it.
"""
import re

SKILL_DICTIONARY = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Rust",
    "SQL", "NoSQL", "MongoDB", "PostgreSQL", "MySQL", "Redis",
    "React", "Angular", "Vue", "Node.js", "Django", "Flask", "Express",
    "REST API", "GraphQL", "HTML", "CSS", "Redux",
    "Machine Learning", "Deep Learning", "Generative AI", "LLM", "NLP",
    "Computer Vision", "TensorFlow", "PyTorch", "Scikit-learn", "Pandas",
    "NumPy", "MLOps", "LangChain", "Prompt Engineering", "OpenAI API",
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "CI/CD", "Terraform",
    "Linux", "Git", "Jenkins",
    "Excel", "Power BI", "Tableau", "Statistics", "Data Visualization",
    "A/B Testing", "Data Analysis",
    "Selenium", "Manual Testing", "API Testing", "Test Automation",
    "DSA", "Problem Solving", "Communication", "Requirement Gathering",
    "Research", "Agile", "Scrum",
]

ROLE_CATEGORY_KEYWORDS = {
    "Data Science / ML": ["data scientist", "machine learning", "ml engineer", "ai engineer", "generative ai"],
    "Software Development": ["software engineer", "backend", "frontend", "full stack", "developer"],
    "Data / Business Analytics": ["data analyst", "business analyst", "research analyst"],
    "DevOps / Infrastructure": ["devops", "site reliability", "infrastructure", "cloud engineer"],
    "QA / Testing": ["qa engineer", "test engineer", "quality assurance"],
    "Internship": ["intern"],
}

EXPERIENCE_PATTERNS = [
    (r"\bfresher\b", "Fresher"),
    (r"\b0-1\s*(?:years|yrs)\b", "0-1 years"),
    (r"\b(\d+)\s*-\s*(\d+)\s*(?:years|yrs)\b", None),  # dynamic range, handled separately
    (r"\b(\d+)\+\s*(?:years|yrs)\b", None),
]


def _compile_skill_patterns():
    # One regex pass is substantially faster than one search per skill for a
    # 50k+ listing corpus.
    ordered = sorted(SKILL_DICTIONARY, key=len, reverse=True)
    parts = [re.escape(s) for s in ordered]
    return re.compile(r"(?<![\\w/])(" + "|".join(parts) + r")(?![\\w/])", re.IGNORECASE)

_SKILL_PATTERN = _compile_skill_patterns()

def extract_skills(text: str):
    if not text:
        return []
    return sorted({m.group(1) for m in _SKILL_PATTERN.finditer(text)}, key=str.lower)


def extract_experience(text: str, fallback: str = None):
    """Normalize raw experience into candidate-facing experience bands."""
    value = str(fallback or "").strip()

    if text:
        text_l = text.lower()

        if re.search(r"\bfresher\b|\bentry[- ]level\b", text_l):
            return "Fresher"

        m = re.search(r"\b(\d+)\s*-\s*(\d+)\s*(?:years|yrs)\b", text_l)
        if m:
            low = float(m.group(1))
            if low < 1:
                return "0-1 years"
            if low < 3:
                return "1-3 years"
            if low < 5:
                return "3-5 years"
            if low < 8:
                return "5-8 years"
            return "8+ years"

        m = re.search(r"\b(\d+)\+\s*(?:years|yrs)\b", text_l)
        if m:
            years = float(m.group(1))
            if years < 1:
                return "0-1 years"
            if years < 3:
                return "1-3 years"
            if years < 5:
                return "3-5 years"
            if years < 8:
                return "5-8 years"
            return "8+ years"

        m = re.search(r"\b(\d+)\s*(?:years|yrs)\b", text_l)
        if m:
            value = m.group(1)

    numeric = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", value)
    if numeric:
        years = float(numeric.group(1))
        if years <= 0:
            return "Fresher"
        if years <= 1:
            return "0-1 years"
        if years <= 3:
            return "1-3 years"
        if years <= 5:
            return "3-5 years"
        if years <= 8:
            return "5-8 years"
        return "8+ years"

    if "," in value:
        return "Not specified"

    if value.lower() in {"fresher", "entry level", "entry-level"}:
        return "Fresher"

    return "Not specified"


def classify_role_category(title: str, description: str = ""):
    haystack = f"{title} {description}".lower()
    for category, keywords in ROLE_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in haystack:
                return category
    return "General"


def enrich_job(job: dict) -> dict:
    """Enrich one normalized record with deterministic NLP signals.

    The supplied dataset already contains an extracted ``skills`` field.
    We merge it with skills found in title/description so we never discard
    source-provided metadata.
    """
    text = f"{job.get('title', '')} {job.get('description', '')}"
    supplied = job.get("skills") or []
    if isinstance(supplied, str):
        supplied = [s.strip() for s in supplied.split(",") if s.strip()]
    # The supplied dataset already contains extracted skills for most rows.
    # Only scan the full description when source metadata is missing.
    extracted = extract_skills(text) if not supplied else []
    job["skills"] = sorted(set(map(str, supplied)) | set(extracted), key=str.lower)
    job["role_category"] = classify_role_category(job.get("title", ""))
    job["experience_level"] = extract_experience("", job.get("experience"))
    return job
