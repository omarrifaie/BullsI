"""BullPen backend. /profile, /jobs, /prepare, /auto run through the LangGraph supervisor (graph.py).
Teammate-owned routes are stubs."""
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
import graph  # noqa: E402
from agents import scout  # noqa: E402
from fake_data import FAKE_COMMUTE, FAKE_PARTTIME  # noqa: E402
from models import Job  # noqa: E402

logger: logging.Logger = logging.getLogger("bullpen")
GENERATED_DIR: Path = graph.GENERATED_DIR
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


def _current_profile_id() -> Optional[int]:
  profile: Optional[dict[str, Any]] = db.latest_profile()
  return profile["id"] if profile else None


def _public_documents(request: Request, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Graph stores paths relative to /generated; the API returns absolute URLs."""
  out: list[dict[str, Any]] = []
  for d in docs:
    urls: dict[str, Optional[str]] = {
      key: str(request.url_for("generated", path=d[key])) if d.get(key) else None
      for key in ("resume_url", "cover_letter_url")
    }
    out.append({"job_id": d["job_id"], "status": d["status"], **urls, "error": d.get("error"),
                "warnings": d.get("warnings") or [], "cached": bool(d.get("cached"))})
  return out


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
  uploads: dict[str, Any] = {"resume": resume_bytes, "schedule": schedule_bytes, "schedule_mime": schedule_mime,
                             "form": form}
  try:
    state: graph.BullPenState = await run_in_threadpool(graph.run, {"action": "profile", "uploads": uploads})
  except Exception as exc:
    logger.exception("Profile agent failed")
    raise HTTPException(status_code=502, detail=f"Profile extraction failed: {type(exc).__name__}") from exc
  return state["profile"]


@app.get("/jobs")
def get_jobs(mode: Literal["internship", "parttime"] = Query(...), refresh: bool = False) -> list[dict[str, Any]]:
  """Ranked jobs, cached per profile; refresh=true re-runs Scout + Matcher."""
  state: graph.BullPenState = graph.run(
    {"action": "jobs", "profile": _require_profile(), "mode": mode, "refresh": refresh})
  return [Job.model_validate(j).model_dump() for j in state["jobs"]]


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
def prepare(request: Request, refresh: bool = False) -> dict[str, Any]:
  """Tailored PDFs for every queued internship; reuses this profile's earlier PDFs unless refresh=true."""
  profile: dict[str, Any] = _require_profile()
  state: graph.BullPenState = graph.run(
    {"action": "prepare", "profile": profile, "queue": db.get_queue(profile["id"]), "refresh": refresh})
  return {"documents": _public_documents(request, state["documents"])}


# Owned by teammate C. Stub.
@app.post("/apply")
def apply() -> dict[str, str]:
  return {"status": "started"}


@app.post("/auto")
def auto(request: Request, threshold: int = Query(80, ge=0, le=100)) -> dict[str, Any]:
  """Queue and prepare every internship scoring at or above threshold."""
  state: graph.BullPenState = graph.run(
    {"action": "auto", "profile": _require_profile(), "mode": "internship", "threshold": threshold})
  return {"queued": state["queue"], "documents": _public_documents(request, state["documents"])}


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
