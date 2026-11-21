# BullPen backend

FastAPI + SQLite + Gemini. Runs on http://localhost:8000; CORS allows http://localhost:5173.

## Setup (once, from `backend/`)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Put `GEMINI_API_KEY=...` in the repo-root `.env` (optional: `GEMINI_MODEL`, default `gemini-3.8-flash`).
PDF generation needs the `tectonic` CLI on PATH (`winget install TectonicTypesetting.Tectonic`).
Commutes (teammate B, `agents/commute.py`) need `GOOGLE_MAPS_API_KEY=...` in the same `.env`: a Google Cloud key
with the Routes API enabled. Without it, `/jobs` cards get `commute: null` (scored by straight-line distance),
`/jobs/{id}/commute` returns `minutes: null` with an `error` field, and the My Job routes return 503.
Optional: `CAR_FREE_MAX_MIN` (default 45), `HART_FARE` (default 2.00).
Demo safety switch (optional, off by default): `BULLPEN_APPLY_URL_OVERRIDE=http://localhost:5173/mock-workday/demo`
makes `POST /apply` open every queued job at that URL instead of its real `apply_url`, so a live demo never touches
real employer sites. `/queue` still returns the real URLs. Read when `/apply` is called; restart the backend after
changing it in `.env`.

## Run (from `backend/`)

```powershell
.venv\Scripts\python -m uvicorn main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

## Test (from `backend/`)

```powershell
.venv\Scripts\python -m pytest -q
```

## Before the demo (server running, profile created)

```powershell
.venv\Scripts\python scripts\warm_demo.py
```

Calls `/jobs` for both modes, queues the top 3 internships, runs `/prepare`, and prints job / score / status /
cached / warnings, so every demo click is served from cache.

## Routes

| Route | Owner | Notes |
|---|---|---|
| `GET /health` | A | `{"ok": true, "profile_id", "tectonic", "gemini_key_loaded"}` (booleans only, never the key) |
| `POST /profile` | A | multipart: files `resume` (PDF), `schedule` (image); optional form fields `name, email, phone, address, work_authorization, transportation, year_in_school, preferred_cities, min_pay, max_commute_minutes, country, phone_device_type, how_heard` (`preferred_cities` is semicolon separated, e.g. `Tampa, FL; Orlando, FL`). Form values override what's extracted. `country` defaults to `United States of America` when the address ends in a US state; `phone_device_type` (e.g. `Mobile`) and `how_heard` stay empty unless the student sets them. The apply worker fills Workday's Country, Phone Device Type and How Did You Hear dropdowns only from these. |
| `GET /jobs?mode=internship\|parttime[&refresh=true]` | A | ranked job objects (shared contract), cached per profile; part-time jobs carry B's commute from the student's address (null if unavailable) |
| `GET /jobs/{id}/commute` | B | commute object for a part-time job (404 otherwise); cached in SQLite `commute_cache` |
| `POST /queue/{id}` | C (stub) | `{"status": "queued", "job_id"}`; also starts a background job-description fetch for internships |
| `POST /prepare[?refresh=true]` | A | `{"documents": [{job_id, status, resume_url, cover_letter_url, error, warnings, cached}]}` for queued internships; reuses this profile's PDFs |
| `GET /profile/current` | A | the current profile JSON (400 if none) |
| `GET /queue` | A | `[{job_id, title, company, apply_url, status, resume_url, cover_letter_url, warnings, cached}]` for the current profile; `status` is `not_prepared` before `/prepare`, URLs are null unless this profile's PDFs exist; `cached` is true when they do (the next `/prepare` reuses them) |
| `POST /apply` | A | starts `apply_worker/apply.py` as a background process: `{"status": "started"}`, or `{"status": "already_running"}`. With `BULLPEN_APPLY_URL_OVERRIDE` set, every tab opens that URL instead (see below) |
| `GET /apply/status` | A | `{"jobs": [{job_id, status, filled_count, needs_you}]}` from `apply_worker/status.json`; status is `opening`, `waiting_for_signin`, `filling`, `ready_for_review` or `error` |
| `POST /auto?threshold=80` | A | `{"queued": [ids], "documents": [...]}` |
| `POST /myjob` | B | body `{employer, address, shifts: [{day, start, end}], home_address?}` -> `{"ok": true}` |
| `GET /myjob` | B | the saved job, or `{}` |
| `GET /myjob/today` | B | next shift with `leave_by`, `arrive_by`, `minutes`, `cost_usd`, `steps` (404 before `POST /myjob`, 503 if the Routes API is unavailable) |
| `GET /myjob/calendar.ics` | B | "Leave for ..." events for the next 4 weeks of shifts (503 if the Routes API is unavailable) |
| `POST /chat` | B | `{"message"}` -> `{"reply"}`; missed-bus help via Gemini calling the Routes API (503 if Gemini is unavailable) |

Generated PDFs are served from `/generated/<job_id>/resume.pdf` and `/generated/<job_id>/cover_letter.pdf`.

Teammate B's routes live in `routes_b.py` and are mounted with `app.include_router`. Their helper script (needs
the Maps key; run from `backend/`): `python -m tools.b_setup bullrunner|geocode|warm`. `geocode` fills `lat`/`lng`
in `data/part_time_jobs.json`; `warm` caches every job's commute from the current profile's address
before the demo (then call `/jobs?mode=parttime&refresh=true` once so the ranked-jobs cache picks them up).

## Apply worker (`apply_worker/`)

Setup once, from `apply_worker/`:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

`POST /apply` starts it with the backend URL. To run it by hand (backend running, jobs queued and prepared):

```powershell
.venv\Scripts\python apply.py --backend http://localhost:8000
```

Try it without the backend (mock Workday page, fake profile, placeholder PDFs; add `--signin` for the sign-in wait):

```powershell
.venv\Scripts\python apply.py --mock
```

Tests (headless, against `mock/workday_mock.html`): `.venv\Scripts\python -m pytest -q tests`. The same tests against
the React page (Vite running): `.venv\Scripts\python -m pytest -q tests --mock-url http://localhost:5173/mock-workday/demo`.
A headed run against it: `.venv\Scripts\python apply.py --mock --mock-url http://localhost:5173/mock-workday/demo`.

It opens one visible Chromium tab per queued job and never submits: it clicks only Apply, Apply Manually, Save and
Continue (once, My Information to My Experience) and Add, fills what the profile answers, outlines what's left in
pink, and adds a corner checklist ("Needs you", "Your choice" for voluntary questions). On a sign-in page it shows a
banner and waits until you click its Continue button. Sign-ins persist in `apply_worker/browser_profile/`
(gitignored). The field map is `workday_fields.json`, and `mock/workday_mock.html` is the test page. `MOCK_FIELDS.md`
is generated by `python make_mock_fields.py`.

There is no auth. The "current profile" is the most recent `POST /profile`.

`/profile`, `/jobs`, `/prepare` and `/auto` run through one LangGraph `StateGraph` (`graph.py`). Ranked jobs and
tailored PDFs are cached per profile in SQLite, so repeat demo calls never wait on Gemini; pass `refresh=true` to redo.
