"""
Resume parsing — extracts raw text from PDF / DOCX / TXT resumes, then
reuses the same local skill-tagger used for job descriptions so resume
skills and job skills live in the same vocabulary (this is what makes
matching meaningful instead of comparing apples to oranges).
"""
import os
from .tagger import extract_skills, extract_experience


def extract_text(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(filepath)
    elif ext == ".docx":
        return _extract_docx(filepath)
    elif ext in (".txt",):
        with open(filepath, "r", errors="ignore") as f:
            return f.read()
    else:
        raise ValueError(f"Unsupported resume format: {ext}. Use PDF, DOCX, or TXT.")


def _extract_pdf(filepath):
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    reader = PdfReader(filepath)
    text = []
    for page in reader.pages:
        text.append(page.extract_text() or "")
    return "\n".join(text)


def _extract_docx(filepath):
    import docx
    doc = docx.Document(filepath)
    return "\n".join(p.text for p in doc.paragraphs)


def parse_resume(filepath: str) -> dict:
    text = extract_text(filepath)
    skills = extract_skills(text)
    experience = extract_experience(text)
    return {
        "raw_text": text,
        "skills": skills,
        "experience_level": experience,
    }
