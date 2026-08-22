"""
Explainable resume-to-job ranking.

1. Scan the full job inventory for explicit skill overlap.
2. Keep a bounded candidate pool so a 50k+ dataset stays responsive.
3. Run TF-IDF cosine similarity on title/description/skills for that pool.
4. Blend semantic similarity (60%) with skill coverage (40%).
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def _job_document(job):
    return f"{job.get('title','')} {job.get('description','')} {' '.join(job.get('skills',[])*3)}"

def recommend_jobs(resume_text,resume_skills,jobs,top_n=10,candidate_limit=3000):
    if not jobs: return []
    resume_set={s.lower() for s in (resume_skills or [])}
    ranked=[]
    for j in jobs:
        js={s.lower() for s in (j.get("skills") or [])}
        overlap=len(resume_set & js)
        coverage=overlap/max(len(resume_set),1)
        ranked.append((coverage,overlap,j))
    ranked.sort(key=lambda x:(x[0],x[1],x[2].get("posted_date") or ""),reverse=True)
    candidates=[x[2] for x in ranked[:candidate_limit]]
    docs=[_job_document(j) for j in candidates]
    docs.append(resume_text or " ".join(resume_skills))
    vectorizer=TfidfVectorizer(stop_words="english",max_features=10000)
    matrix=vectorizer.fit_transform(docs)
    sims=cosine_similarity(matrix[-1],matrix[:-1])[0]
    scored=[]
    for j,sim in zip(candidates,sims):
        js={s.lower() for s in (j.get("skills") or [])}
        overlap=resume_set & js
        coverage=len(overlap)/max(len(resume_set),1)
        final=.6*float(sim)+.4*coverage
        scored.append({**j,"match_score":round(final*100,1),
                       "matched_skills":sorted(overlap)})
    scored.sort(key=lambda x:(x["match_score"],x.get("posted_date") or ""),reverse=True)
    return scored[:top_n]
