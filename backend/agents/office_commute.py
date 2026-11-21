"""Bus line for Tampa Bay internship cards, e.g. "Bus 5 · 34 min · Free with Flamingo Card".

Approximate: postings only give a city, so the office is geocoded from "<company>, <city>". Reuses teammate B's
commute agent as-is (Routes API call and key, local-agency route choice, fares, home origin, commute_cache table).
/jobs never waits on Google: attach_hints() only reads the cache and hands misses to one background thread.
"""
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Optional

from agents import commute as cm

logger: logging.Logger = logging.getLogger("bullpen.office_commute")

TAMPA_BAY_RE: re.Pattern[str] = re.compile(
  r"\b(tampa|temple terrace|brandon|clearwater|st\.? pete(rsburg)?|saint petersburg|largo|riverview|lutz"
  r"|wesley chapel|plant city|oldsmar|pinellas park|dunedin|seminole|palm harbor|tarpon springs|valrico|seffner"
  r"|lithia|apollo beach|ruskin|land o'? ?lakes|odessa|new port richey|safety harbor),\s*(fl|florida)\b",
  re.IGNORECASE,
)
REMOTE_RE: re.Pattern[str] = re.compile(r"\bremote\b", re.IGNORECASE)
MAX_PER_REFRESH: int = 15  # Tampa Bay cards (in rank order) that get a bus line per /jobs call
ARRIVE_HOUR: int = 9  # estimate a weekday 9:00 arrival
CACHE_VERSION: str = "v2"  # v2: city-center fallbacks count as "office not found"
CITY_CENTER_MILES: float = 0.05  # a company "found" this close to the bare city's geocode is Google's fallback
NO_HINT: dict[str, bool] = {"no_hint": True}  # cached "geocode found nothing": show nothing, don't ask again

_pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="office-commute")
_inflight: set[str] = set()
_failed: set[str] = set()  # API errors this run: show nothing, retry after a backend restart
_lock: threading.Lock = threading.Lock()


def tampa_location(job: dict[str, Any]) -> Optional[str]:
  """The first Tampa Bay location in the posting ("St. Petersburg, FL"), or None."""
  for place in (job.get("address") or "").split(";"):
    if TAMPA_BAY_RE.search(place):
      return place.strip()
  return None


def _hint(kind: str, text: str, origin: Any, minutes: Optional[int] = None) -> dict[str, Any]:
  return {"kind": kind, "text": text, "minutes": minutes, "approx": kind not in ("remote", "pending"),
          "origin_label": cm.origin_label(origin) if origin is not None else ""}


def _locate(address: str) -> Optional[dict[str, float]]:
  """lat/lng the way B's tools/b_setup.geocode does it (a DRIVE route's end point). Cached; None = not found.
  API errors raise, so they are retried on a later refresh instead of being cached."""
  key: str = f"geo|{address}"
  hit: Optional[dict[str, Any]] = cm._cache_get(key)
  if hit is None:
    resp: dict[str, Any] = cm._call(
      {"origin": cm._waypoint(cm.CAMPUS), "destination": cm._waypoint(address), "travelMode": "DRIVE"},
      "routes.legs.endLocation",
    )
    try:
      loc: dict[str, float] = resp["routes"][0]["legs"][0]["endLocation"]["latLng"]
      hit = {"lat": round(loc["latitude"], 6), "lng": round(loc["longitude"], 6)}
    except (KeyError, IndexError):
      hit = NO_HINT
    cm._cache_put(key, hit)
  return None if hit == NO_HINT else hit


def geocode(company: str, place: str) -> Optional[dict[str, float]]:
  """The office, or None when Google can't place the company. An unknown company comes back as the city center
  (e.g. three Tampa companies at the same point), which counts as not found."""
  office: Optional[dict[str, float]] = _locate(f"{company}, {place}")
  if not office:
    return None
  center: Optional[dict[str, float]] = _locate(place)
  if center and cm._haversine_miles(office, center) < CITY_CENTER_MILES:
    return None
  return office


def next_weekday_arrival() -> datetime:
  day: datetime = cm.datetime.now(cm.TZ) + timedelta(days=1)  # cm.datetime so tests can fix B's clock
  while day.weekday() >= 5:
    day += timedelta(days=1)
  return day.replace(hour=ARRIVE_HOUR, minute=0, second=0, microsecond=0)


def _line_label(step: dict[str, Any]) -> str:
  if "bull runner" in step.get("line_name", "").lower():
    return "Bull Runner"
  if step.get("vehicle") == "TRAM":
    return "Streetcar"
  return f"Bus {step['line']}"


def _fare_text(route: dict[str, Any], transit: list[dict[str, Any]]) -> str:
  if route.get("cost_usd") == 0:
    notes: set[str] = {s["fare_note"] for s in transit}
    return "Free with Flamingo Card" if notes <= {cm.FLAMINGO_FREE, "Free with USFCard"} else "Free"
  return f"${route['cost_usd']:.2f} each way" if route.get("cost_usd") else ""


def summarize(route: Optional[dict[str, Any]], origin: Any) -> dict[str, Any]:
  """One card line from B's parsed route. Intercity buses (not local_only) count as no route."""
  if not route or not route.get("local_only"):
    return _hint("no_route", "No bus route", origin)
  transit: list[dict[str, Any]] = [s for s in route["steps"] if s["mode"] == "TRANSIT"]
  if not transit:
    return _hint("walk", f"Walk · {route['minutes']} min", origin, route["minutes"])
  lines: str = " → ".join(dict.fromkeys(_line_label(s) for s in transit))
  parts: list[str] = [lines, f"{route['minutes']} min", _fare_text(route, transit)]
  return _hint("bus", " · ".join(p for p in parts if p), origin, route["minutes"])


def compute(job: dict[str, Any], origin: Any) -> Optional[dict[str, Any]]:
  """Geocode the office, then B's transit route from the student's start point. None = office not found."""
  place: Optional[str] = tampa_location(job)
  office: Optional[dict[str, float]] = geocode(job["company"], place) if place else None
  if not office:
    return None
  return summarize(cm.fetch_transit(origin, office, arrive_by=next_weekday_arrival()), origin)


def _key(job: dict[str, Any], origin: Any) -> str:
  return f"office|{CACHE_VERSION}|{job['id']}|{origin}"  # origin comes from the profile: per job and profile


def _fill(job: dict[str, Any], origin: Any) -> None:
  key: str = _key(job, origin)
  try:
    cm._cache_put(key, compute(job, origin) or NO_HINT)
  except Exception as exc:  # no key, quota, API down: not cached, so a restart retries it
    logger.warning("Office commute failed for %s: %s", job["id"], str(exc)[:200])
    with _lock:
      _failed.add(key)
  finally:
    with _lock:
      _inflight.discard(key)


def _cached_or_queued(job: dict[str, Any], origin: Any) -> Optional[dict[str, Any]]:
  key: str = _key(job, origin)
  hit: Optional[dict[str, Any]] = cm._cache_get(key)
  if hit is not None:
    return None if hit == NO_HINT else hit
  with _lock:
    if key in _failed:
      return None
    queue: bool = key not in _inflight
    _inflight.add(key)
  if queue:  # submit outside the lock: _fill takes it too
    _pool.submit(_fill, dict(job), origin)
  return _hint("pending", "", origin)


def attach_hints(jobs: list[dict[str, Any]], profile: Optional[dict[str, Any]]) -> None:
  """Set each internship's commute_hint in place. Tampa Bay (top MAX_PER_REFRESH): bus line from the cache, or
  "pending" while the background thread fetches it. Remote: "Remote, no commute". Elsewhere or any error: None."""
  try:
    origin: Any = cm.home_origin(profile)
  except Exception as exc:
    logger.warning("Office commute origin failed: %s", type(exc).__name__)
    return
  budget: int = MAX_PER_REFRESH
  for job in jobs:
    job["commute_hint"] = None
    try:
      if tampa_location(job):
        if budget > 0:
          budget -= 1
          job["commute_hint"] = _cached_or_queued(job, origin)
      elif REMOTE_RE.search(job.get("address") or ""):
        job["commute_hint"] = _hint("remote", "Remote, no commute", None)
    except Exception as exc:
      logger.warning("Office commute hint failed for %s: %s", job.get("id"), type(exc).__name__)
