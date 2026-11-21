"""Commute agent (Person B).

Everything numeric lives in plain Python: Gemini is only used for the
missed-bus chat, where it calls get_transit_route() as a tool.

Public API other people call:
    commute_for_job(job, origin=None)   -> contract "commute" dict (Person A's /jobs)
    shift_route(job, shift, origin)     -> (route, arrive_by)         (My Job)
    leave_by_time(route, arrive_by)     -> aware datetime              (My Job)
    answer_missed_bus(message, ctx)     -> str                         (POST /chat)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

import db
import gemini

TZ = ZoneInfo("America/New_York")
CAMPUS = {"lat": 28.0587, "lng": -82.4139}  # USF Tampa; adjust if you start elsewhere
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

CAR_FREE_MAX_MIN = int(os.getenv("CAR_FREE_MAX_MIN", "45"))  # badge threshold
ARRIVE_EARLY_MIN = 10  # arrive this long before a shift starts
# EPA: a typical passenger vehicle emits about 400 g CO2 per mile (cite on the slide).
EPA_KG_CO2_PER_MILE = 0.400
HART_FARE = float(os.getenv("HART_FARE", "2.00"))  # VERIFY the current HART fare before demo

DAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

# Field mask keeps responses small and billing in the cheaper SKU.
TRANSIT_MASK = ",".join([
    "routes.duration",
    "routes.distanceMeters",
    "routes.legs.steps.travelMode",
    "routes.legs.steps.staticDuration",
    "routes.legs.steps.distanceMeters",
    "routes.legs.steps.polyline.encodedPolyline",
    "routes.legs.steps.navigationInstruction.instructions",
    "routes.legs.steps.transitDetails",
])


# ---------- time helpers ----------
def next_shift_start(day: str, hhmm: str, after: datetime | None = None) -> datetime:
    after = after or datetime.now(TZ)
    h, m = map(int, hhmm.split(":"))
    d = after + timedelta(days=(DAYS[day] - after.weekday()) % 7)
    start = d.replace(hour=h, minute=m, second=0, microsecond=0)
    if start <= after:
        start += timedelta(days=7)
    return start


def _utc_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def _hhmm(iso: str | None) -> str:
    return _parse_iso(iso).astimezone(TZ).strftime("%H:%M") if iso else ""


def _secs(v) -> int:
    return int(float(str(v).rstrip("s"))) if v else 0


# ---------- Routes API ----------
class MapsUnavailable(RuntimeError):
    """No GOOGLE_MAPS_API_KEY, or the Routes API call failed. Routes turn this into a 503."""


def _waypoint(p):
    if isinstance(p, str):
        return {"address": p}
    return {"location": {"latLng": {"latitude": p["lat"], "longitude": p["lng"]}}}


def _call(body: dict, mask: str) -> dict:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise MapsUnavailable("GOOGLE_MAPS_API_KEY is not set in the repo-root .env")
    try:
        r = httpx.post(
            ROUTES_URL,
            json=body,
            timeout=20,
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": mask},
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:  # message has the status and Google's reason, never the key
        raise MapsUnavailable(f"Routes API returned {e.response.status_code}: {e.response.text[:200]}") from e
    except httpx.HTTPError as e:
        raise MapsUnavailable(f"Routes API unreachable: {type(e).__name__}") from e
    return r.json()


def _parse_step(s: dict) -> dict:
    poly = (s.get("polyline") or {}).get("encodedPolyline", "")
    t = s.get("transitDetails")
    base = {"minutes": round(_secs(s.get("staticDuration")) / 60), "polyline": poly}
    if t:
        sd, line = t.get("stopDetails", {}), t.get("transitLine", {})
        name = line.get("name", "")
        short = line.get("nameShort") or name
        free = "bull runner" in name.lower()
        return {
            **base,
            "mode": "TRANSIT",
            "line": short,
            "line_name": name,
            "color": line.get("color", "#006747"),
            "headsign": t.get("headsign", ""),
            "from_stop": sd.get("departureStop", {}).get("name", ""),
            "to_stop": sd.get("arrivalStop", {}).get("name", ""),
            "depart": _hhmm(sd.get("departureTime")),
            "arrive": _hhmm(sd.get("arrivalTime")),
            "depart_iso": sd.get("departureTime"),
            "arrive_iso": sd.get("arrivalTime"),
            "stops": t.get("stopCount", 0),
            "fare_usd": 0.0 if free else HART_FARE,
            "instruction": f"Take {short} toward {t.get('headsign', 'end of line')}",
        }
    instr = (s.get("navigationInstruction") or {}).get("instructions") or "Walk"
    return {
        **base,
        "mode": s.get("travelMode", "WALK"),
        "line": "", "from_stop": "", "to_stop": "", "depart": "", "arrive": "",
        "meters": s.get("distanceMeters", 0),
        "instruction": instr,
    }


def parse_route(resp: dict) -> dict | None:
    routes = resp.get("routes") or []
    if not routes:
        return None
    r = routes[0]
    steps = [_parse_step(s) for leg in r.get("legs", []) for s in leg.get("steps", [])]
    transit = [s for s in steps if s["mode"] == "TRANSIT"]
    return {
        "minutes": round(_secs(r.get("duration")) / 60),
        "transfers": max(len(transit) - 1, 0),
        "has_transit": bool(transit),
        "cost_usd": round(sum(s["fare_usd"] for s in transit), 2),
        "steps": steps,
    }


def fetch_transit(origin, dest, *, arrive_by: datetime | None = None,
                  depart_at: datetime | None = None) -> dict | None:
    body = {
        "origin": _waypoint(origin),
        "destination": _waypoint(dest),
        "travelMode": "TRANSIT",
        "languageCode": "en-US",
        "units": "IMPERIAL",
    }
    if arrive_by:
        body["arrivalTime"] = _utc_z(arrive_by)
    elif depart_at:
        body["departureTime"] = _utc_z(depart_at)
    return parse_route(_call(body, TRANSIT_MASK))


def _haversine_miles(a: dict, b: dict) -> float:
    r = 3958.8
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def driving_miles(origin, dest) -> float:
    try:
        resp = _call(
            {"origin": _waypoint(origin), "destination": _waypoint(dest), "travelMode": "DRIVE"},
            "routes.distanceMeters",
        )
        return resp["routes"][0]["distanceMeters"] / 1609.344
    except Exception:
        if isinstance(origin, dict) and isinstance(dest, dict):
            return _haversine_miles(origin, dest) * 1.3  # rough road factor
        return 0.0


# ---------- cache (the demo must never wait on the API) ----------
def _db() -> sqlite3.Connection:
    conn = db.connect()  # same absolute bullpen.db (or BULLPEN_DB) as the rest of the backend
    conn.execute("CREATE TABLE IF NOT EXISTS commute_cache(key TEXT PRIMARY KEY, payload TEXT, created REAL)")
    return conn


def _cache_get(key: str):
    with _db() as c:
        row = c.execute("SELECT payload FROM commute_cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _cache_put(key: str, payload: dict) -> None:
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO commute_cache VALUES (?,?,?)", (key, json.dumps(payload), time.time()))


# ---------- the agent ----------
def home_origin(profile: dict | None, job: dict | None = None):
    """Where commutes start: My Job's home_address, else the student's profile address, else campus."""
    if job and job.get("home_address"):
        return job["home_address"]
    return (profile or {}).get("address") or CAMPUS


def _dest(job: dict):
    return {"lat": job["lat"], "lng": job["lng"]} if job.get("lat") is not None else job["address"]


def shift_route(job: dict, shift: dict, origin=None, use_cache: bool = True):
    """Transit route that arrives ARRIVE_EARLY_MIN before the shift. Returns (route|None, arrive_by)."""
    origin = origin or CAMPUS
    arrive_by = next_shift_start(shift["day"], shift["start"]) - timedelta(minutes=ARRIVE_EARLY_MIN)
    key = f"{job.get('id', job['address'])}|{origin}|{shift['day']}{shift['start']}"
    route = _cache_get(key) if use_cache else None
    if route is None:
        route = fetch_transit(origin, _dest(job), arrive_by=arrive_by)
        if route:
            _cache_put(key, route)
    return route, arrive_by


def leave_by_time(route: dict, arrive_by: datetime) -> datetime:
    steps = route["steps"]
    i = next((n for n, s in enumerate(steps) if s["mode"] == "TRANSIT" and s.get("depart_iso")), None)
    if i is None:
        return arrive_by - timedelta(minutes=route["minutes"])
    walk_first = sum(s["minutes"] for s in steps[:i])
    return _parse_iso(steps[i]["depart_iso"]) - timedelta(minutes=walk_first)


def commute_for_job(job: dict, origin=None, use_cache: bool = True) -> dict:
    """Fill the contract's `commute` object for one part-time job."""
    origin = origin or CAMPUS
    shifts = job.get("shifts") or []
    empty = {"minutes": None, "car_free": False, "transfers": 0, "co2_saved_kg_week": 0,
             "cost_usd": None, "steps": []}
    if not shifts:
        return empty
    try:
        route, arrive_by = shift_route(job, shifts[0], origin, use_cache)
    except Exception as e:  # API down, bad key, quota
        return {**empty, "error": str(e)[:200]}
    if not route:
        return empty
    car_free = route["has_transit"] and route["minutes"] <= CAR_FREE_MAX_MIN
    co2 = 0.0
    if car_free:
        trips_per_week = len(shifts) * 2  # there and back
        co2 = round(driving_miles(origin, _dest(job)) * EPA_KG_CO2_PER_MILE * trips_per_week, 1)
    leave = leave_by_time(route, arrive_by)
    return {
        "minutes": route["minutes"],
        "car_free": car_free,
        "transfers": route["transfers"],
        "co2_saved_kg_week": co2,
        "cost_usd": route["cost_usd"],
        "next_shift": shifts[0],
        "arrive_by": arrive_by.astimezone(TZ).strftime("%H:%M"),
        "leave_by": leave.astimezone(TZ).strftime("%H:%M"),
        "steps": route["steps"],
    }


def warm_cache(jobs: list[dict], origin=None) -> None:
    """Run once before the demo so no card waits on the API."""
    for j in jobs:
        commute_for_job(j, origin)


# ---------- missed-bus chat (Gemini function calling) ----------
def get_transit_route(origin: str, destination: str, depart_after: str) -> dict:
    """Find the next public-transit option between two places in the Tampa area.

    Args:
        origin: Street address or place name to start from, e.g. "USF Marshall Student Center, Tampa".
        destination: Street address or place name to arrive at.
        depart_after: Earliest departure time as ISO 8601 local time, e.g. "2026-11-24T14:30:00".

    Returns:
        A short summary with total minutes and each step, or an error message.
    """
    try:
        dep = datetime.fromisoformat(depart_after)
        dep = dep if dep.tzinfo else dep.replace(tzinfo=TZ)
        route = fetch_transit(origin, destination, depart_at=dep)
    except Exception as e:
        return {"error": f"Route lookup failed: {str(e)[:120]}"}
    if not route:
        return {"error": "No transit route found for that time."}
    return {
        "minutes": route["minutes"],
        "cost_usd": route["cost_usd"],
        "steps": [
            {"mode": s["mode"], "line": s["line"], "from": s["from_stop"], "to": s["to_stop"],
             "depart": s["depart"], "arrive": s["arrive"], "text": s["instruction"]}
            for s in route["steps"]
        ],
    }


def answer_missed_bus(message: str, ctx: dict) -> str:
    """ctx: {"home": str, "employer": str, "address": str, "next_shift": str}"""
    from google.genai import types

    now = datetime.now(TZ).strftime("%A %Y-%m-%dT%H:%M:%S")
    system = (
        "You help a USF student who works part-time and rides the bus. "
        f"Current local time: {now}. Home: {ctx.get('home', 'USF campus')}. "
        f"Workplace: {ctx.get('employer', '')} at {ctx.get('address', '')}. "
        f"Next shift: {ctx.get('next_shift', 'unknown')}. "
        "When they miss a bus, call get_transit_route with depart_after set to the current time, "
        "then reply in 2-4 short sentences: the next option, the arrival time, and whether they "
        "will make the shift. If they will be late, say by how much and suggest messaging their manager. "
        "Never invent departure times; use only tool results."
    )
    resp = gemini.client().models.generate_content(  # shared client: repo-root GEMINI_API_KEY, timeout
        model=gemini.model_name(),
        contents=message,
        config=types.GenerateContentConfig(system_instruction=system, tools=[get_transit_route], temperature=0.2),
    )
    return resp.text or "I couldn't find a route right now. Check the HART app for live departures."
