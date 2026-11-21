"""BullPen backend. Real: /profile, /jobs, /auto ranking. Still fake: /prepare PDFs (M4). Teammate routes are stubs."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Optional

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import db  # noqa: E402
from agents import matcher, scout  # noqa: E402
from agents import profile as profile_agent  # noqa: E402
from fake_data import FAKE_COMMUTE, FAKE_PARTTIME, write_placeholder_pdf  # noqa: E402
from models import Job  # noqa: E402

logger: logging.Logger = logging.getLogger("bullpen")
GENERATED_DIR: Path = Path(__file__).resolve().parent / "generated"
GENERATED_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
SCHEDULE_MIMES: set[str] = {"image/png", "image/jpeg", "image/webp"}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
  db.init_db()
  yield


app: FastAPI = FastAPI(title="BullPen", lifespan=lifespan)
app.add_middleware(
  CORSMiddleware,
  allow_origins=["http://localhost:5173"],
  allow_methods=["*"],
  allow_headers=["*"],
)
app.mount("/generated", StaticFiles(directory=GENERATED_DIR), name="generated")


def _find_job(job_id: str) -> dict[str, Any]:
  job: Optional[dict[str, Any]] = scout.find_job(job_id)
  if job is None:
    raise HTTPException(status_code=404, detail=f"Unknown job id {job_id}")
  return job


def _require_profile() -> dict[str, Any]:
  profile: Optional[dict[str, Any]] = db.latest_profile()
  if profile is None:
    raise HTTPException(status_code=400, detail="No profile yet. POST /profile first.")
  return profile


def _ranked_jobs(mode: str) -> list[dict[str, Any]]:
  """Scout + Matcher. Output is validated against the contract (drops internal 'meta')."""
  profile: dict[str, Any] = _require_profile()
  jobs: list[dict[str, Any]] = scout.fetch_internships() if mode == "internship" else scout.load_part_time()
  return [Job.model_validate(j).model_dump() for j in matcher.rank(profile, jobs)]


def _current_profile_id() -> Optional[int]:
  profile: Optional[dict[str, Any]] = db.latest_profile()
  return profile["id"] if profile else None


def _prepare(request: Request, job_ids: list[str]) -> list[dict[str, Any]]:
  """M1 stub: writes placeholder PDFs for queued internships."""
  profile_id: Optional[int] = _current_profile_id()
  docs: list[dict[str, Any]] = []
  for job_id in job_ids:
    job: Optional[dict[str, Any]] = scout.find_job(job_id)
    if job is None or job["mode"] != "internship":
      continue
    write_placeholder_pdf(GENERATED_DIR / job_id / "resume.pdf", f"Resume for {job['title']} at {job['company']}")
    write_placeholder_pdf(GENERATED_DIR / job_id / "cover_letter.pdf", f"Cover letter for {job['company']}")
    doc: dict[str, Any] = {
      "job_id": job_id,
      "status": "ready",
      "resume_url": str(request.url_for("generated", path=f"{job_id}/resume.pdf")),
      "cover_letter_url": str(request.url_for("generated", path=f"{job_id}/cover_letter.pdf")),
      "error": None,
    }
    db.save_document(profile_id, doc)
    docs.append(doc)
  return docs


@app.post("/profile")
async def create_profile(
  resume: UploadFile = File(...),
  schedule: UploadFile = File(...),
  name: Optional[str] = Form(None),
  email: Optional[str] = Form(None),
  phone: Optional[str] = Form(None),
  address: Optional[str] = Form(None),
  work_authorization: Optional[Literal["citizen", "permanent_resident", "needs_sponsorship"]] = Form(None),
  transportation: Optional[str] = Form(None),
  year_in_school: Optional[str] = Form(None),
  preferred_cities: Optional[str] = Form(None),  # semicolon separated: "Tampa, FL; Orlando, FL"
  min_pay: Optional[float] = Form(None),
  max_commute_minutes: Optional[int] = Form(None),
) -> dict[str, Any]:
  resume_bytes: bytes = await resume.read(MAX_UPLOAD_BYTES + 1)
  schedule_bytes: bytes = await schedule.read(MAX_UPLOAD_BYTES + 1)
  if len(resume_bytes) > MAX_UPLOAD_BYTES or len(schedule_bytes) > MAX_UPLOAD_BYTES:
    raise HTTPException(status_code=413, detail="Files must be under 10 MB")
  if not resume_bytes.startswith(b"%PDF"):
    raise HTTPException(status_code=400, detail="resume must be a PDF")
  schedule_mime: str = schedule.content_type or ""
  if schedule_mime not in SCHEDULE_MIMES:
    raise HTTPException(status_code=400, detail="schedule must be a PNG, JPEG, or WebP image")
  form: dict[str, Any] = {
    "name": name, "email": email, "phone": phone, "address": address,
    "work_authorization": work_authorization, "transportation": transportation,
    "year_in_school": year_in_school, "preferred_cities": preferred_cities,
    "min_pay": min_pay, "max_commute_minutes": max_commute_minutes,
  }
  try:
    profile: dict[str, Any] = await run_in_threadpool(
      profile_agent.run, resume_bytes, schedule_bytes, schedule_mime, form)
  except Exception as exc:
    logger.exception("Profile agent failed")
    raise HTTPException(status_code=502, detail=f"Profile extraction failed: {type(exc).__name__}") from exc
  profile["id"] = db.save_profile(profile)
  return profile


@app.get("/jobs")
def get_jobs(mode: Literal["internship", "parttime"] = Query(...)) -> list[dict[str, Any]]:
  return _ranked_jobs(mode)


# Owned by teammate B. Stub.
@app.get("/jobs/{job_id}/commute")
def get_commute(job_id: str) -> dict[str, Any]:
  _find_job(job_id)
  return FAKE_COMMUTE


# Owned by teammate C. Stub.
@app.post("/queue/{job_id}")
def queue_job(job_id: str) -> dict[str, Any]:
  _find_job(job_id)
  db.add_to_queue(_current_profile_id(), job_id)
  return {"status": "queued", "job_id": job_id}


@app.post("/prepare")
def prepare(request: Request) -> dict[str, Any]:
  return {"documents": _prepare(request, db.get_queue(_current_profile_id()))}


# Owned by teammate C. Stub.
@app.post("/apply")
def apply() -> dict[str, str]:
  return {"status": "started"}


@app.post("/auto")
def auto(request: Request, threshold: int = Query(80, ge=0, le=100)) -> dict[str, Any]:
  profile_id: Optional[int] = _current_profile_id()
  picked: list[str] = [j["id"] for j in _ranked_jobs("internship") if j["match"]["score"] >= threshold]
  for job_id in picked:
    db.add_to_queue(profile_id, job_id)
  return {"queued": picked, "documents": _prepare(request, picked)}


# Owned by teammate B. Stubs.
@app.post("/myjob")
def save_myjob(job: dict[str, Any] = Body(...)) -> dict[str, Any]:
  db.save_myjob(job)
  return {"status": "saved", "myjob": job}


@app.get("/myjob/today")
def myjob_today() -> dict[str, Any]:
  job: dict[str, Any] = db.get_myjob() or FAKE_PARTTIME[0]
  return {"job": job, "shift": {"day": "Tue", "start": "15:00", "end": "21:00"},
          "commute": FAKE_COMMUTE, "leave_by": "14:18"}


@app.get("/myjob/calendar.ics")
def myjob_calendar() -> Response:
  ics: str = "\r\n".join([
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BullPen//EN",
    "BEGIN:VEVENT", "UID:bullpen-shift-1@bullpen", "DTSTAMP:20261121T120000Z",
    "DTSTART:20261124T150000", "DTEND:20261124T210000", "RRULE:FREQ=WEEKLY;BYDAY=TU,TH",
    "SUMMARY:Barista shift - Bulls Brew Cafe", "LOCATION:5010 E Fowler Ave\\, Tampa\\, FL 33617",
    "END:VEVENT", "END:VCALENDAR", "",
  ])
  return Response(content=ics, media_type="text/calendar")


class ChatIn(BaseModel):
  message: str


@app.post("/chat")
def chat(body: ChatIn) -> dict[str, str]:
  return {"reply": "Your next shift is Tuesday 15:00-21:00. Leave by 14:18 to catch the Bull Runner C."}
