"""Person B's FastAPI routes. In main.py:  app.include_router(routes_b.router)"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from agents import commute as cm

router = APIRouter()
DATA = Path(__file__).parent / "data" / "part_time_jobs.json"


# ---------- models ----------
class Shift(BaseModel):
    day: str    # Mon..Sun
    start: str  # "15:00"
    end: str


class MyJobIn(BaseModel):
    employer: str
    address: str
    shifts: list[Shift]
    home_address: str | None = None  # defaults to the profile address, then campus


class ChatIn(BaseModel):
    message: str


# ---------- storage ----------
def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(cm.DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS myjob(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT)")
    return conn


def _load_myjob() -> dict | None:
    with _db() as c:
        row = c.execute("SELECT data FROM myjob WHERE id=1").fetchone()
    return json.loads(row[0]) if row else None


def _origin(job: dict | None = None):
    if job and job.get("home_address"):
        return job["home_address"]
    try:
        from db import get_profile  # Person A's helper; rename here if theirs differs
        addr = (get_profile() or {}).get("address")
        if addr:
            return addr
    except Exception:
        pass
    return cm.CAMPUS


def _find_job(job_id: str) -> dict | None:
    try:
        from db import get_job  # Person A's helper; rename here if theirs differs
        j = get_job(job_id)
        if j:
            return j
    except Exception:
        pass
    if DATA.exists():
        return next((j for j in json.loads(DATA.read_text()) if j["id"] == job_id), None)
    return None


def _next_shift(job: dict):
    return min(job["shifts"], key=lambda s: cm.next_shift_start(s["day"], s["start"]))



def _ics_text(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(events: list[dict]) -> str:
    """Tiny RFC 5545 writer (no dependency). events: name, begin, end (aware datetimes), location, description."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BullPen//Leave-by//EN", "CALSCALE:GREGORIAN"]
    for i, e in enumerate(events):
        out += [
            "BEGIN:VEVENT",
            f"UID:bullpen-{fmt(e['begin'])}-{i}@bullpen.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{fmt(e['begin'])}",
            f"DTEND:{fmt(e['end'])}",
            f"SUMMARY:{_ics_text(e['name'])}",
            f"LOCATION:{_ics_text(e['location'])}",
            f"DESCRIPTION:{_ics_text(e['description'])}",
            "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Time to leave", "TRIGGER:-PT5M", "END:VALARM",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


# ---------- routes ----------
@router.get("/jobs/{job_id}/commute")
def job_commute(job_id: str):
    job = _find_job(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    return cm.commute_for_job(job, _origin())


@router.post("/myjob")
def save_myjob(body: MyJobIn):
    data = body.model_dump()
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO myjob VALUES (1, ?)", (json.dumps(data),))
    return {"ok": True}


@router.get("/myjob")
def get_myjob():
    return _load_myjob() or {}


@router.get("/myjob/today")
def myjob_today():
    job = _load_myjob()
    if not job or not job["shifts"]:
        raise HTTPException(404, "Add your job first")
    shift = _next_shift(job)
    route, arrive_by = cm.shift_route(job, shift, _origin(job))
    if not route:
        raise HTTPException(502, "No transit route found for the next shift")
    leave = cm.leave_by_time(route, arrive_by)
    starts = cm.next_shift_start(shift["day"], shift["start"])
    return {
        "employer": job["employer"],
        "address": job["address"],
        "shift": shift,
        "starts_at": starts.isoformat(),
        "arrive_by": arrive_by.astimezone(cm.TZ).strftime("%H:%M"),
        "leave_by": leave.astimezone(cm.TZ).strftime("%H:%M"),
        "leave_by_iso": leave.isoformat(),
        "minutes": route["minutes"],
        "cost_usd": route["cost_usd"],
        "steps": route["steps"],
    }


@router.get("/myjob/calendar.ics")
def myjob_calendar():
    job = _load_myjob()
    if not job:
        raise HTTPException(404, "Add your job first")
    origin = _origin(job)
    events = []
    for shift in job["shifts"]:
        route, arrive_by = cm.shift_route(job, shift, origin)
        if not route:
            continue
        leave = cm.leave_by_time(route, arrive_by)
        lines = [
            f"{s['depart']} {s['instruction']} ({s['from_stop']} to {s['to_stop']})"
            if s["mode"] == "TRANSIT" else f"{s['instruction']} ({s['minutes']} min)"
            for s in route["steps"]
        ]
        for week in range(4):  # next four weeks of shifts
            begin = leave + timedelta(days=7 * week)
            events.append({
                "name": f"Leave for {job['employer']}",
                "begin": begin,
                "end": begin + timedelta(minutes=route["minutes"]),
                "location": job["address"],
                "description": "\n".join(lines),
            })
    return Response(
        content=build_ics(events),
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="bullpen-shifts.ics"'},
    )


@router.post("/chat")
def chat(body: ChatIn):
    job = _load_myjob() or {}
    ctx = {"home": _origin(job) if job else "USF campus"}
    if job:
        s = _next_shift(job)
        ctx |= {"employer": job["employer"], "address": job["address"],
                "next_shift": f"{s['day']} {s['start']}-{s['end']}"}
    if not isinstance(ctx["home"], str):
        ctx["home"] = "USF campus"
    return {"reply": cm.answer_missed_bus(body.message, ctx)}
