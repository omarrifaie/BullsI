"""Profile agent: resume PDF + schedule screenshot -> Profile, via one Gemini call."""
import re
from datetime import date
from typing import Any, Literal, Optional

from google.genai import types
from pydantic import BaseModel

import gemini
from models import Bullet, Education, Experience, Preferences, Profile, Project, TimeBlock

# Gemini fills these; code assigns bullet ids afterwards so they are always stable and unique.


class ExtractedExperience(BaseModel):
  title: str
  organization: str
  location: str
  start: str
  end: str
  bullets: list[str]


class ExtractedProject(BaseModel):
  name: str
  tech: list[str]
  bullets: list[str]


class ExtractedPreferences(BaseModel):
  roles: list[str]
  preferred_cities: list[str]


class ExtractedProfile(BaseModel):
  name: str
  email: str
  phone: str
  address: str
  work_authorization: Literal["citizen", "permanent_resident", "needs_sponsorship"]
  education: list[Education]
  experience: list[ExtractedExperience]
  projects: list[ExtractedProject]
  skills: list[str]
  class_schedule: list[TimeBlock]
  preferences: ExtractedPreferences


SYSTEM: str = """You extract a student's profile from two inputs: a resume PDF and a screenshot of their class schedule.
Rules:
- Copy resume bullets verbatim, one string per bullet. Never invent experience, projects, or skills.
- Use "" for any text field not present. Use [] for missing lists.
- work_authorization: "needs_sponsorship" only if the resume says the student needs visa sponsorship or is on F-1/OPT/CPT;
  "permanent_resident" if it says green card / permanent resident; otherwise "citizen".
- education.year_in_school: one of freshman, sophomore, junior, senior, graduate, inferred from the expected graduation
  date relative to November 2026 if not stated.
- class_schedule comes ONLY from the schedule screenshot. One entry per day per class meeting (expand "MWF" or "TR" into
  separate days). day is one of Mon, Tue, Wed, Thu, Fri, Sat, Sun. start and end are 24-hour "HH:MM".
- preferences.roles: up to 3 role types the resume targets (e.g. "software engineering"). preferred_cities: [] unless stated.
"""

DAYS: dict[str, str] = {d.lower(): d for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}


def _hhmm(value: str) -> str:
  """Normalize "9:30", "09:30", "9:30 PM" to 24h "HH:MM"."""
  m: Optional[re.Match[str]] = re.match(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?", value)
  if not m:
    return value
  hour: int = int(m.group(1))
  ampm: Optional[str] = m.group(3)
  if ampm and ampm.lower() == "pm" and hour < 12:
    hour += 12
  if ampm and ampm.lower() == "am" and hour == 12:
    hour = 0
  return f"{hour:02d}:{m.group(2)}"


MONTHS: list[str] = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse_month_year(text: str) -> Optional[tuple[int, int]]:
  """'Dec 2027' / 'December 2027' -> (2027, 12)."""
  m: Optional[re.Match[str]] = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", text)
  if not m or m.group(1).lower() not in MONTHS:
    return None
  return int(m.group(2)), MONTHS.index(m.group(1).lower()) + 1


def year_from_graduation(graduation: str, today: date) -> Optional[str]:
  """'Dec 2027' seen in Nov 2026 -> 'junior'. Gemini guessed this wrong live, so code decides."""
  ym: Optional[tuple[int, int]] = parse_month_year(graduation)
  if not ym:
    return None
  months_left: int = (ym[0] - today.year) * 12 + ym[1] - today.month
  if months_left <= 12:
    return "senior"
  if months_left <= 24:
    return "junior"
  if months_left <= 36:
    return "sophomore"
  return "freshman"


def build_profile(extracted: ExtractedProfile, today: Optional[date] = None) -> dict[str, Any]:
  """Assign stable bullet ids (exp1_b1, proj2_b3, ...), normalize the schedule, derive year in school."""
  education: list[Education] = [e.model_copy() for e in extracted.education]
  for edu in education:
    if not re.search(r"master|ph\.?d|m\.s\.|mba", edu.degree, re.IGNORECASE):
      edu.year_in_school = year_from_graduation(edu.graduation, today or date.today()) or edu.year_in_school
  experience: list[Experience] = [
    Experience(
      id=f"exp{i}", title=e.title, organization=e.organization, location=e.location, start=e.start, end=e.end,
      bullets=[Bullet(id=f"exp{i}_b{j}", text=t) for j, t in enumerate(e.bullets, start=1)],
    )
    for i, e in enumerate(extracted.experience, start=1)
  ]
  projects: list[Project] = [
    Project(id=f"proj{i}", name=p.name, tech=p.tech,
            bullets=[Bullet(id=f"proj{i}_b{j}", text=t) for j, t in enumerate(p.bullets, start=1)])
    for i, p in enumerate(extracted.projects, start=1)
  ]
  schedule: list[TimeBlock] = [
    TimeBlock(day=DAYS.get(c.day[:3].lower(), c.day), start=_hhmm(c.start), end=_hhmm(c.end))
    for c in extracted.class_schedule
  ]
  profile: Profile = Profile(
    name=extracted.name, email=extracted.email, phone=extracted.phone, address=extracted.address,
    work_authorization=extracted.work_authorization, education=education, experience=experience,
    projects=projects, skills=extracted.skills, class_schedule=schedule, transportation="",
    preferences=Preferences(roles=extracted.preferences.roles,
                            preferred_cities=extracted.preferences.preferred_cities),
  )
  return profile.model_dump(exclude={"id"})


US_STATE_CODES: set[str] = {
  "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA",
  "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR",
  "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"}


def us_country_from_address(address: str) -> str:
  """"..., Tampa, FL 33620" or "Tampa, FL" -> "United States of America"; anything else -> "" (never guessed)."""
  match: Optional[re.Match[str]] = re.search(r",\s*([A-Z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$", address or "")
  return "United States of America" if match and match[1] in US_STATE_CODES else ""


def apply_signup(profile: dict[str, Any], form: dict[str, Any]) -> dict[str, Any]:
  """Signup form answers override anything Gemini extracted. None/"" means not answered."""
  for key in ("name", "email", "phone", "address", "work_authorization", "transportation",
              "country", "phone_device_type", "how_heard"):
    if form.get(key):
      profile[key] = form[key]
  if not profile.get("country"):
    profile["country"] = us_country_from_address(profile.get("address", ""))  # derived from the state, not guessed
  if form.get("year_in_school"):
    if not profile["education"]:
      profile["education"] = [Education(school="University of South Florida").model_dump()]
    profile["education"][0]["year_in_school"] = form["year_in_school"]
  if form.get("preferred_cities"):
    profile["preferences"]["preferred_cities"] = [c.strip() for c in form["preferred_cities"].split(";") if c.strip()]
  for key in ("min_pay", "max_commute_minutes"):
    if form.get(key) is not None:
      profile["preferences"][key] = form[key]
  return Profile.model_validate(profile).model_dump(exclude={"id"})


def extract(resume_pdf: bytes, schedule_img: bytes, schedule_mime: str) -> ExtractedProfile:
  return gemini.generate_json(
    [
      types.Part.from_bytes(data=resume_pdf, mime_type="application/pdf"),
      types.Part.from_bytes(data=schedule_img, mime_type=schedule_mime),
      "The first file is the resume. The second is the class schedule screenshot. Extract the profile.",
    ],
    ExtractedProfile,
    system=SYSTEM,
  )


def run(resume_pdf: bytes, schedule_img: bytes, schedule_mime: str, form: dict[str, Any]) -> dict[str, Any]:
  return apply_signup(build_profile(extract(resume_pdf, schedule_img, schedule_mime)), form)
