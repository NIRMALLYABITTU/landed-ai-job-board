# LANDED — AI-Powered Job Board

**Find the job. Understand the fit. Land the role.**

## Submission Links — REQUIRED

- **Live deployed prototype:** `https://landed-ai-job-board.onrender.com/`
- **Explanation video (English, view access enabled):** `https://drive.google.com/file/d/1EK9qz5ExXyC-wPZ4W8VgSGhas3LJTLJr/view?usp=sharing`
- **Public GitHub repository:** https://github.com/NIRMALLYABITTU/landed-ai-job-board

LANDED is an AI-powered job discovery platform built for the AlmaBetter Research Analyst hiring assignment. It uses the supplied structured job dataset as its primary source of truth and turns that dataset into a searchable, deduplicated, filterable job board with resume matching and a grounded Gemini assistant.

## What LANDED does

LANDED combines five major capabilities in one web application:

1. **Multi-platform job search** across the supplied dataset.
2. **Structured job enrichment** for skills, role categories and experience bands.
3. **Explainable resume-to-job recommendations** using skill overlap and TF-IDF similarity.
4. **AI Job Assistant** for job explanations, suitability analysis, skill gaps, preparation and recommendations.
5. **Candidate-friendly discovery filters** for platform, experience, work mode and location.

The application is designed around the assignment requirement that the provided JSON data—not live scraping—must be the primary job source.

---

## Dataset and data pipeline

The supplied dataset contains **56,769 source job records**. LANDED applies normalisation and deduplication before the application uses the records.

Current verified result from the supplied dataset:

| Metric | Value |
|---|---:|
| Source records | 56,769 |
| Unique jobs after deduplication | 45,853 |
| Duplicate records merged | 10,916 |
|

The canonical deduplication key is based on normalised:

```text
job title + company + location
```

Cross-posted records can therefore be merged while preserving platform-specific source IDs and source URLs.

### Runtime storage

The application uses **SQLite** as the runtime query store. The JSON dataset is treated as the source dataset; SQLite is the derived application database used for search, filtering, recommendations and job detail retrieval.

The data flow is:

```text
Supplied JSON dataset
        ↓
Normalization
        ↓
Skill / experience / role enrichment
        ↓
Deduplication
        ↓
SQLite runtime database
        ↓
Flask API
        ↓
LANDED frontend
```

---

## Supported job sources

The supplied dataset contains job records from multiple platforms. LANDED supports platform filtering using the source information in the dataset.

The application can expose sources such as:

- LinkedIn
- Naukri
- Indeed
- Internshala

The application does **not** scrape these platforms.

---

## AI / LLM-based classification pipeline

The assignment explicitly asks for AI/LLM-based processing of job descriptions. LANDED addresses that requirement with a preprocessing pipeline in `enrich_with_gemini.py`. The preprocessing flow is:

```text
Supplied job description
        ↓
Gemini structured extraction
        ↓
skills + role_category + experience_level
        ↓
deterministic validation/normalization
        ↓
SQLite runtime database
```

The Gemini step is **preprocessing**, not a runtime dependency for every search. If an LLM enrichment request is unavailable, the deterministic `utils/tagger.py` layer provides a reproducible fallback and normalises the output into the same schema. This makes the architecture explainable and keeps search reliable.

`enrich_with_gemini.py` never stores the Gemini key; it reads `GEMINI_API_KEY` from the environment.

## AI / NLP enrichment

LANDED enriches job records before they reach the UI.

### Skills and technologies

The tagger extracts technical skills and technologies from job content and stores them as structured tags.

Examples include:

```text
Python
SQL
Machine Learning
Generative AI
PostgreSQL
Redis
Docker
AWS
Rust
Tokio
```

### Role classification

Jobs are assigned a role category to improve the quality of discovery and recommendations.

### Experience normalisation

Raw numeric or textual experience signals are converted into user-friendly bands:

```text
Fresher
0-1 years
1-3 years
3-5 years
5-8 years
8+ years
Not specified
```

This prevents the UI from exposing inconsistent raw values such as `2`, `5`, `10`, or malformed values from the source data.

---

## Job search and filtering

The search engine supports keyword search across multiple job fields, including:

- Title
- Company
- Location
- Description
- Skills
- Role category
- Domain
- Location requirement

The filter layer supports:

```text
Platform
Role category
Experience level
Work mode
Location
```

### Work mode

The work-mode filter is designed around the job information available in the supplied dataset:

```text
Any work mode
Remote
Hybrid
On-site
Not specified
```

### Location

Locations are populated dynamically from the database rather than being hard-coded into the frontend.

---

## Resume matching and personalised recommendations

Candidates can upload a resume in:

```text
PDF
DOCX
TXT
```

The resume is parsed locally and converted into structured candidate signals, including detected skills, an experience band, and a role/category signal.

### Recommendation pipeline

```text
Resume
  ↓
Resume parser
  ↓
Candidate skills + experience + role signals
  ↓
Skill-overlap candidate retrieval
  ↓
TF-IDF semantic similarity
  ↓
Experience-fit scoring
  ↓
Role-relevance scoring
  ↓
Weighted final ranking
  ↓
Top recommendations
```

The current ranking is intentionally explainable:

| Component | Weight |
|---|---:|
| Job-description / title semantic similarity (TF-IDF) | 35% |
| Skill coverage | 30% |
| Experience fit | 20% |
| Role relevance | 15% |

Each result exposes matched skills and the score components so the recommendation can be defended during an interview.

## Explainable CV match and skill gaps

When a candidate asks whether they are suitable for a selected job, LANDED produces an explicit skill comparison.

The assistant can report:

```text
CV match: 70%
CV skill gap: 30%
Already covered: Python, SQL, PostgreSQL
Skills not currently shown: Docker, AWS, Kubernetes
```

The application also gives an important safety rule: a missing skill should only be added to the CV when the candidate genuinely has that skill and can support it with evidence such as work experience, projects, coursework or certification.

This keeps the recommendation explainable without encouraging false claims on a resume.

---

## AI Job Assistant

LANDED includes a conversational job assistant grounded in the selected job and candidate context.

Supported use cases include:

- **Am I suitable for this job?**
- **What skills am I missing?**
- **Explain this job description.**
- **Which jobs should I apply for?**
- **How should I prepare for this role?**
- **Compare two jobs.**
- **What should I improve in my resume for this opportunity?**

### Grounding strategy

The assistant does not treat Gemini as the source of truth for job facts.

The flow is:

```text
User question
      ↓
Selected job/candidate context retrieved
      ↓
Structured grounded context
      ↓
Gemini
      ↓
Answer
```

The prompt instructs the model not to invent job facts, companies, salaries, dates or requirements.

### Gemini API key

The assistant supports **both** deployment-level and user-provided Gemini keys:

1. **Render/server key:** `GEMINI_API_KEY` is the secure default for the deployment.
2. **User-provided key:** the assistant UI accepts an optional Gemini key and sends it only with the current chat request. It is not written to the database, Flask session, browser local storage, or filesystem.

For local development on PowerShell:

```powershell
$env:GEMINI_API_KEY="YOUR_REAL_GEMINI_KEY"
python app.py
```

For Render, add `GEMINI_API_KEY` under the service's environment variables. A user-entered key takes precedence for that request only.

No key is committed to this public repository.

---

## Backend architecture

LANDED is a Flask application with a SQLite runtime database.

### Main backend components

```text
app.py
├── Flask web server
├── REST API
├── Resume upload / parsing flow
├── Recommendation flow
├── Authentication endpoints
└── AI assistant endpoint

 database.py
├── SQLite connection management
├── Job storage
├── Deduplication support
├── Search / filtering
├── Statistics
├── Recommendation candidate retrieval
└── User persistence

 utils/tagger.py
├── Skill extraction
├── Experience normalization
├── Role classification
└── Job enrichment

 utils/recommender.py
└── Resume/job similarity and ranking

 utils/resume_parser.py
└── PDF / DOCX / TXT resume parsing

 utils/assistant.py
└── Grounded rule-based assistant + optional Gemini enhancement
```

### API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /` | Main application UI |
| `GET /api/health` | Backend/database health check |
| `GET /api/stats` | Job-board statistics |
| `GET /api/sources` | Sources, roles, experience, work modes and locations |
| `GET /api/jobs` | Search/filter/paginate jobs |
| `GET /api/jobs/<job_hash>` | Retrieve a specific job |
| `POST /api/resume/upload` | Parse and store a session-scoped resume profile |
| `GET /api/recommendations` | Return resume-based recommendations |
| `POST /api/chat` | Grounded AI assistant interaction |
| `POST /api/auth/signup` | Create an account |
| `POST /api/auth/login` | Authenticate a user |
| `POST /api/auth/logout` | End a session |
| `GET /api/auth/me` | Return the current authenticated user |

---

## Frontend architecture

The frontend is server-rendered HTML with JavaScript-driven API interactions.

### Key frontend features

- Hero search
- Animated job counters
- Platform filter
- Role filter
- Experience filter
- Work-mode filter
- Location filter
- Pagination
- Job detail drawer
- Source-specific application links
- Resume upload and parsing state
- Recommendation cards
- AI assistant panel
- Loading, empty and error states

The primary frontend files are:

```text
 templates/index.html
 static/app.js
 static/style.css
```

---

## Running locally

### Requirements

Recommended local runtime:

```text
Python 3.14.x
```

### Create a virtual environment

Windows PowerShell:

```powershell
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
```

### Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### Load the database

Only needed when starting from a fresh database:

```powershell
python load_data.py data/jobs_normalized.json.gz --reset
```

### Run the app

```powershell
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

### Health check

```text
http://127.0.0.1:5000/api/health
```

---

## Render deployment

LANDED is structured for deployment as a Flask Web Service.

The repository contains deployment configuration for Gunicorn and Render.

Typical commands:

```text
Build:
pip install -r requirements.txt && python load_data.py data/jobs_normalized.json.gz --reset

Start:
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

The production health endpoint is:

```text
/api/health
```

### Required environment variables

```text
SECRET_KEY
GEMINI_API_KEY
```

`SECRET_KEY` should be generated by the hosting provider or supplied as a secure secret.

`GEMINI_API_KEY` should never be committed to the public repository.

---

## Security and privacy

LANDED follows these principles:

- No live scraping is performed.
- No Gemini API key is stored in the browser when configured server-side.
- Resume files are temporary and deleted after parsing.
- Password hashes are never returned to clients.
- API errors are returned as JSON for API routes.
- Uploaded file size is limited to 5 MB.
- Supported resume types are explicitly restricted to PDF, DOCX and TXT.

For a public production deployment, use platform-managed secrets rather than embedding credentials in source code.

---

## Product decisions and interview talking points

### Why SQLite?

The JSON dataset is the assignment's source dataset, but repeatedly scanning a large JSON file for every request is inefficient. SQLite provides indexed, structured querying while keeping the system simple and reproducible.

### Why deduplicate?

The same job can be present across multiple platforms. A canonical identity based on title, company and location reduces repeated listings while preserving source-specific URLs and IDs.

### Why deterministic enrichment first?

Skills, role categories and experience bands should be explainable. Deterministic enrichment gives repeatable structured signals that are easy to validate and explain before any LLM is involved.

### Why candidate-first retrieval for recommendations?

The recommender first finds a bounded pool using skill overlap, then applies similarity ranking. This reduces computation while preserving relevant candidates.

### Why ground Gemini?

The LLM is used as an interpretation and explanation layer. Structured job and candidate information remains the source of truth.

---

## Assignment requirement mapping

| Assignment requirement | LANDED implementation |
|---|---|
| Multi-platform job data | Supplied JSON dataset + source filter |
| No scraping | No live scraping pipeline |
| Efficient data processing | JSON → normalized SQLite |
| Deduplication | Canonical title/company/location key |
| AI / LLM classification | Gemini preprocessing + deterministic validation/fallback |
| Structured filters | Platform, role, experience, work mode, location |
| Resume parsing | PDF / DOCX / TXT |
| Job recommendations | Skill overlap + TF-IDF + experience fit + role relevance |
| Explainable recommendations | Matched skills + gaps + rationale |
| AI assistant | Seven assignment intents + grounded Gemini enhancement + user-supplied key support |
| Public deployment | Flask + Gunicorn + Render configuration |
| Security | Environment secrets + temporary resume handling |

---

## Project structure

```text
landed-ai-job-board/
│
├── app.py
├── database.py
├── load_data.py
├── enrich_with_gemini.py
├── requirements.txt
├── render.yaml
├── Procfile
├── Dockerfile
├── .gitignore
├── README.md
│
├── data/
│   └── jobs_normalized.json.gz
│
├── templates/
│   └── index.html
│
├── static/
│   ├── app.js
│   └── style.css
│
└── utils/
    ├── assistant.py
    ├── recommender.py
    ├── resume_parser.py
    └── tagger.py
```

---

## Current limitations

The supplied job dataset is a static assignment dataset rather than a live feed. Therefore:

- "Jobs added today" reflects the dates present in the supplied data, not live portal updates.
- Search results are limited to the supplied source dataset.
- AI recommendations are only as good as the extracted resume/job signals.
- Gemini is an optional enhancement; the grounded local assistant should remain usable when Gemini is unavailable.

---

## License / assignment note

This project was built as an assignment prototype using the supplied job dataset. The repository should not be interpreted as an authorized scraper or mirror of the listed job platforms.
