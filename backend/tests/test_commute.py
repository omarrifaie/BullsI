"""Teammate B's commute agent and routes, offline: fake Routes API, fixed clock (Mon 2026-11-23 10:00 Eastern)."""
from datetime import datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest
from fastapi.testclient import TestClient
from google.genai import errors as genai_errors

import db
from agents import commute as cm
from routes_b import build_ics
from test_m1_routes import _post_profile

FIXED_NOW: datetime = datetime(2026, 11, 23, 10, 0, tzinfo=cm.TZ)
JOB: dict[str, Any] = {"id": "job_1", "address": "1 Main St, Tampa", "lat": 28.07, "lng": -82.41,
                       "shifts": [{"day": "Tue", "start": "15:00", "end": "21:00"},
                                  {"day": "Thu", "start": "15:00", "end": "21:00"}]}
MYJOB: dict[str, Any] = {"employer": "Bulls Brew Cafe", "address": "5010 E Fowler Ave, Tampa, FL 33617",
                         "shifts": [{"day": "Tue", "start": "15:00", "end": "21:00"}]}


class FixedDatetime(datetime):
  @classmethod
  def now(cls, tz: Optional[tzinfo] = None) -> datetime:
    return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture()
def fixed_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(cm, "datetime", FixedDatetime)
  monkeypatch.setenv("BULLPEN_DB", str(tmp_path / "commute.db"))


def test_commute_for_job(fixed_clock: None, fake_routes: list[dict[str, Any]]) -> None:
  out: dict[str, Any] = cm.commute_for_job(JOB)
  assert out["minutes"] == 25 and out["car_free"] and out["transfers"] == 0
  assert out["cost_usd"] == 0.0, "Bull Runner should be fare-free"
  assert abs(out["co2_saved_kg_week"] - 11.9) < 0.2  # 12000 m = 7.46 mi * 0.4 kg * 4 trips
  assert out["arrive_by"] == "14:50"  # Tue 15:00 shift minus 10 min
  assert out["steps"][1]["depart"] == "14:22" and out["leave_by"] == "14:18"  # 14:22 minus the 4 min walk
  for key in ("mode", "line", "from_stop", "to_stop", "depart", "arrive", "polyline"):
    assert all(key in s for s in out["steps"]), key
  transit_request: dict[str, Any] = next(b for b in fake_routes if b["travelMode"] == "TRANSIT")
  assert transit_request["arrivalTime"] == "2026-11-24T19:50:00Z"  # next Tuesday from the fixed clock
  assert transit_request["computeAlternativeRoutes"] is True
  assert out["origin_label"] == "USF campus"  # no origin given


def test_second_call_is_served_from_cache(fixed_clock: None, fake_routes: list[dict[str, Any]],
                                          monkeypatch: pytest.MonkeyPatch) -> None:

  def cache_miss(*_args: Any) -> None:
    raise AssertionError("cache miss: called the Routes API")
  first: dict[str, Any] = cm.commute_for_job(JOB)
  monkeypatch.setattr(cm, "_call", cache_miss)
  second: dict[str, Any] = cm.commute_for_job(JOB)  # transit route AND driving distance come from the cache
  assert second["minutes"] == 25 and second["co2_saved_kg_week"] == first["co2_saved_kg_week"] == 11.9


def _transit_route(minutes: int, line: str, agency: str) -> dict[str, Any]:
  return {"duration": f"{minutes * 60}s", "legs": [{"steps": [{"travelMode": "TRANSIT", "staticDuration": f"{minutes * 60}s",
          "transitDetails": {"transitLine": {"name": line, "nameShort": line, "agencies": [{"name": agency}]},
                             "stopDetails": {}}}]}]}


FLIXBUS: dict[str, Any] = _transit_route(30, "FlixBus", "FlixBus")
HART_5: dict[str, Any] = _transit_route(40, "5", "Hillsborough Area Regional Transit")


def test_picks_first_local_alternative(fixed_clock: None, monkeypatch: pytest.MonkeyPatch) -> None:
  """Google ranks an intercity FlixBus first; the agent skips it for the first HART-only route."""
  monkeypatch.setattr(cm, "_call", lambda body, _mask: (
    {"routes": [{"distanceMeters": 12000}]} if body["travelMode"] == "DRIVE" else {"routes": [FLIXBUS, HART_5]}))
  out: dict[str, Any] = cm.commute_for_job(JOB)
  assert out["minutes"] == 40 and out["car_free"] and out["steps"][0]["line"] == "5"


def test_no_local_alternative_keeps_best_but_not_car_free(fixed_clock: None, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(cm, "_call", lambda body, _mask: {"routes": [FLIXBUS]})
  out: dict[str, Any] = cm.commute_for_job(JOB)
  assert out["minutes"] == 30 and not out["car_free"] and out["co2_saved_kg_week"] == 0.0


def test_no_route_is_cached(fixed_clock: None, monkeypatch: pytest.MonkeyPatch) -> None:
  calls: list[str] = []

  def no_routes(body: dict[str, Any], _mask: str) -> dict[str, Any]:
    calls.append(body["travelMode"])
    return {}
  monkeypatch.setattr(cm, "_call", no_routes)
  assert cm.commute_for_job(JOB)["minutes"] is None
  assert cm.commute_for_job(JOB)["minutes"] is None
  assert calls == ["TRANSIT"]


def test_home_origin_needs_a_street_address() -> None:
  assert cm.home_origin({"address": "Tampa, FL"}) == cm.CAMPUS  # city only would geocode downtown
  assert cm.home_origin({"address": ""}) == cm.CAMPUS and cm.home_origin(None) == cm.CAMPUS
  assert cm.home_origin({"address": "4202 E Fowler Ave, Tampa, FL 33620"}) == "4202 E Fowler Ave, Tampa, FL 33620"
  assert cm.home_origin({"address": "Tampa, FL"}, {"home_address": "12 Elm St, Tampa"}) == "12 Elm St, Tampa"
  assert cm.origin_label(cm.CAMPUS) == "USF campus" and cm.origin_label("12 Elm St, Tampa") == "Your address"


def test_next_shift_start(fixed_clock: None) -> None:
  assert cm.next_shift_start("Tue", "15:00") == datetime(2026, 11, 24, 15, 0, tzinfo=cm.TZ)
  assert cm.next_shift_start("Mon", "09:00") == datetime(2026, 11, 30, 9, 0, tzinfo=cm.TZ)  # already started today


def test_build_ics_escapes_text() -> None:
  begin: datetime = datetime(2026, 11, 24, 14, 18, tzinfo=cm.TZ)
  ics: str = build_ics([{"name": "Leave for Cafe, Inc.", "begin": begin, "end": begin + timedelta(minutes=25),
                         "location": "1 Main St, Tampa", "description": "line one\nline two"}])
  assert "BEGIN:VEVENT" in ics and "DTSTART:20261124T191800Z" in ics
  assert "SUMMARY:Leave for Cafe\\, Inc." in ics and "DESCRIPTION:line one\\nline two" in ics


def test_db_path_matches_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  """Commute cache and My Job share db.py's absolute bullpen.db, whatever folder uvicorn starts from."""
  monkeypatch.delenv("BULLPEN_DB", raising=False)
  monkeypatch.setattr(db, "DEFAULT_DB", tmp_path / "bullpen.db")
  elsewhere: Path = tmp_path / "elsewhere"
  elsewhere.mkdir()
  monkeypatch.chdir(elsewhere)
  conn = cm._db()
  try:
    assert Path(conn.execute("PRAGMA database_list").fetchone()[2]) == tmp_path / "bullpen.db"
  finally:
    conn.close()


def test_routes_api_errors_become_maps_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
  with pytest.raises(cm.MapsUnavailable, match="GOOGLE_MAPS_API_KEY is not set"):
    cm._call({}, "routes.duration")
  monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "secret-test-key")
  denied: httpx.Response = httpx.Response(403, text="API key not valid", request=httpx.Request("POST", cm.ROUTES_URL))
  monkeypatch.setattr(cm.httpx, "post", lambda *_args, **_kwargs: denied)
  with pytest.raises(cm.MapsUnavailable, match="403") as info:
    cm._call({}, "routes.duration")
  assert "secret-test-key" not in str(info.value)


# ---------- /jobs attaches commutes ----------

def test_parttime_jobs_carry_commutes(client: TestClient, fake_routes: list[dict[str, Any]]) -> None:
  profile: dict[str, Any] = _post_profile(client)
  jobs: list[dict[str, Any]] = client.get("/jobs?mode=parttime").json()
  assert jobs and all(j["commute"]["minutes"] == 25 and j["commute"]["car_free"] for j in jobs)
  assert all(j["commute"]["origin_label"] == "Your address" for j in jobs)
  assert all(j["match"]["reason"].endswith("25 min") for j in jobs)  # the Matcher scored real minutes
  assert all(b["origin"] == {"address": profile["address"]} for b in fake_routes)


def test_parttime_jobs_survive_missing_maps_key(client: TestClient) -> None:
  _post_profile(client)  # conftest removes GOOGLE_MAPS_API_KEY
  res = client.get("/jobs?mode=parttime")
  assert res.status_code == 200 and res.json()
  assert all(j["commute"] is None and "km from USF" in j["match"]["reason"] for j in res.json())


# ---------- 503s instead of 500s ----------

def test_myjob_routes_503_without_maps_key(client: TestClient) -> None:
  client.post("/myjob", json=MYJOB)
  for path in ("/myjob/today", "/myjob/calendar.ics"):
    res = client.get(path)
    assert res.status_code == 503 and "GOOGLE_MAPS_API_KEY is not set" in res.json()["detail"], path


def test_chat_503_without_gemini_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.delenv("GEMINI_API_KEY", raising=False)
  res = client.post("/chat", json={"message": "I missed the bus"})
  assert res.status_code == 503 and "GEMINI_API_KEY is not set" in res.json()["detail"]


def test_chat_503_when_gemini_fails(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("GEMINI_API_KEY", "test-key")

  def gemini_down(*_args: Any) -> str:
    raise genai_errors.APIError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
  monkeypatch.setattr(cm, "answer_missed_bus", gemini_down)
  res = client.post("/chat", json={"message": "I missed the bus"})
  assert res.status_code == 503 and "Gemini request failed" in res.json()["detail"]


# ---------- fares (USF Flamingo Card), CO2 source, merged walking steps ----------

@pytest.mark.parametrize("name,short,agency,vehicle,fare,note", [
  ("40th Street", "5", "Hillsborough Area Regional Transit", "BUS", 0.0, "Free with USF Flamingo Card"),
  ("New Tampa Limited Express", "275", "Hillsborough Area Regional Transit", "BUS", 0.0, "Free with USF Flamingo Card"),
  ("Airport", "60LX", "Hillsborough Area Regional Transit", "BUS", 0.0, "Free with USF Flamingo Card"),
  ("Brandon Express", "20X", "Hillsborough Area Regional Transit", "BUS", 3.0,
   "HART Express fare (not covered by the Flamingo Card)"),
  ("TECO Line Streetcar", "", "Hillsborough Area Regional Transit", "TRAM", 0.0, "TECO streetcar, free for everyone"),
  ("Bull Runner C", "C", "University of South Florida", "BUS", 0.0, "Free with USFCard"),
  ("FlixBus", "FlixBus", "FlixBus", "BUS", None, "Fare not known"),
])
def test_student_fares(name: str, short: str, agency: str, vehicle: str, fare: Optional[float], note: str) -> None:
  assert cm._fare(name, short, agency, vehicle) == (fare, note)


def test_route_cost_note_and_unknown_fares(fixed_clock: None, monkeypatch: pytest.MonkeyPatch) -> None:
  express: dict[str, Any] = _transit_route(30, "20X", "Hillsborough Area Regional Transit")
  monkeypatch.setattr(cm, "_call", lambda body, _mask: (
    {"routes": [{"distanceMeters": 12000}]} if body["travelMode"] == "DRIVE" else {"routes": [express]}))
  out: dict[str, Any] = cm.commute_for_job(JOB)
  assert out["cost_usd"] == 3.0 and out["cost_note"] == "HART Express fare (not covered by the Flamingo Card)"
  assert cm.parse_route({"routes": [FLIXBUS]})["cost_usd"] is None
  assert cm.parse_route({"routes": [{"duration": "600s", "legs": [{"steps": [
    {"travelMode": "WALK", "staticDuration": "600s"}]}]}]})["cost_note"] == "Walking only, no fare"


def test_commute_carries_co2_source(fixed_clock: None, fake_routes: list[dict[str, Any]]) -> None:
  out: dict[str, Any] = cm.commute_for_job(JOB)
  assert out["co2_source"]["url"].startswith("https://www.epa.gov/") and "400 g" in out["co2_source"]["label"]
  assert out["cost_note"] == "Free with USFCard"


def test_describe_steps_merges_walking() -> None:
  walk: dict[str, Any] = {"mode": "WALK", "minutes": 2}
  bus: dict[str, Any] = {"mode": "TRANSIT", "depart": "08:28", "arrive": "08:34", "instruction": "Take 48 toward Netpark",
                         "from_stop": "Holly Dr", "to_stop": "Fowler Av @ 51st St"}
  assert cm.describe_steps([walk, walk, bus, walk, walk, walk]) == [
    "Walk 4 min", "08:28 Take 48 toward Netpark (Holly Dr to Fowler Av @ 51st St), arrive 08:34", "Walk 6 min"]
  assert cm.describe_steps([bus, {"mode": "WALK", "minutes": 0}, bus])[1] == "Walk under 1 min"


def test_calendar_description_merges_walking(client: TestClient, fake_routes: list[dict[str, Any]]) -> None:
  client.post("/myjob", json=MYJOB)
  ics: str = client.get("/myjob/calendar.ics").text
  assert "DESCRIPTION:Walk 4 min\\n" in ics and "Walk to Marshall Student Center" not in ics
