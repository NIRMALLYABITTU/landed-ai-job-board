"""
Optional LLM enrichment for the supplied dataset.

This is intentionally a preprocessing tool, not a required runtime call.
Set GEMINI_API_KEY in your local environment; never commit it.
It enriches batches of jobs with role_category, experience_level and tags.
"""
import json, os, argparse, requests

MODEL="gemini-2.5-flash"
URL=f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

def enrich_batch(batch,key):
    prompt="""Return ONLY a JSON array with one object per job, in the same order.
For each job extract:
- role_category: concise category such as Data Science / ML, Software Development, Data / Business Analytics, DevOps / Infrastructure, QA / Testing, Product, Sales, Marketing, HR, Finance, Operations, Other
- experience_level: Fresher, 0-1 years, 1-3 years, 3-5 years, 5+ years, or Not specified
- tags: 3-12 important skills/technologies/keywords.
Do not invent skills not supported by the title/description.
Jobs:
""" + json.dumps([{"title":x.get("title"),"description":x.get("description","")[:5000]} for x in batch],ensure_ascii=False)
    r=requests.post(URL,params={"key":key},json={"contents":[{"parts":[{"text":prompt}]}]},timeout=90)
    r.raise_for_status()
    text=r.json()["candidates"][0]["content"]["parts"][0]["text"]
    text=text.replace("```json","").replace("```","").strip()
    return json.loads(text)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--batch-size",type=int,default=20)
    a=ap.parse_args()
    key=os.getenv("GEMINI_API_KEY")
    if not key: raise SystemExit("Set GEMINI_API_KEY in your environment; it is never stored by this script.")
    with open(a.input,encoding="utf-8") as f: jobs=json.load(f)
    for i in range(0,len(jobs),a.batch_size):
        batch=jobs[i:i+a.batch_size]
        result=enrich_batch(batch,key)
        for job,tags in zip(batch,result):
            job["role_category"]=tags.get("role_category") or job.get("role_category")
            job["experience_level"]=tags.get("experience_level") or job.get("experience_level")
            job["skills"]=sorted(set((job.get("skills") or [])+(tags.get("tags") or [])),key=str.lower)
        print(f"Enriched {min(i+a.batch_size,len(jobs)):,}/{len(jobs):,}",flush=True)
    with open(a.output,"w",encoding="utf-8") as f: json.dump(jobs,f,ensure_ascii=False,separators=(",",":"))
if __name__=="__main__": main()
