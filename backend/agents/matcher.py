"""Matcher agent: hard gates + plain-Python scores, then one batched Gemini call for top-20 reasons."""
import logging
import math
import re
import time
from typing import Any, Optional

from pydantic import BaseModel

import gemini
from agents.profile import parse_month_year

logger: logging.Logger = logging.getLogger("bullpen.matcher")

USF: tuple[float, float] = (28.06, -82.41)
CLASS_BUFFER_MIN: int = 30
TOP_N_REASONS: int = 20
TAMPA_BAY_RE: re.Pattern[str] = re.compile(
  r"tampa|st\.? ?petersburg|clearwater|brandon|largo|lakeland|wesley chapel|temple terrace|riverview|sarasota",
  re.IGNORECASE,
)
FLORIDA_RE: re.Pattern[str] = re.compile(r"florida|,\s*fl\b", re.IGNORECASE)
TAMPA_BAY_EMPLOYERS: set[str] = {
  "raymond james", "jabil", "cae", "mosaic", "moffitt cancer center", "baycare", "kforce", "connectwise",
  "knowbe4", "syniverse", "tampa electric", "teco", "publix", "bloomin' brands", "wellcare", "lazydays",
  "heritage insurance", "tampa general hospital", "university of south florida", "usf",
}
TERM_END_MONTH: dict[str, int] = {"spring": 5, "summer": 8, "fall": 12, "winter": 3}


# ---------- gates ----------

def passes_work_auth(profile: dict[str, Any], job: dict[str, Any]) -> bool:
  sponsorship: str = (job.get("meta") or {}).get("sponsorship", "Other")
  auth: str = profile["work_authorization"]
  if sponsorship == "U.S. Citizenship is Required":
    return auth == "citizen"
  if sponsorship == "Does Not Offer Sponsorship":
    return auth != "needs_sponsorship"
  return True  # "Offers Sponsorship" or "Other" (unknown)


def _minutes(hhmm: str) -> int:
  h, m = hhmm.split(":")
  return int(h) * 60 + int(m)


def passes_schedule(profile: dict[str, Any], job: dict[str, Any]) -> bool:
  """Part-time only: no shift may overlap a class widened by 30 minutes on each side."""
  for shift in job.get("shifts") or []:
    for cls in profile.get("class_schedule") or []:
      if shift["day"] != cls["day"]:
        continue
      busy_start: int = _minutes(cls["start"]) - CLASS_BUFFER_MIN
      busy_end: int = _minutes(cls["end"]) + CLASS_BUFFER_MIN
      if _minutes(shift["start"]) < busy_end and _minutes(shift["end"]) > busy_start:
        return False
  return True


# ---------- scoring helpers ----------

def _norm(s: str) -> str:
  return re.sub(r"[^a-z0-9+#]", "", s.lower())


def _profile_text(profile: dict[str, Any]) -> str:
  parts: list[str] = list(profile.get("skills") or [])
  for item in (profile.get("experience") or []) + (profile.get("projects") or []):
    parts += [item.get("title", ""), item.get("name", ""), *item.get("tech", [])]
    parts += [b["text"] for b in item.get("bullets") or []]
  return " ".join(parts).lower()


def skill_overlap(profile: dict[str, Any], job_skills: list[str]) -> tuple[float, list[str]]:
  """Fraction of the job's skills the student has (exact skill or mentioned in experience)."""
  if not job_skills:
    return 0.5, []
  have: set[str] = {_norm(s) for s in profile.get("skills") or []}
  text: str = _profile_text(profile)
  matched: list[str] = [s for s in job_skills if _norm(s) in have or s.lower() in text]
  return len(matched) / len(job_skills), matched


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
  lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
  h: float = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
  return 6371 * 2 * math.asin(math.sqrt(h))


def _linear(value: float, full_at: float, zero_at: float) -> float:
  """1.0 at or below full_at, 0.0 at or above zero_at, linear between."""
  if value <= full_at:
    return 1.0
  if value >= zero_at:
    return 0.0
  return (zero_at - value) / (zero_at - full_at)


def experience_fit(profile: dict[str, Any], job: dict[str, Any], now: float) -> float:
  """0..1 from degrees[] (12/20), terms[] vs graduation (8/20), and year in school vs senior-ish titles."""
  meta: dict[str, Any] = job.get("meta") or {}
  degrees: list[str] = meta.get("degrees") or []
  year: str = ((profile.get("education") or [{}])[0]).get("year_in_school", "")
  grad_student: bool = year == "graduate"
  if not degrees or "Bachelor's" in degrees or (grad_student and {"Master's", "PhD"} & set(degrees)):
    degree_pts: float = 12
  else:
    degree_pts = 3  # graduate-only posting for an undergrad
  term_pts: float = 5  # "N/A" or unparseable terms
  grad: Optional[tuple[int, int]] = parse_month_year(((profile.get("education") or [{}])[0]).get("graduation", ""))
  now_ym: tuple[int, int] = (time.gmtime(now).tm_year, time.gmtime(now).tm_mon)
  term_scores: list[float] = []
  for term in meta.get("terms") or []:
    m: Optional[re.Match[str]] = re.match(r"(Spring|Summer|Fall|Winter)\s+(\d{4})", term)
    if not m:
      continue
    ends: tuple[int, int] = (int(m.group(2)), TERM_END_MONTH[m.group(1).lower()])
    if ends < now_ym:
      term_scores.append(0)  # already over
    elif grad and ends > grad:
      term_scores.append(1)  # student will have graduated
    else:
      term_scores.append(8)
  if term_scores:
    term_pts = max(term_scores)
  senior_title: bool = bool(re.search(r"\b(phd|master'?s|graduate)\b", job["title"], re.IGNORECASE))
  if senior_title and not grad_student:
    degree_pts = min(degree_pts, 3)
  return (degree_pts + term_pts) / 20


def _is_us_remote(location: str) -> bool:
  """'Remote' or 'Remote in USA' count; 'Remote in Canada' does not."""
  loc: str = location.lower()
  if "remote" not in loc:
    return False
  m: Optional[re.Match[str]] = re.search(r"remote in (.+)", loc)
  return m is None or bool(re.match(r"(usa|us|united states)\b", m.group(1)))


def location_fit(profile: dict[str, Any], locations: list[str]) -> float:
  joined: str = " | ".join(locations)
  preferred: list[str] = [c.split(",")[0].strip().lower() for c in profile["preferences"].get("preferred_cities") or []]
  if TAMPA_BAY_RE.search(joined) or any(c and c in joined.lower() for c in preferred):
    return 1.0
  if any(_is_us_remote(loc) for loc in locations):
    return 0.8
  if FLORIDA_RE.search(joined):
    return 0.6
  return 0.0


def is_tampa_bay_employer(job: dict[str, Any]) -> bool:
  company: str = job["company"].lower()
  return company in TAMPA_BAY_EMPLOYERS or bool(TAMPA_BAY_RE.search(job.get("address", "")))


def _clamp(score: float) -> int:
  return max(0, min(100, round(score)))


# ---------- scores ----------

def score_internship(profile: dict[str, Any], job: dict[str, Any], now: float) -> tuple[int, dict[str, Any]]:
  meta: dict[str, Any] = job.get("meta") or {}
  skill_frac, matched = skill_overlap(profile, job["skills"])
  age_days: float = (now - (meta.get("date_posted") or 0)) / 86400
  parts: dict[str, float] = {
    "skills": 40 * skill_frac,
    "experience": 20 * experience_fit(profile, job, now),
    "location": 20 * location_fit(profile, meta.get("locations") or [job["address"]]),
    "recency": 10 * _linear(age_days, 7, 60),
    "tampa_bay": 10 if is_tampa_bay_employer(job) else 0,
  }
  return _clamp(sum(parts.values())), {**{k: round(v, 1) for k, v in parts.items()}, "matched_skills": matched}


def score_parttime(profile: dict[str, Any], job: dict[str, Any]) -> tuple[int, dict[str, Any]]:
  class_days: set[str] = {c["day"] for c in profile.get("class_schedule") or []}
  shifts: list[dict[str, str]] = job.get("shifts") or []
  schedule_frac: float = sum(1.0 if s["day"] not in class_days else 0.7 for s in shifts) / len(shifts) if shifts else 0.5
  commute: Optional[dict[str, Any]] = job.get("commute")
  if commute:  # teammate B's real data
    commute_frac: float = _linear(commute["minutes"], 15, 60)
    commute_note: str = f"{commute['minutes']} min"
  elif job.get("lat") is not None and job.get("lng") is not None:
    km: float = haversine_km(USF, (job["lat"], job["lng"]))
    commute_frac = _linear(km, 3, 25)
    commute_note = f"{km:.1f} km from USF"
  else:
    commute_frac, commute_note = 0.5, "unknown distance"
  skill_frac, matched = skill_overlap(profile, job.get("skills") or [])
  min_pay: Optional[float] = profile["preferences"].get("min_pay")
  pay: float = job.get("pay") or 0
  pay_frac: float = min(1.0, pay / (min_pay or 15.0)) if pay else 0.0
  parts: dict[str, float] = {
    "schedule": 35 * schedule_frac,
    "commute": 25 * commute_frac,
    "skills": 20 * skill_frac,
    "pay": 10 * pay_frac,
    "tampa_bay": 10 if is_tampa_bay_employer(job) else 0,
  }
  return _clamp(sum(parts.values())), {**{k: round(v, 1) for k, v in parts.items()},
                                       "matched_skills": matched, "commute_note": commute_note}


# ---------- reasons ----------

class Reason(BaseModel):
  id: str
  reason: str


class Reasons(BaseModel):
  reasons: list[Reason]


def template_reason(job: dict[str, Any], breakdown: dict[str, Any]) -> str:
  matched: list[str] = breakdown.get("matched_skills") or []
  if job["mode"] == "parttime":
    return f"Shifts avoid your classes, {breakdown.get('commute_note', '')}".strip(", ")
  where: str = "Tampa Bay role" if breakdown.get("tampa_bay") else "Role"
  return f"{where} matching {', '.join(matched[:2])}" if matched else f"{where} worth a look for your profile"


def _clean_reason(text: str, max_words: int = 11) -> Optional[str]:
  """Reasons must be under 12 words. Over-long ones are dropped (template used) rather than cut mid-sentence."""
  words: list[str] = text.strip().rstrip(".").split()
  return " ".join(words) if 0 < len(words) <= max_words else None


def write_reasons(profile: dict[str, Any], ranked: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, str]:
  """One Gemini call for all top jobs. Falls back to templates on any failure."""
  if not ranked:
    return {}
  lines: list[str] = []
  for job, breakdown in ranked:
    meta: dict[str, Any] = job.get("meta") or {}
    lines.append(
      f"- id={job['id']} | {job['title']} at {job['company']} | {job['address']}"
      f" | shifts={job.get('shifts')} | pay={job.get('pay')} | score parts={breakdown}"
      f" | terms={meta.get('terms', [])}"
    )
  edu: dict[str, Any] = (profile.get("education") or [{}])[0]
  prompt: str = (
    f"Student: {edu.get('year_in_school', '')} {edu.get('major', '')} at USF. Skills: {', '.join(profile.get('skills') or [])}.\n"
    f"Classes: {profile.get('class_schedule')}.\n\nJobs (already scored; score parts show why):\n" + "\n".join(lines) +
    "\n\nFor EVERY job id, write one reason of AT MOST 10 words telling the student why it fits them. "
    "Be specific (name a matching skill, the location, or the schedule). Only use facts given above."
  )
  try:
    out: Reasons = gemini.generate_json([prompt], Reasons)
    cleaned: dict[str, Optional[str]] = {r.id: _clean_reason(r.reason) for r in out.reasons}
    return {job_id: reason for job_id, reason in cleaned.items() if reason}
  except Exception as exc:
    logger.warning("Reason generation failed (%s); using templates", type(exc).__name__)
    return {}


# ---------- entry point ----------

def rank(profile: dict[str, Any], jobs: list[dict[str, Any]], now: Optional[float] = None) -> list[dict[str, Any]]:
  """Gate, score, sort, and attach match {score, reason}. Failed jobs are dropped, not shown low."""
  now = now or time.time()
  scored: list[tuple[dict[str, Any], dict[str, Any]]] = []
  for job in jobs:
    if not passes_work_auth(profile, job):
      continue
    if job["mode"] == "parttime":
      if not passes_schedule(profile, job):
        continue
      score, breakdown = score_parttime(profile, job)
    else:
      score, breakdown = score_internship(profile, job, now)
    scored.append(({**job, "match": {"score": score, "reason": ""}}, breakdown))
  scored.sort(key=lambda pair: pair[0]["match"]["score"], reverse=True)
  reasons: dict[str, str] = write_reasons(profile, scored[:TOP_N_REASONS])
  for job, breakdown in scored:
    job["match"]["reason"] = reasons.get(job["id"]) or template_reason(job, breakdown)
  return [job for job, _ in scored]
