# Fielded — AI Job Board

A Flask job board built from the supplied structured JSON dataset. The JSON is the source of truth; SQLite is the derived runtime query layer.

## Fixed in this pass — why deploys weren't working

**Root cause: the database build step used 1.68 GB of RAM at peak**, because
`load_data.py` called `json.load()` on the entire ~380MB decompressed
dataset at once, holding the raw parse tree and the normalized copies in
memory simultaneously. Render's free **and** Starter web-service tiers are
both capped at **512 MB RAM** — so the build was getting OOM-killed before
the app ever started. This is very likely why nothing you deployed worked:
the build never finished.

**Fix:** `load_data.py` now stream-parses the JSON with `ijson`, one
record at a time, instead of loading the whole array into memory. Verified
before/after on this exact dataset (56,769 records, 59MB gzipped):

| | Before | After |
|---|---|---|
| Peak RAM during build | 1.68 GB | **24.5 MB** |
| Build time | 15.6s | 8.1s (faster too) |

I confirmed this with a full clean-clone simulation: fresh checkout →
`pip install -r requirements.txt` → the exact Render `buildCommand` →
`verify_project.py` → `smoke_test.py` → `gunicorn app:app ...` (the exact
Render `startCommand`) → live HTTP requests against every endpoint. All
green. Runtime (serving) memory peaks around 250-290MB under load, which
also fits comfortably in 512MB.

**Second fix:** `utils/assistant.py` defaulted `GEMINI_API_KEY` to the
literal string `"PASTE_YOUR_GEMINI_API_KEY_HERE"` when the env var wasn't
set. That string is truthy, so every chat message was silently attempting
a real (doomed) network call to Google's API and waiting out a timeout
before falling back to the local answer — adding needless latency on every
single chat message when no key is configured. Now it defaults to `""` and
skips the network call entirely when no real key is present. The Gemini
integration remains fully optional either way — the assistant answers
correctly from local grounded logic with zero API keys and zero cost; see
`utils/assistant.py`'s docstring.

## Included dataset

- 56,769 source records
- 45,853 deduplicated jobs
- 10,916 duplicate records merged
- 508 source/platform names in the supplied dataset

The dataset supplied for the assignment does not contain Naukri or Indeed records in the current file. The source selector therefore displays the platforms actually present rather than fabricating records.

## Deploy today (Render — recommended, matches the bundled `render.yaml`)

1. Push this folder to a GitHub repo (a pre-built `jobboard.db` is
   intentionally **not** included — `render.yaml`'s build step regenerates
   it from `data/jobs_normalized.json.gz` automatically, and that file
   fits well under GitHub's 100MB limit).
2. On [render.com](https://render.com): **New +** → **Blueprint** → connect
   your repo. Render will detect `render.yaml` automatically and prefill
   the build/start commands and the health check path.
3. When prompted for `GEMINI_API_KEY`, you can leave it blank — the app
   works fully without it (see above). Set it later if you want Gemini-
   polished chat answers.
4. Deploy. The build step (`pip install` + `load_data.py`) takes well
   under a minute now; watch the logs for `Unique jobs stored: 45,853`.
5. Free-tier note: the service spins down after 15 minutes idle and takes
   ~30-60s to wake on the next request — normal, not a bug. Use the
   Starter tier ($7/mo) if you need it always-on for a live demo.

If you'd rather deploy via Docker (Railway, Fly.io, etc.), the `Dockerfile`
runs the same fixed build step and needs no changes.

## Local Windows run

Recommended: Python 3.11–3.12. Python 3.14 may work, but package wheel availability can vary.

### One-click-ish setup

Run `start_windows.bat` from this folder. It creates/uses `venv`, installs dependencies, verifies the database/search/resume/recommendation pipeline, and starts Flask.

### Manual

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python load_data.py data/jobs_normalized.json.gz --reset
python verify_project.py
python app.py
```

Open `http://127.0.0.1:5000`.

(A prior version of this README said not to run `load_data.py` because a
pre-built `jobboard.db` shipped in the folder. That db is no longer
bundled — see above — so you do need to run it once on a fresh clone.)

## Gemini (optional)

`utils/assistant.py` reads `GEMINI_API_KEY` from the environment. If unset,
the assistant uses its local grounded rule-based logic — no network call,
no cost, fully functional. Set the environment variable (never commit a
real key to the file) if you want Gemini-polished answers layered on top
of the same grounded context.

For Render, set `GEMINI_API_KEY` under Environment Variables/Secrets — optional.

## Render

This repo includes `render.yaml`.

Build command:

```text
pip install -r requirements.txt && python load_data.py data/jobs_normalized.json.gz --reset
```

Start command:

```text
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

Set `GEMINI_API_KEY` as a Render secret. Never commit the real key.

## Architecture

```text
Supplied JSON
    ↓
Normalization + deterministic enrichment
    ↓
Deduplication by title + company + location
    ↓
SQLite runtime database
    ↓
Flask REST API
    ├── Search / filters
    ├── Job details
    ├── Resume parsing
    ├── Explainable recommendations
    └── Grounded Gemini assistant
```

## API

- `GET /api/health`
- `GET /api/stats`
- `GET /api/sources`
- `GET /api/jobs`
- `GET /api/jobs/<hash>`
- `POST /api/resume/upload`
- `GET /api/recommendations`
- `POST /api/chat`
