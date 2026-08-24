"""LLM preprocessing for the supplied job dataset.

This script is intentionally a preprocessing step, not a runtime requirement.
It uses Gemini to classify jobs into a stable schema, then the normal runtime
pipeline can load the resulting enriched JSON/JSON.GZ into SQLite.

The API key is read from GEMINI_API_KEY and is never written to output files.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
from pathlib import Path

import requests

PREFERRED_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]


def load_jobs(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_jobs(path: Path, jobs):
    if path.suffix == ".gz":
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, separators=(",", ":"))
    else:
        with path.open("w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, separators=(",", ":"))


def choose_model(api_key: str) -> str:
    headers = {"x-goog-api-key": api_key}
    r = requests.get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    models = r.json().get("models", [])
    available = {
        str(m.get("name", "")).split("/")[-1]
        for m in models
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    }
    for model in PREFERRED_MODELS:
        if model in available:
            return model
    for model in sorted(available):
        if model.startswith("gemini"):
            return model
    raise RuntimeError("No Gemini model supporting generateContent is available for this key.")


def extract_json_array(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
    text = re.sub(r"```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Gemini did not return a JSON array.")
    return json.loads(text[start : end + 1])


def enrich_batch(batch, api_key, model):
    prompt = (
        "Return ONLY a JSON array with one object per job, in the same order. "
        "For each job return exactly: role_category, experience_level, tags. "
        "role_category must be a concise job family. experience_level must be one of "
        "Fresher, 0-1 years, 1-3 years, 3-5 years, 5-8 years, 8+ years, Not specified. "
        "tags must contain 3-12 concrete skills, technologies, frameworks, tools, or domain keywords. "
        "Use only evidence present in the title or description. Do not invent requirements.\n\n" +
        json.dumps(
            [
                {
                    "title": item.get("title", ""),
                    "description": (item.get("description") or "")[:7000],
                }
                for item in batch
            ],
            ensure_ascii=False,
        )
    )
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=90,
    )
    r.raise_for_status()
    parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    text = "\n".join(p.get("text", "") for p in parts if p.get("text"))
    result = extract_json_array(text)
    if len(result) != len(batch):
        raise ValueError(f"Expected {len(batch)} enrichment rows but received {len(result)}.")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set GEMINI_API_KEY in the environment; it is never stored by this script.")

    source = Path(args.input)
    output = Path(args.output)
    jobs = load_jobs(source)
    model = choose_model(key)

    for i in range(0, len(jobs), args.batch_size):
        batch = jobs[i : i + args.batch_size]
        result = enrich_batch(batch, key, model)
        for job, extracted in zip(batch, result):
            if not isinstance(extracted, dict):
                continue
            job["role_category"] = extracted.get("role_category") or job.get("role_category")
            job["experience_level"] = extracted.get("experience_level") or job.get("experience_level")
            tags = extracted.get("tags") or []
            if not isinstance(tags, list):
                tags = [tags]
            existing = job.get("skills") or []
            if isinstance(existing, str):
                existing = [x.strip() for x in existing.split(",") if x.strip()]
            job["skills"] = sorted({str(x).strip() for x in [*existing, *tags] if str(x).strip()}, key=str.lower)
        print(f"Enriched {min(i + args.batch_size, len(jobs)):,}/{len(jobs):,}", flush=True)

    write_jobs(output, jobs)
    print(f"Wrote {len(jobs):,} enriched jobs to {output}")


if __name__ == "__main__":
    main()
