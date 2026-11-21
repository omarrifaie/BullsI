"""Bus line on Tampa Bay internship cards (agents/office_commute.py), offline: fake Routes API, fixed clock."""
import copy
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

import db
from agents import commute as cm
from agents import office_commute as oc
from conftest import FAKE_ROUTE
from fake_data import FAKE_PROFILE
from test_commute import FixedDatetime

def end_at(lat: float, lng: float) -> dict[str, Any]:
  return {"routes": [{"legs": [{"endLocation": {"latLng": {"latitude": lat, "longitude": lng}}}]}]}


OFFICE: dict[str, Any] = end_at(27.7712349, -82.6398771)
CITY_CENTER: dict[str, Any] = end_at(27.767, -82.640)  # where Google puts a bare "St. Petersburg, FL" (or "Tampa, FL")


def hart_route(short: str = "5", agency: str = "Hillsborough Area Regional Transit") -> dict[str, Any]:
  """FAKE_ROUTE with its Bull Runner ride swapped for another line (a HART bus by default)."""
  route: dict[str, Any] = copy.deepcopy(FAKE_ROUTE)
  step: dict[str, Any] = route["routes"][0]["legs"][0]["steps"][1]["transitDetails"]["transitLine"]
  step.update({"name": f"Route {short}", "nameShort": short, "agencies": [{"name": agency}]})
  return route


class InlinePool:
  """Runs background work immediately, so a test can see what the worker thread would cache."""
  def submit(self, fn: Callable[..., Any], *args: Any) -> None:
    fn(*args)


class RecordingPool:
  """Keeps background work instead of running it: proves /jobs returned without calling Google."""
  def __init__(self) -> None:
    self.jobs: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

  def submit(self, fn: Callable[..., Any], *args: Any) -> None:
    self.jobs.append((fn, args))


def fake_google(body: dict[str, Any]) -> dict[str, Any]:
  """DRIVE = geocode: "<company>, <city>, <state>" -> OFFICE, a bare "<city>, <state>" -> CITY_CENTER."""
  if body["travelMode"] == "DRIVE":
    return CITY_CENTER if body["destination"]["address"].count(",") == 1 else OFFICE
  return hart_route()


def job(job_id: str, company: str, address: str) -> dict[str, Any]:
  return {"id": job_id, "company": company, "address": address}


@pytest.fixture()
def maps(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
  """Temp DB, Mon 2026-11-23 10:00 Eastern, fake Google (geocode -> St. Pete office, transit -> HART 5).
  Returns the request bodies sent to Google."""
  monkeypatch.setenv("BULLPEN_DB", str(tmp_path / "office.db"))
  monkeypatch.setattr(cm, "datetime", FixedDatetime)
  monkeypatch.setattr(oc, "_inflight", set())
  monkeypatch.setattr(oc, "_failed", set())
  calls: list[dict[str, Any]] = []

  def fake_call(body: dict[str, Any], _mask: str) -> dict[str, Any]:
    calls.append(body)
    return fake_google(body)
  monkeypatch.setattr(cm, "_call", fake_call)
  return calls


def no_api(*_args: Any) -> None:
  raise AssertionError("called the Routes API")


@pytest.mark.parametrize("address, expected", [
  ("Tampa, FL", "Tampa, FL"),
  ("Remote in USA; St. Petersburg, FL", "St. Petersburg, FL"),
  ("Boston, MA; Temple Terrace, FL", "Temple Terrace, FL"),
  ("Clearwater, Florida", "Clearwater, Florida"),
  ("Lithia, FL", "Lithia, FL"),
  ("Orlando, FL", None),
  ("Tampa, AZ", None),
  ("Remote in USA", None),
])
def test_tampa_location(address: str, expected: str | None) -> None:
  assert oc.tampa_location({"address": address}) == expected


def test_compute_geocodes_the_office_then_routes_from_the_student(maps: list[dict[str, Any]]) -> None:
  hint: dict[str, Any] | None = oc.compute(job("job_1", "Raymond James", "St. Petersburg, FL"), "4202 E Fowler Ave, Tampa")
  assert hint == {"kind": "bus", "text": "Bus 5 · 25 min · Free with Flamingo Card", "minutes": 25, "approx": True,
                  "origin_label": "Your address"}
  geo, city, transit = maps
  assert geo["travelMode"] == "DRIVE" and geo["destination"] == {"address": "Raymond James, St. Petersburg, FL"}
  assert city["destination"] == {"address": "St. Petersburg, FL"}  # to spot Google's city-center fallback
  assert transit["origin"] == {"address": "4202 E Fowler Ave, Tampa"}
  assert transit["destination"]["location"]["latLng"] == {"latitude": 27.771235, "longitude": -82.639877}
  assert transit["arrivalTime"] == "2026-11-24T14:00:00Z"  # next weekday 09:00 Eastern


def test_summaries() -> None:
  bull_runner: dict[str, Any] | None = cm.parse_route(FAKE_ROUTE)
  assert oc.summarize(bull_runner, cm.CAMPUS)["text"] == "Bull Runner · 25 min · Free with Flamingo Card"
  assert oc.summarize(bull_runner, cm.CAMPUS)["origin_label"] == "USF campus"
  express: dict[str, Any] | None = cm.parse_route(hart_route("20X"))
  assert oc.summarize(express, cm.CAMPUS)["text"] == "Bus 20X · 25 min · $3.00 each way"
  intercity: dict[str, Any] | None = cm.parse_route(hart_route("FLX", agency="FlixBus"))
  assert oc.summarize(intercity, cm.CAMPUS) == {"kind": "no_route", "text": "No bus route", "minutes": None,
                                                 "approx": True, "origin_label": "USF campus"}
  assert oc.summarize(None, cm.CAMPUS)["kind"] == "no_route"
  walk_only: dict[str, Any] = {"minutes": 9, "local_only": True, "steps": [{"mode": "WALK"}], "cost_usd": 0}
  assert oc.summarize(walk_only, cm.CAMPUS)["text"] == "Walk · 9 min"


def test_hints_by_region_and_cache(maps: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(oc, "_pool", InlinePool())
  jobs: list[dict[str, Any]] = [job("job_t", "Citi", "Tampa, FL"), job("job_r", "Stripe", "Remote in USA"),
                                job("job_o", "Lockheed", "Orlando, FL")]
  oc.attach_hints(jobs, FAKE_PROFILE)
  assert jobs[0]["commute_hint"]["kind"] == "pending"  # cache miss: queued, /jobs doesn't wait
  assert jobs[1]["commute_hint"] == {"kind": "remote", "text": "Remote, no commute", "minutes": None,
                                     "approx": False, "origin_label": ""}
  assert jobs[2]["commute_hint"] is None  # elsewhere: nothing
  monkeypatch.setattr(cm, "_call", no_api)
  oc.attach_hints(jobs, FAKE_PROFILE)  # the worker cached it; now served without Google
  assert jobs[0]["commute_hint"]["text"] == "Bus 5 · 25 min · Free with Flamingo Card"
  other_start: dict[str, Any] = {**FAKE_PROFILE, "address": "1 Main St, Clearwater, FL"}
  monkeypatch.setattr(cm, "_call", lambda body, _m: maps.append(body) or fake_google(body))
  oc.attach_hints(jobs, other_start)  # cached per profile start point: a new start is a miss again
  assert jobs[0]["commute_hint"]["kind"] == "pending" and jobs[0]["commute_hint"]["origin_label"] == "Your address"
  oc.attach_hints(jobs, other_start)
  assert jobs[0]["commute_hint"]["text"] == "Bus 5 · 25 min · Free with Flamingo Card"
  assert [b["travelMode"] for b in maps] == ["DRIVE", "DRIVE", "TRANSIT", "TRANSIT"]  # office + city, then 2 routes


def test_office_not_found_shows_nothing_and_is_cached(maps: list[dict[str, Any]],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(oc, "_pool", InlinePool())
  monkeypatch.setattr(cm, "_call", lambda body, _m: maps.append(body) or {})  # no routes at all
  jobs: list[dict[str, Any]] = [job("job_t", "Nowhere LLC", "Tampa, FL")]
  oc.attach_hints(jobs, FAKE_PROFILE)
  monkeypatch.setattr(cm, "_call", no_api)
  oc.attach_hints(jobs, FAKE_PROFILE)
  assert jobs[0]["commute_hint"] is None and len(maps) == 1


def test_city_center_fallback_counts_as_not_found(maps: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
  """Google puts an unknown company at the city center; a bus line there would look real but be wrong."""
  assert oc.geocode("Raymond James", "St. Petersburg, FL") == {"lat": 27.771235, "lng": -82.639877}
  maps.clear()
  monkeypatch.setattr(cm, "_call", lambda body, _m: maps.append(body) or CITY_CENTER)
  assert oc.geocode("Unknown Startup", "St. Petersburg, FL") is None
  assert len(maps) == 1  # the city center itself came from the cache


def test_api_failure_leaves_hint_null_without_retrying(maps: list[dict[str, Any]],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(oc, "_pool", InlinePool())

  def down(*_args: Any) -> None:
    maps.append({})
    raise cm.MapsUnavailable("Routes API returned 429: quota")
  monkeypatch.setattr(cm, "_call", down)
  jobs: list[dict[str, Any]] = [job("job_t", "Citi", "Tampa, FL")]
  oc.attach_hints(jobs, FAKE_PROFILE)
  oc.attach_hints(jobs, FAKE_PROFILE)
  assert jobs[0]["commute_hint"] is None and len(maps) == 1  # not cached, not retried until a restart


def test_cap_per_refresh(maps: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
  pool: RecordingPool = RecordingPool()
  monkeypatch.setattr(oc, "_pool", pool)
  jobs: list[dict[str, Any]] = [job(f"job_{i}", f"Co {i}", "Tampa, FL") for i in range(20)]
  oc.attach_hints(jobs, FAKE_PROFILE)
  assert len(pool.jobs) == oc.MAX_PER_REFRESH == 15 and not maps
  assert all(j["commute_hint"]["kind"] == "pending" for j in jobs[:15])
  assert all(j["commute_hint"] is None for j in jobs[15:])
  oc.attach_hints(jobs, FAKE_PROFILE)
  assert len(pool.jobs) == 15  # still in flight: not queued twice


def test_jobs_endpoint_never_waits_on_google(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
  db.save_profile(FAKE_PROFILE)  # straight into the temp DB, no POST /profile
  pool: RecordingPool = RecordingPool()
  monkeypatch.setattr(oc, "_pool", pool)
  monkeypatch.setattr(oc, "_inflight", set())
  monkeypatch.setattr(oc, "_failed", set())
  monkeypatch.setattr(cm, "_call", no_api)
  first: list[dict[str, Any]] = client.get("/jobs", params={"mode": "internship"}).json()
  by_company: dict[str, dict[str, Any]] = {j["company"]: j for j in first}
  assert by_company["Raymond James"]["commute_hint"]["kind"] == "pending"
  assert by_company["Stripe"]["commute_hint"]["text"] == "Remote, no commute"
  assert by_company["Lockheed"]["commute_hint"] is None
  assert all(j["commute"] is None for j in first)  # the contract's commute (and the match score) are untouched
  assert len(pool.jobs) == 1

  monkeypatch.setattr(cm, "datetime", FixedDatetime)
  monkeypatch.setattr(cm, "_call", lambda body, _m: fake_google(body))
  fn, args = pool.jobs[0]
  fn(*args)  # what the background thread does
  monkeypatch.setattr(cm, "_call", no_api)
  second: list[dict[str, Any]] = client.get("/jobs", params={"mode": "internship"}).json()
  hint: dict[str, Any] = next(j for j in second if j["company"] == "Raymond James")["commute_hint"]
  assert hint["text"] == "Bus 5 · 25 min · Free with Flamingo Card" and hint["approx"] is True
  assert [j["match"] for j in second] == [j["match"] for j in first]
