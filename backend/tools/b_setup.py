"""Person B setup helpers. Run from backend/:

    python -m tools.b_setup bullrunner   # step 4: does Google transit include the Bull Runner?
    python -m tools.b_setup geocode      # fill lat/lng in data/part_time_jobs.json (uses the Routes API)
    python -m tools.b_setup warm         # step 2: cache every job's commute before the demo
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parents[2] / ".env")  # repo-root .env, same as main.py
import db  # noqa: E402
from agents import commute as cm  # noqa: E402

JOBS = Path(__file__).resolve().parent.parent / "data" / "part_time_jobs.json"


def bullrunner():
    dep = cm.datetime.now(cm.TZ)
    dep = (dep + timedelta(days=(7 - dep.weekday()) % 7 or 1)).replace(hour=10, minute=0, second=0, microsecond=0)  # next weekday-ish 10:00
    if dep.weekday() >= 5:
        dep += timedelta(days=7 - dep.weekday())
    route = cm.fetch_transit(cm.CAMPUS, "University Area Transit Center, Tampa, FL", depart_at=dep)
    if not route:
        print("No transit route at all. Check the key, billing, and that Routes API is enabled.")
        return
    lines = [s["line_name"] or s["line"] for s in route["steps"] if s["mode"] == "TRANSIT"]
    print("Transit lines returned:", lines or "none (walking only)")
    if any("bull runner" in l.lower() for l in lines):
        print("YES: Bull Runner is in Google's transit data. Use Google for the whole route.")
    else:
        print("NO: draw the campus-to-UATC leg from the Bull Runner/HART feed and use Google for the HART part.")


def geocode():
    jobs = json.loads(JOBS.read_text())
    for j in jobs:
        if j.get("lat") is not None:
            continue
        resp = cm._call(
            {"origin": cm._waypoint(cm.CAMPUS), "destination": cm._waypoint(j["address"]), "travelMode": "DRIVE"},
            "routes.legs.endLocation",
        )
        loc = resp["routes"][0]["legs"][0]["endLocation"]["latLng"]
        j["lat"], j["lng"] = round(loc["latitude"], 6), round(loc["longitude"], 6)
        print(j["id"], j["address"], "->", j["lat"], j["lng"])
    JOBS.write_text(json.dumps(jobs, indent=2))


def warm():
    jobs = json.loads(JOBS.read_text())
    origin = cm.home_origin(db.latest_profile())  # same origin /jobs uses, so these become cache hits
    print("Origin:", cm.origin_label(origin))
    for j in jobs:
        c = cm.commute_for_job(j, origin)
        print(j["id"], c.get("minutes"), "min", "car-free" if c.get("car_free") else "", c.get("error", ""))


if __name__ == "__main__":
    {"bullrunner": bullrunner, "geocode": geocode, "warm": warm}[sys.argv[1] if len(sys.argv) > 1 else "bullrunner"]()
