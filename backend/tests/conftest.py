import json
import sys
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # for TECTONIC_PATH; Gemini is always mocked in tests

from agents import commute, jobdesc, matcher, scout  # noqa: E402
from agents import profile as profile_agent  # noqa: E402
from agents import tailor as tailor_agent  # noqa: E402
from fake_data import FAKE_PROFILE  # noqa: E402

NOW: int = 1795300000  # 2026-11-22


def raw_listing(uid: str, title: str, company: str, locations: list[str], days_old: int = 1,
                sponsorship: str = "Other", active: bool = True, category: str = "Software",
                degrees: list[str] | None = None, terms: list[str] | None = None) -> dict[str, Any]:
  """A row shaped like SimplifyJobs listings.json."""
  return {
    "source": "Simplify", "category": category, "company_name": company, "id": uid, "title": title,
    "active": active, "terms": terms or ["Summer 2027"], "date_updated": NOW, "date_posted": NOW - days_old * 86400,
    "url": f"https://example.com/apply/{uid}", "locations": locations, "company_url": "", "is_visible": True,
    "sponsorship": sponsorship, "degrees": degrees or ["Bachelor's"],
  }


RAW_LISTINGS: list[dict[str, Any]] = [
  raw_listing("aaaaaaaa-0000-0000-0000-000000000001", "Data Engineering Intern", "Raymond James", ["St. Petersburg, FL"]),
  raw_listing("bbbbbbbb-0000-0000-0000-000000000002", "Software Engineer Intern", "Stripe", ["Remote in USA"], days_old=40),
  raw_listing("cccccccc-0000-0000-0000-000000000003", "Software Engineer Intern", "Lockheed", ["Orlando, FL"],
              sponsorship="U.S. Citizenship is Required"),
  raw_listing("dddddddd-0000-0000-0000-000000000004", "Hardware Intern", "Intel", ["Austin, TX"], category="Hardware"),
  raw_listing("eeeeeeee-0000-0000-0000-000000000005", "Backend Intern", "Closed Co", ["Tampa, FL"], active=False),
]


def fake_extracted() -> profile_agent.ExtractedProfile:
  """What Gemini would return for FAKE_PROFILE (bullets as plain strings, no ids)."""
  p: dict[str, Any] = FAKE_PROFILE
  return profile_agent.ExtractedProfile(
    name=p["name"], email=p["email"], phone=p["phone"], address=p["address"],
    work_authorization=p["work_authorization"], education=p["education"],
    experience=[{**e, "bullets": [b["text"] for b in e["bullets"]]} for e in p["experience"]],
    projects=[{**pr, "bullets": [b["text"] for b in pr["bullets"]]} for pr in p["projects"]],
    skills=p["skills"], class_schedule=p["class_schedule"],
    preferences={"roles": p["preferences"]["roles"], "preferred_cities": []},
  )


def fake_tailor_output() -> tailor_agent.TailorOutput:
  return tailor_agent.TailorOutput(
    bullets=[{"id": "exp1_b2", "text": "Wrote a Python script that auto-tags tickets, cutting triage time by 30%"},
             {"id": "proj1_b1", "text": "Built a live campus shuttle map used by 300+ students"}],
    featured_skills=["Python", "SQL", "Kubernetes"],
    cover_letter_paragraphs=["I am applying for this role & excited.", "At USF IT I cut triage time by 30%.",
                             "I would bring Python and SQL skills. Thank you."],
  )


def _stub_build(_profile: dict[str, Any], _job: dict[str, Any], _out: Any, out_dir: Path) -> tuple[Path, Path]:
  out_dir.mkdir(parents=True, exist_ok=True)
  for name in ("resume.pdf", "cover_letter.pdf"):
    (out_dir / name).write_bytes(b"%PDF-1.4\n%stub\n")
  return out_dir / "resume.pdf", out_dir / "cover_letter.pdf"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
  """App with a temp DB, no network (Scout falls back to a temp cache, no Maps key), and Gemini mocked out."""
  monkeypatch.setenv("BULLPEN_DB", str(tmp_path / "test.db"))
  monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)  # commute agent raises MapsUnavailable unless faked
  monkeypatch.setattr(profile_agent, "extract", lambda *_args: fake_extracted())
  monkeypatch.setattr(matcher, "write_reasons", lambda *_args: {})
  monkeypatch.setattr(tailor_agent, "ask_gemini", lambda *_args: fake_tailor_output())
  monkeypatch.setattr(tailor_agent, "build_documents", _stub_build)
  monkeypatch.setattr(jobdesc, "fetch", lambda _job: None)
  monkeypatch.setattr(jobdesc, "prefetch", lambda _job: None)
  cache: Path = tmp_path / "listings_cache.json"
  cache.write_text(json.dumps(RAW_LISTINGS), encoding="utf-8")
  monkeypatch.setattr(scout, "LISTINGS_CACHE", cache)
  monkeypatch.setattr(scout, "LISTINGS_SEED", tmp_path / "listings_seed.json")
  monkeypatch.setattr(scout, "PART_TIME_FILE", tmp_path / "part_time_jobs.json")

  def offline(*_args: Any, **_kwargs: Any) -> None:
    raise httpx.ConnectError("offline in tests")
  monkeypatch.setattr(scout.httpx, "get", offline)
  from main import app
  with TestClient(app) as c:
    yield c


# A Routes API transit response: 4 min walk, then a 15 min Bull Runner ride (Tue 2026-11-24 14:22 Eastern).
FAKE_ROUTE: dict[str, Any] = {"routes": [{"duration": "1500s", "distanceMeters": 9000, "legs": [{"steps": [
  {"travelMode": "WALK", "staticDuration": "240s", "distanceMeters": 300,
   "navigationInstruction": {"instructions": "Walk to Marshall Student Center"},
   "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"}},
  {"travelMode": "TRANSIT", "staticDuration": "900s", "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"},
   "transitDetails": {
    "headsign": "UATC", "stopCount": 4, "transitLine": {"name": "Bull Runner", "nameShort": "BR", "color": "#006747"},
    "stopDetails": {"departureStop": {"name": "Marshall Student Center"}, "arrivalStop": {"name": "UATC"},
                    "departureTime": "2026-11-24T19:22:00Z", "arrivalTime": "2026-11-24T19:37:00Z"}}},
]}]}]}


@pytest.fixture()
def fake_routes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
  """Teammate B's commute agent without Google: canned transit route, 12 km drive. Returns the request bodies."""
  calls: list[dict[str, Any]] = []

  def fake_call(body: dict[str, Any], _mask: str) -> dict[str, Any]:
    calls.append(body)
    return {"routes": [{"distanceMeters": 12000}]} if body["travelMode"] == "DRIVE" else FAKE_ROUTE
  monkeypatch.setattr(commute, "_call", fake_call)
  return calls
