# BullPen backend

FastAPI + SQLite + Gemini. Runs on http://localhost:8000; CORS allows http://localhost:5173.

## Setup (once, from `backend/`)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Put `GEMINI_API_KEY=...` in the repo-root `.env` (optional: `GEMINI_MODEL`, default `gemini-3.8-flash`).
PDF generation needs the `tectonic` CLI on PATH (`winget install TectonicTypesetting.Tectonic`).

## Run (from `backend/`)

```powershell
.venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Test (from `backend/`)

```powershell
.venv\Scripts\python -m pytest -q
```

## Routes

| Route | Owner | Notes |
|---|---|---|
| `POST /profile` | A | multipart: files `resume` (PDF), `schedule` (image); optional form fields `name, email, phone, address, work_authorization, transportation, year_in_school, preferred_cities, min_pay, max_commute_minutes` (`preferred_cities` is semicolon separated, e.g. `Tampa, FL; Orlando, FL`). Form values override what's extracted. |
| `GET /jobs?mode=internship\|parttime[&refresh=true]` | A | ranked job objects (shared contract), cached per profile |
| `GET /jobs/{id}/commute` | B (stub) | commute object |
| `POST /queue/{id}` | C (stub) | `{"status": "queued", "job_id"}` |
| `POST /prepare[?refresh=true]` | A | `{"documents": [{job_id, status, resume_url, cover_letter_url, error, warnings, cached}]}` for queued internships; reuses this profile's PDFs |
| `POST /apply` | C (stub) | `{"status": "started"}` |
| `POST /auto?threshold=80` | A | `{"queued": [ids], "documents": [...]}` |
| `POST /myjob`, `GET /myjob/today`, `GET /myjob/calendar.ics`, `POST /chat` | B (stubs) | |

Generated PDFs are served from `/generated/<job_id>/resume.pdf` and `/generated/<job_id>/cover_letter.pdf`.

There is no auth. The "current profile" is the most recent `POST /profile`.

`/profile`, `/jobs`, `/prepare` and `/auto` run through one LangGraph `StateGraph` (`graph.py`). Ranked jobs and
tailored PDFs are cached per profile in SQLite, so repeat demo calls never wait on Gemini; pass `refresh=true` to redo.
