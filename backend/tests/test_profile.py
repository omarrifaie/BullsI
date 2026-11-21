"""M2: Profile agent post-processing (Gemini mocked)."""
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents import profile as profile_agent
from conftest import fake_extracted

PDF_BYTES: bytes = b"%PDF-1.4\n%fake\n"
PNG_BYTES: bytes = b"\x89PNG\r\n\x1a\nfake"


def test_bullet_ids_are_stable_and_unique() -> None:
  profile: dict[str, Any] = profile_agent.build_profile(fake_extracted())
  ids: list[str] = [b["id"] for e in profile["experience"] + profile["projects"] for b in e["bullets"]]
  assert ids == ["exp1_b1", "exp1_b2", "proj1_b1", "proj1_b2"]
  assert profile_agent.build_profile(fake_extracted()) == profile


def test_signup_overrides_gemini() -> None:
  profile: dict[str, Any] = profile_agent.build_profile(fake_extracted())
  out: dict[str, Any] = profile_agent.apply_signup(profile, {
    "name": "Sam Bull", "work_authorization": "needs_sponsorship", "email": "",
    "year_in_school": "junior", "preferred_cities": "Tampa, FL; Orlando, FL",
    "min_pay": 16.0, "max_commute_minutes": None,
  })
  assert out["name"] == "Sam Bull"
  assert out["work_authorization"] == "needs_sponsorship"
  assert out["email"] == "alexrivera@usf.edu"  # empty form value does not override
  assert out["education"][0]["year_in_school"] == "junior"
  assert out["preferences"]["preferred_cities"] == ["Tampa, FL", "Orlando, FL"]
  assert out["preferences"]["min_pay"] == 16.0
  assert out["country"] == "United States of America"  # derived from "..., Tampa, FL 33620"
  assert out["phone_device_type"] == "" and out["how_heard"] == ""  # never guessed


def test_signup_apply_answers() -> None:
  profile: dict[str, Any] = profile_agent.build_profile(fake_extracted())
  out: dict[str, Any] = profile_agent.apply_signup(profile, {
    "country": "Canada", "phone_device_type": "Mobile", "how_heard": "Career Fair"})
  assert (out["country"], out["phone_device_type"], out["how_heard"]) == ("Canada", "Mobile", "Career Fair")


@pytest.mark.parametrize("address,expected", [
  ("4202 E Fowler Ave, Tampa, FL 33620", "United States of America"), ("Tampa, FL", "United States of America"),
  ("1 Main St, Austin, TX 78701-1234", "United States of America"), ("Toronto, ON M5V 2T6", ""),
  ("Toronto, ON", ""), ("Tampa", ""), ("", "")])
def test_country_only_from_a_us_state(address: str, expected: str) -> None:
  assert profile_agent.us_country_from_address(address) == expected


@pytest.mark.parametrize("graduation,expected", [("Dec 2027", "junior"), ("May 2027", "senior"),
                                                 ("December 2028", "sophomore"), ("May 2030", "freshman"),
                                                 ("", None), ("2028", None)])
def test_year_from_graduation(graduation: str, expected: str | None) -> None:
  assert profile_agent.year_from_graduation(graduation, date(2026, 11, 21)) == expected


@pytest.mark.parametrize("raw,expected", [("9:30", "09:30"), ("09:30", "09:30"), ("3:05 PM", "15:05"),
                                          ("12:00 am", "00:00"), ("12:15 PM", "12:15")])
def test_time_normalization(raw: str, expected: str) -> None:
  assert profile_agent._hhmm(raw) == expected


def test_route_rejects_bad_files(client: TestClient) -> None:
  png: tuple[str, bytes, str] = ("s.png", PNG_BYTES, "image/png")
  assert client.post("/profile", files={"resume": ("r.txt", b"hello", "text/plain"), "schedule": png}).status_code == 400
  assert client.post("/profile", files={"resume": ("r.pdf", PDF_BYTES, "application/pdf"),
                                        "schedule": ("s.gif", b"GIF89a", "image/gif")}).status_code == 400


def test_route_returns_502_when_gemini_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
  def boom(*_args: Any) -> None:
    raise RuntimeError("quota")
  monkeypatch.setattr(profile_agent, "extract", boom)
  res = client.post("/profile", files={"resume": ("r.pdf", PDF_BYTES, "application/pdf"),
                                       "schedule": ("s.png", PNG_BYTES, "image/png")})
  assert res.status_code == 502
