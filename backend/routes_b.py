"""Person B's FastAPI routes. In main.py:  app.include_router(routes_b.router)"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Response
from google.genai import errors as genai_errors
from pydantic import BaseModel

import db
from agents import commute as cm
from agents import scout

router = APIRouter()
logger = logging.getLogger("bullpen.routes_b")


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
    conn = db.connect()  # same absolute bullpen.db as the rest of the backend
    conn.execute("CREATE TABLE IF NOT EXISTS myjob(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT)")
    return conn


def _load_myjob() -> dict | None:
    with _db() as c:
        row = c.execute("SELECT data FROM myjob WHERE id=1").fetchone()
    return json.loads(row[0]) if row else None


def _origin(job: dict | None = None):
    return cm.home_origin(db.latest_profile(), job)


def _find_job(job_id: str) -> dict | None:
    return scout.find_job(job_id)


def _maps_unavailable(e: cm.MapsUnavailable) -> HTTPException:
    logger.warning("Routes API unavailable: %s", e)
    return HTTPException(503, f"Commute service unavailable: {e}")


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
    try:
        route, arrive_by = cm.shift_route(job, shift, _origin(job))
    except cm.MapsUnavailable as e:
        raise _maps_unavailable(e) from e
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
        try:
            route, arrive_by = cm.shift_route(job, shift, origin)
        except cm.MapsUnavailable as e:
            raise _maps_unavailable(e) from e
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
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(503, "Chat unavailable: GEMINI_API_KEY is not set in the repo-root .env")
    try:
        return {"reply": cm.answer_missed_bus(body.message, ctx)}
    except (genai_errors.APIError, httpx.HTTPError) as e:
        logger.warning("Gemini chat failed: %s", type(e).__name__)
        raise HTTPException(503, f"Chat unavailable: Gemini request failed ({type(e).__name__})") from e
