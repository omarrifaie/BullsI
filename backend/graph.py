"""LangGraph supervisor: one StateGraph, shared state, routes each request to the agents it needs.

  profile  : START -> profile -> END
  jobs     : START -> load_jobs -(cache miss)-> scout -> match -> END
  prepare  : START -> tailor -> END
  auto     : START -> load_jobs -> [scout -> match] -> select -> tailor -> END

Caches (SQLite, per profile id, so a new profile never sees stale results):
  ranked jobs   -> cache table, key jobs:<profile_id>:<mode>   (bypass with refresh=True)
  tailored PDFs -> documents table + files in generated/<job_id>/ (reused if this profile made the newest ones)
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

import db
from agents import jobdesc, matcher, scout
from agents import profile as profile_agent
from agents import tailor as tailor_agent
from latex.render import LatexError

GENERATED_DIR: Path = Path(__file__).resolve().parent / "generated"
PREPARE_WORKERS: int = 4


class BullPenState(TypedDict, total=False):
  action: Literal["profile", "jobs", "prepare", "auto"]
  uploads: dict[str, Any]  # profile action: resume/schedule bytes, schedule mime, form answers
  profile: dict[str, Any]
  mode: Literal["internship", "parttime"]
  refresh: bool
  jobs: list[dict[str, Any]]
  jobs_cached: bool
  threshold: int
  queue: list[str]
  documents: list[dict[str, Any]]


def _jobs_key(state: BullPenState) -> str:
  return f"jobs:{state['profile']['id']}:{state['mode']}"


# ---------- nodes ----------

def profile_node(state: BullPenState) -> BullPenState:
  up: dict[str, Any] = state["uploads"]
  profile: dict[str, Any] = profile_agent.run(up["resume"], up["schedule"], up["schedule_mime"], up["form"])
  profile["id"] = db.save_profile(profile)
  return {"profile": profile}


def load_jobs_node(state: BullPenState) -> BullPenState:
  cached: Optional[list[dict[str, Any]]] = None if state.get("refresh") else db.cache_get(_jobs_key(state))
  return {"jobs": cached or [], "jobs_cached": cached is not None}


def scout_node(state: BullPenState) -> BullPenState:
  jobs: list[dict[str, Any]] = scout.fetch_internships() if state["mode"] == "internship" else scout.load_part_time()
  return {"jobs": jobs}


def match_node(state: BullPenState) -> BullPenState:
  ranked: list[dict[str, Any]] = matcher.rank(state["profile"], state["jobs"])
  db.cache_set(_jobs_key(state), ranked)
  return {"jobs": ranked}


def select_node(state: BullPenState) -> BullPenState:
  picked: list[str] = [j["id"] for j in state["jobs"]
                       if j["mode"] == "internship" and j["match"]["score"] >= state["threshold"]]
  for job_id in picked:
    db.add_to_queue(state["profile"]["id"], job_id)
  return {"queue": picked}


def _cached_document(profile_id: int, job_id: str) -> Optional[dict[str, Any]]:
  doc: Optional[dict[str, Any]] = db.latest_document(job_id)
  if not doc or doc["profile_id"] != profile_id or doc["status"] != "ready":
    return None
  if not all((GENERATED_DIR / job_id / name).exists() for name in ("resume.pdf", "cover_letter.pdf")):
    return None
  # Rebuild paths from the job id: rows written before M5 stored absolute URLs.
  return {**doc, "resume_url": f"{job_id}/resume.pdf", "cover_letter_url": f"{job_id}/cover_letter.pdf",
          "cached": True}


def _prepare_one(profile: dict[str, Any], job: dict[str, Any], refresh: bool) -> dict[str, Any]:
  """Never raises: a failed job comes back as status "error" so the rest of the batch still succeeds."""
  if not refresh and (hit := _cached_document(profile["id"], job["id"])):
    return hit
  doc: dict[str, Any] = {"job_id": job["id"], "status": "error", "resume_url": None, "cover_letter_url": None,
                         "error": None, "warnings": [], "cached": False}
  try:
    description: Optional[str] = jobdesc.fetch(job)
    doc["warnings"] = tailor_agent.run(profile, job, GENERATED_DIR / job["id"], description)
    if not description:
      doc["warnings"].append("No job description found; tailored from the title only")
  except (tailor_agent.TailorValidationError, LatexError) as exc:
    doc["error"] = str(exc)
  except Exception as exc:
    tailor_agent.logger.exception("Tailor failed for %s", job["id"])
    doc["error"] = f"Tailor agent failed: {type(exc).__name__}"
  else:
    # Paths relative to /generated; main.py turns them into absolute URLs.
    doc.update(status="ready", resume_url=f"{job['id']}/resume.pdf", cover_letter_url=f"{job['id']}/cover_letter.pdf")
  db.save_document(profile["id"], doc)
  return doc


def tailor_node(state: BullPenState) -> BullPenState:
  known: dict[str, dict[str, Any]] = {j["id"]: j for j in state.get("jobs") or []}
  jobs: list[dict[str, Any]] = [
    j for j in (known.get(i) or scout.find_job(i) for i in state.get("queue") or [])
    if j is not None and j["mode"] == "internship"
  ]
  refresh: bool = bool(state.get("refresh"))
  with ThreadPoolExecutor(max_workers=PREPARE_WORKERS) as pool:  # each job writes only generated/<job_id>/
    docs: list[dict[str, Any]] = list(pool.map(lambda job: _prepare_one(state["profile"], job, refresh), jobs))
  return {"documents": docs}


# ---------- routing ----------

def route_start(state: BullPenState) -> str:
  return {"profile": "profile", "jobs": "load_jobs", "auto": "load_jobs", "prepare": "tailor"}[state["action"]]


def route_after_load(state: BullPenState) -> str:
  if not state["jobs_cached"]:
    return "scout"
  return "select" if state["action"] == "auto" else END


def route_after_match(state: BullPenState) -> str:
  return "select" if state["action"] == "auto" else END


def build_graph() -> Any:
  g: StateGraph = StateGraph(BullPenState)
  g.add_node("profile", profile_node)
  g.add_node("load_jobs", load_jobs_node)
  g.add_node("scout", scout_node)
  g.add_node("match", match_node)
  g.add_node("select", select_node)
  g.add_node("tailor", tailor_node)
  g.add_conditional_edges(START, route_start, ["profile", "load_jobs", "tailor"])
  g.add_edge("profile", END)
  g.add_conditional_edges("load_jobs", route_after_load, ["scout", "select", END])
  g.add_edge("scout", "match")
  g.add_conditional_edges("match", route_after_match, ["select", END])
  g.add_edge("select", "tailor")
  g.add_edge("tailor", END)
  return g.compile()


GRAPH: Any = build_graph()


def run(state: BullPenState) -> BullPenState:
  return GRAPH.invoke(state)
