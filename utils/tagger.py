"""
AI-based job classification & tagging — WITHOUT any external API key.

Approach:
- A curated skills/technology dictionary (extensible) is matched against
  job description text using word-boundary-safe regex, so "R" doesn't
  match inside "Research" etc.
- Role category is inferred from title keywords.
- Experience level is extracted via regex patterns ("2-4 years",
  "fresher", "0-1 yrs", etc).
- This is deliberately deterministic/local (no network, no API key) so it
  always works offline. It's easy to swap in a transformer-based NER /
  zero-shot classifier later (see README) without changing the interface.
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
    """
    Convert raw experience information into structured experience bands.

    Supported bands:
    Fresher
    0-1 years
    1-3 years
    3-5 years
    5-8 years
    8+ years
    Not specified
    """

    value = str(fallback or "").strip()

    # First check the actual job description.
    if text:
        text_l = text.lower()

        if re.search(r"\bfresher\b|\bentry[- ]level\b", text_l):
            return "Fresher"

        # Explicit ranges such as 2-4 years
        m = re.search(r"\b(\d+)\s*-\s*(\d+)\s*(?:years|yrs)\b", text_l)

        if m:
            low = float(m.group(1))

            if low < 1:
                return "0-1 years"
            elif low < 3:
                return "1-3 years"
            elif low < 5:
                return "3-5 years"
            elif low < 8:
                return "5-8 years"
            else:
                return "8+ years"

        # Values such as 5+ years
        m = re.search(r"\b(\d+)\+\s*(?:years|yrs)\b", text_l)

        if m:
            years = float(m.group(1))

            if years < 1:
                return "0-1 years"
            elif years < 3:
                return "1-3 years"
            elif years < 5:
                return "3-5 years"
            elif years < 8:
                return "5-8 years"
            else:
                return "8+ years"

        # Values such as "3 years"
        m = re.search(r"\b(\d+)\s*(?:years|yrs)\b", text_l)

        if m:
            value = m.group(1)

    # Handle numeric dataset values such as 0, 1, 2, 3, 5, 10.
    numeric = re.match(r"^\s*(\d+(?:\.\d+)?)\s*$", value)

    if numeric:
        years = float(numeric.group(1))

        if years <= 0:
            return "Fresher"
        elif years <= 1:
            return "0-1 years"
        elif years <= 3:
            return "1-3 years"
        elif years <= 5:
            return "3-5 years"
        elif years <= 8:
            return "5-8 years"
        else:
            return "8+ years"

    # Handle malformed values such as "200,022".
    # Do not allow these to become a misleading experience category.
    if "," in value:
        return "Not specified"

    # Preserve explicit fresher information.
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
