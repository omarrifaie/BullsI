import json
import sys
from pathlib import Path
from typing import Any, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import matcher, scout  # noqa: E402
from agents import profile as profile_agent  # noqa: E402
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


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
  """App with a temp DB, no network (Scout falls back to a temp cache), and Gemini mocked out."""
  monkeypatch.setenv("BULLPEN_DB", str(tmp_path / "test.db"))
  monkeypatch.setattr(profile_agent, "extract", lambda *_args: fake_extracted())
  monkeypatch.setattr(matcher, "write_reasons", lambda *_args: {})
  cache: Path = tmp_path / "listings_cache.json"
  cache.write_text(json.dumps(RAW_LISTINGS), encoding="utf-8")
  monkeypatch.setattr(scout, "LISTINGS_CACHE", cache)
  monkeypatch.setattr(scout, "PART_TIME_FILE", tmp_path / "part_time_jobs.json")

  def offline(*_args: Any, **_kwargs: Any) -> None:
    raise httpx.ConnectError("offline in tests")
  monkeypatch.setattr(scout.httpx, "get", offline)
  from main import app
  with TestClient(app) as c:
    yield c
