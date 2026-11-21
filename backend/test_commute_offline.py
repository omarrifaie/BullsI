"""Run: python test_commute_offline.py   (no API keys needed)"""
import os
import tempfile

os.environ["BULLPEN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["GOOGLE_MAPS_API_KEY"] = "fake"

from agents import commute as cm

FAKE = {"routes": [{
    "duration": "1500s", "distanceMeters": 9000,
    "legs": [{"steps": [
        {"travelMode": "WALK", "staticDuration": "240s", "distanceMeters": 300,
         "navigationInstruction": {"instructions": "Walk to Marshall Student Center"},
         "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"}},
        {"travelMode": "TRANSIT", "staticDuration": "900s",
         "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC"},
         "transitDetails": {
             "headsign": "UATC", "stopCount": 4,
             "stopDetails": {
                 "departureStop": {"name": "Marshall Student Center"},
                 "arrivalStop": {"name": "UATC"},
                 "departureTime": "2026-11-24T19:22:00Z", "arrivalTime": "2026-11-24T19:37:00Z"},
             "transitLine": {"name": "Bull Runner", "nameShort": "BR", "color": "#006747"}}},
    ]}]}]}

cm.fetch_transit.__globals__["_call"] = lambda body, mask: (
    {"routes": [{"distanceMeters": 12000}]} if body["travelMode"] == "DRIVE" else FAKE)

job = {"id": "job_1", "address": "1 Main St, Tampa", "lat": 28.07, "lng": -82.41,
       "shifts": [{"day": "Tue", "start": "15:00", "end": "21:00"},
                  {"day": "Thu", "start": "15:00", "end": "21:00"}]}

out = cm.commute_for_job(job)
assert out["minutes"] == 25 and out["car_free"] and out["transfers"] == 0
assert out["cost_usd"] == 0.0, "Bull Runner should be fare-free"
# 12000 m = 7.46 mi * 0.4 kg * 4 trips = 11.9 kg
assert abs(out["co2_saved_kg_week"] - 11.9) < 0.2, out["co2_saved_kg_week"]
assert out["steps"][1]["depart"] == "14:22", out["steps"][1]["depart"]
assert out["leave_by"] == "14:18", out["leave_by"]  # 14:22 minus 4 min walk
for k in ("mode", "line", "from_stop", "to_stop", "depart", "arrive", "polyline"):
    assert all(k in s for s in out["steps"]), k
# cached second call must not hit the API
cm.fetch_transit.__globals__["_call"] = lambda *a: (_ for _ in ()).throw(RuntimeError("cache miss"))
assert cm.commute_for_job(job)["minutes"] == 25

# next_shift_start is always in the future and on the right weekday
d = cm.next_shift_start("Tue", "15:00")
assert d > cm.datetime.now(cm.TZ) and d.weekday() == 1

# calendar (routes_b imports fastapi; install fastapi pydantic to run this part)
from routes_b import build_ics
from datetime import timedelta
ics = build_ics([{"name": "Leave for Cafe, Inc.", "begin": d, "end": d + timedelta(minutes=25),
                  "location": "1 Main St, Tampa", "description": "line one\nline two"}])
assert "BEGIN:VEVENT" in ics and "SUMMARY:Leave for Cafe\\, Inc." in ics and "DESCRIPTION:line one\\nline two" in ics
print("all good:", out["minutes"], "min,", out["co2_saved_kg_week"], "kg CO2/week, leave by", out["leave_by"])
