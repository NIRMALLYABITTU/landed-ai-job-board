"""
Generates a sample multi-platform job dataset with the SAME SHAPE as the
dataset you'll be given for the assignment (LinkedIn / Naukri / Indeed /
Internshala listings).

IMPORTANT: This is placeholder/synthetic data only, used so the app runs
out of the box. Once you download the real dataset from the Google Drive
link in the brief, just replace data/jobs_raw.json with that file (same
"source" / "title" / "company" / "description" fields, or close to it —
the loader in load_data.py normalizes common field-name variations).
"""
import json
import random
import hashlib

random.seed(42)

SOURCES = ["LinkedIn", "Naukri", "Indeed", "Internshala"]

ROLES = [
    ("Data Analyst", ["SQL", "Excel", "Python", "Power BI", "Tableau", "Statistics"]),
    ("Machine Learning Engineer", ["Python", "TensorFlow", "PyTorch", "Machine Learning", "MLOps", "Docker"]),
    ("Generative AI Engineer", ["Python", "Generative AI", "LLM", "LangChain", "Prompt Engineering", "OpenAI API"]),
    ("Backend Developer", ["Python", "Django", "REST API", "PostgreSQL", "AWS", "Docker"]),
    ("Frontend Developer", ["JavaScript", "React", "HTML", "CSS", "TypeScript", "Redux"]),
    ("Full Stack Developer", ["JavaScript", "Node.js", "React", "MongoDB", "Express", "REST API"]),
    ("Data Scientist", ["Python", "Machine Learning", "SQL", "Pandas", "Statistics", "Deep Learning"]),
    ("DevOps Engineer", ["AWS", "Docker", "Kubernetes", "CI/CD", "Terraform", "Linux"]),
    ("Business Analyst", ["Excel", "SQL", "Power BI", "Communication", "Requirement Gathering"]),
    ("Research Analyst", ["Python", "SQL", "Research", "Excel", "Statistics", "Data Visualization"]),
    ("Software Engineer Intern", ["Python", "Java", "DSA", "Git", "Problem Solving"]),
    ("QA Engineer", ["Selenium", "Manual Testing", "API Testing", "Python", "Test Automation"]),
]

COMPANIES = [
    "Nexora Labs", "BluePeak Technologies", "Vertex Analytics", "CloudNine Systems",
    "Northwind Software", "Pixel & Co", "DataForge", "Skyline Consulting",
    "Bright Path AI", "Orbit Solutions", "Granite Works", "Fenwick Digital",
    "Solstice Tech", "Marlin Software", "Ivory Cloud", "Kestrel Analytics",
]

LOCATIONS = ["Bangalore", "Kolkata", "Hyderabad", "Pune", "Remote", "Gurugram", "Mumbai", "Chennai"]

EXPERIENCE_BUCKETS = ["Fresher", "0-1 years", "1-3 years", "2-4 years", "3-5 years", "5+ years"]

DESC_TEMPLATE = (
    "We are looking for a {role} to join our team in {location}. "
    "The ideal candidate should have experience with {skills}. "
    "Responsibilities include working on real-world projects, collaborating with "
    "cross-functional teams, and delivering high quality outcomes. "
    "Experience required: {experience}. Strong problem-solving and communication "
    "skills are a plus. This is a great opportunity to grow with a fast moving team."
)


def make_job(idx, source, dup_of=None):
    role, skill_pool = random.choice(ROLES)
    company = random.choice(COMPANIES)
    location = random.choice(LOCATIONS)
    experience = random.choice(EXPERIENCE_BUCKETS)
    skills = random.sample(skill_pool, k=min(4, len(skill_pool)))
    description = DESC_TEMPLATE.format(
        role=role, location=location, skills=", ".join(skills), experience=experience
    )
    job_id = f"{source.lower()}_{idx}"
    return {
        "id": job_id,
        "source": source,
        "title": role,
        "company": company,
        "location": location,
        "experience": experience,
        "description": description,
        "url": f"https://example.com/jobs/{job_id}",
        "posted_date": f"2026-0{random.randint(1,7)}-{random.randint(10,28)}",
    }


def main():
    jobs = []
    idx = 1
    for source in SOURCES:
        for _ in range(12):
            jobs.append(make_job(idx, source))
            idx += 1

    # Inject a handful of *intentional* near-duplicates across platforms
    # (same role posted on two sources) so dedup logic has something to catch.
    for i in range(5):
        base = random.choice(jobs).copy()
        base["id"] = f"dup_{i}"
        base["source"] = random.choice(SOURCES)
        base["url"] = f"https://example.com/jobs/dup_{i}"
        jobs.append(base)

    with open("data/jobs_raw.json", "w") as f:
        json.dump(jobs, f, indent=2)

    print(f"Wrote {len(jobs)} sample jobs to data/jobs_raw.json")


if __name__ == "__main__":
    main()
