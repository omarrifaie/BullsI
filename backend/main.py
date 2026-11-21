"""BullPen backend. /profile, /jobs, /prepare, /auto run through the LangGraph supervisor (graph.py).
Teammate-owned routes are stubs."""
import json
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import db  # noqa: E402
import graph  # noqa: E402
import routes_b  # noqa: E402
from agents import jobdesc, scout  # noqa: E402
from latex.render import tectonic_path  # noqa: E402
from models import Job  # noqa: E402

logger: logging.Logger = logging.getLogger("bullpen")
GENERATED_DIR: Path = graph.GENERATED_DIR
GENERATED_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
SCHEDULE_MIMES: set[str] = {"image/png", "image/jpeg", "image/webp"}
APPLY_WORKER_DIR: Path = Path(__file__).resolve().parent.parent / "apply_worker"
_apply_proc: Optional[subprocess.Popen[bytes]] = None


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
app.include_router(routes_b.router)  # teammate B: /jobs/{id}/commute, /myjob, /myjob/today, /myjob/calendar.ics, /chat


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


@app.get("/health")
def health() -> dict[str, Any]:
  """Liveness for teammates. Reports whether the key is loaded, never the key itself."""
  exe: Optional[str] = tectonic_path()
  return {
    "ok": True,
    "profile_id": _current_profile_id(),
    "tectonic": bool(exe) and Path(exe).is_file(),
    "gemini_key_loaded": bool(os.environ.get("GEMINI_API_KEY")),
  }


@app.get("/profile/current")
def current_profile() -> dict[str, Any]:
  return _require_profile()


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
  country: Optional[str] = Form(None),
  phone_device_type: Optional[str] = Form(None),
  how_heard: Optional[str] = Form(None),
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
    "country": country, "phone_device_type": phone_device_type, "how_heard": how_heard,
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


# Owned by teammate C. Stub.
@app.post("/queue/{job_id}")
def queue_job(job_id: str) -> dict[str, Any]:
  job: dict[str, Any] = _find_job(job_id)
  db.add_to_queue(_current_profile_id(), job_id)
  if job["mode"] == "internship":
    jobdesc.prefetch(job)  # background, returns immediately; /prepare waits at most 10 s for it
  return {"status": "queued", "job_id": job_id}


@app.delete("/queue/{job_id}")
def unqueue_job(job_id: str) -> dict[str, Any]:
  """Take a job off the current profile's queue. No-op if it isn't queued; tailored PDFs stay cached."""
  db.remove_from_queue(_current_profile_id(), job_id)
  return {"status": "removed", "job_id": job_id}


@app.post("/prepare")
def prepare(request: Request, refresh: bool = False) -> dict[str, Any]:
  """Tailored PDFs for every queued internship; reuses this profile's earlier PDFs unless refresh=true."""
  profile: dict[str, Any] = _require_profile()
  state: graph.BullPenState = graph.run(
    {"action": "prepare", "profile": profile, "queue": db.get_queue(profile["id"]), "refresh": refresh})
  return {"documents": _public_documents(request, state["documents"])}


@app.get("/queue")
def get_queue(request: Request) -> list[dict[str, Any]]:
  """Queued jobs for the current profile with their apply_url and newest tailored PDFs (for the apply worker).
  `cached` is true when this profile's PDFs are on disk, so the next /prepare reuses them."""
  profile_id: int = _require_profile()["id"]
  out: list[dict[str, Any]] = []
  for job_id in db.get_queue(profile_id):
    job: dict[str, Any] = _find_job(job_id)
    doc: Optional[dict[str, Any]] = graph._cached_document(profile_id, job_id)  # only this profile's PDFs on disk
    if doc is None:
      latest: Optional[dict[str, Any]] = db.latest_document(job_id)
      mine: bool = latest is not None and latest["profile_id"] == profile_id
      doc = {"job_id": job_id, "status": latest["status"] if mine else "not_prepared",
             "error": latest.get("error") if mine else None, "warnings": latest["warnings"] if mine else []}
    public: dict[str, Any] = _public_documents(request, [doc])[0]
    out.append({"job_id": job_id, "title": job["title"], "company": job["company"], "apply_url": job["apply_url"],
                "status": public["status"], "resume_url": public["resume_url"],
                "cover_letter_url": public["cover_letter_url"], "warnings": public["warnings"],
                "cached": public["cached"]})
  return out


@app.post("/apply")
def apply(request: Request) -> dict[str, str]:
  """Start the Playwright apply worker (apply_worker/apply.py) unless one is already running."""
  global _apply_proc
  if _apply_proc is not None and _apply_proc.poll() is None:
    return {"status": "already_running"}
  venv_python: Path = APPLY_WORKER_DIR / ".venv" / "Scripts" / "python.exe"
  python: str = str(venv_python) if venv_python.is_file() else sys.executable
  backend_url: str = str(request.base_url).rstrip("/")
  args: list[str] = [python, "apply.py", "--backend", backend_url]
  override: str = os.environ.get("BULLPEN_APPLY_URL_OVERRIDE", "").strip()
  if override:  # demo safety switch: every queued job opens this page instead of its real apply_url
    args += ["--apply-url-override", override]
  _apply_proc = subprocess.Popen(args, cwd=APPLY_WORKER_DIR)
  return {"status": "started"}


@app.get("/apply/status")
def apply_status() -> dict[str, Any]:
  """Per-job progress the worker writes to apply_worker/status.json."""
  path: Path = APPLY_WORKER_DIR / "status.json"
  if not path.is_file():
    return {"jobs": []}
  return json.loads(path.read_text(encoding="utf-8"))


@app.post("/auto")
def auto(request: Request, threshold: int = Query(80, ge=0, le=100)) -> dict[str, Any]:
  """Queue and prepare every internship scoring at or above threshold."""
  state: graph.BullPenState = graph.run(
    {"action": "auto", "profile": _require_profile(), "mode": "internship", "threshold": threshold})
  return {"queued": state["queue"], "documents": _public_documents(request, state["documents"])}

