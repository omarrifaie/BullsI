"""Scout agent: internships from SimplifyJobs, part-time jobs from data/part_time_jobs.json."""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

import httpx

logger: logging.Logger = logging.getLogger("bullpen.scout")

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
LISTINGS_URL: str = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
LISTINGS_CACHE: Path = DATA_DIR / "listings_cache.json"  # runtime, gitignored
LISTINGS_SEED: Path = DATA_DIR / "listings_seed.json"  # committed snapshot, last resort
CACHE_MAX_AGE_S: int = 3600
PART_TIME_FILE: Path = DATA_DIR / "part_time_jobs.json"

# Live data uses "Software" and "AI/ML/Data"; the longer names match a handful of older rows.
CATEGORIES: set[str] = {"Software", "AI/ML/Data", "Software Engineering", "Data Science, AI & Machine Learning"}
NEWEST_N: int = 100
LOCAL_RE: re.Pattern[str] = re.compile(r"tampa|florida|,\s*fl\b|remote", re.IGNORECASE)

# Title keyword -> skills a posting with that title usually asks for (Simplify has no skills field).
TITLE_SKILLS: list[tuple[str, list[str]]] = [
  (r"data engineer|etl|analytics engineer", ["SQL", "Python", "dbt", "Snowflake", "Spark", "ETL"]),
  (r"data scien|analyst|analytics", ["Python", "SQL", "Pandas", "Statistics", "Tableau"]),
  (r"machine learning|\bml\b|\bai\b|deep learning|computer vision|nlp|llm", ["Python", "PyTorch", "Machine Learning", "SQL"]),
  (r"front.?end|ui\b|web", ["JavaScript", "TypeScript", "React", "HTML", "CSS"]),
  (r"back.?end|platform|api", ["Python", "Java", "SQL", "REST API", "PostgreSQL"]),
  (r"full.?stack", ["JavaScript", "React", "Python", "SQL", "REST API"]),
  (r"devops|cloud|infrastructure|site reliability|sre", ["Linux", "AWS", "Docker", "Kubernetes", "CI/CD"]),
  (r"security|cyber", ["Python", "Linux", "Networking", "Security"]),
  (r"database|dba", ["SQL", "PostgreSQL", "Database Administration", "Python"]),
  (r"embedded|firmware", ["C/C++", "Embedded Systems", "Linux"]),
  (r"mobile|ios|android", ["Swift", "Kotlin", "Mobile Development"]),
  (r"software|developer|engineer|swe|programm", ["Python", "Java", "C/C++", "Git", "Data Structures"]),
]


def title_skills(title: str) -> list[str]:
  skills: list[str] = []
  for pattern, words in TITLE_SKILLS:
    if re.search(pattern, title, re.IGNORECASE):
      skills += [w for w in words if w not in skills]
  return skills[:6]


def select_listings(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Active + visible + SWE/Data categories; newest 100 plus every Tampa/Florida/Remote listing."""
  kept: list[dict[str, Any]] = [
    x for x in raw if x.get("active") and x.get("is_visible") and x.get("category") in CATEGORIES
  ]
  kept.sort(key=lambda x: x.get("date_posted") or 0, reverse=True)
  newest: list[dict[str, Any]] = kept[:NEWEST_N]
  local: list[dict[str, Any]] = [x for x in kept[NEWEST_N:] if LOCAL_RE.search(" | ".join(x.get("locations") or []))]
  return newest + local


def normalize(x: dict[str, Any]) -> dict[str, Any]:
  return {
    "id": "job_" + x["id"].replace("-", "")[:8],
    "mode": "internship",
    "title": x["title"],
    "company": x["company_name"],
    "address": "; ".join(x.get("locations") or []) or "Unknown",
    "lat": None,
    "lng": None,
    "apply_url": x["url"],
    "shifts": [],
    "pay": None,
    "skills": title_skills(x["title"]),
    "match": None,
    "commute": None,
    # Not part of the contract; used by the Matcher and dropped by the Job model on output.
    "meta": {
      "locations": x.get("locations") or [],
      "sponsorship": x.get("sponsorship") or "Other",
      "date_posted": x.get("date_posted") or 0,
      "degrees": x.get("degrees") or [],
      "terms": x.get("terms") or [],
      "category": x.get("category") or "",
    },
  }


def fetch_internships() -> list[dict[str, Any]]:
  """Cache if under 1 hour old, else download; on failure fall back to cache, then the committed seed."""
  if LISTINGS_CACHE.exists() and time.time() - LISTINGS_CACHE.stat().st_mtime < CACHE_MAX_AGE_S:
    return [normalize(x) for x in cached_listings()]
  try:
    res: httpx.Response = httpx.get(LISTINGS_URL, timeout=30, follow_redirects=True)
    res.raise_for_status()
    selected: list[dict[str, Any]] = select_listings(res.json())
    LISTINGS_CACHE.write_text(json.dumps(selected), encoding="utf-8")
  except (httpx.HTTPError, ValueError) as exc:
    logger.warning("Simplify download failed (%s); using local copy", type(exc).__name__)
    selected = cached_listings()
  return [normalize(x) for x in selected]


def cached_listings() -> list[dict[str, Any]]:
  """Runtime cache if present, else the committed seed."""
  for path in (LISTINGS_CACHE, LISTINGS_SEED):
    if path.exists():
      return select_listings(json.loads(path.read_text(encoding="utf-8")))
  return []


PLACEHOLDER_PART_TIME: list[dict[str, Any]] = [
  {"id": "job_pt000001", "mode": "parttime", "title": "Barista", "company": "Bulls Brew Cafe",
   "address": "5010 E Fowler Ave, Tampa, FL 33617", "lat": 28.0545, "lng": -82.4008,
   "apply_url": "http://localhost:5173/mock-workday/job_pt000001",
   "shifts": [{"day": "Tue", "start": "15:00", "end": "21:00"}, {"day": "Thu", "start": "15:00", "end": "21:00"}],
   "pay": 15.0, "skills": ["customer service", "cash handling"], "match": None, "commute": None},
  {"id": "job_pt000002", "mode": "parttime", "title": "Library Desk Assistant",
   "company": "Tampa-Hillsborough Public Library", "address": "2902 W Bearss Ave, Tampa, FL 33618",
   "lat": 28.0880, "lng": -82.4960, "apply_url": "http://localhost:5173/mock-workday/job_pt000002",
   "shifts": [{"day": "Mon", "start": "13:00", "end": "15:00"}, {"day": "Fri", "start": "09:00", "end": "14:00"}],
   "pay": 14.5, "skills": ["organization", "customer service"], "match": None, "commute": None},
  {"id": "job_pt000003", "mode": "parttime", "title": "Retail Sales Associate", "company": "Target",
   "address": "1 Tampa Palms Blvd, Tampa, FL 33647", "lat": 28.1290, "lng": -82.3720,
   "apply_url": "http://localhost:5173/mock-workday/job_pt000003",
   "shifts": [{"day": "Fri", "start": "16:00", "end": "22:00"}, {"day": "Sat", "start": "10:00", "end": "16:00"}],
   "pay": 16.0, "skills": ["customer service", "inventory"], "match": None, "commute": None},
  {"id": "job_pt000004", "mode": "parttime", "title": "IT Support Technician", "company": "Moffitt Cancer Center",
   "address": "12902 USF Magnolia Dr, Tampa, FL 33612", "lat": 28.0640, "lng": -82.4210,
   "apply_url": "http://localhost:5173/mock-workday/job_pt000004",
   "shifts": [{"day": "Fri", "start": "08:00", "end": "14:00"}, {"day": "Tue", "start": "12:00", "end": "16:00"}],
   "pay": 18.0, "skills": ["troubleshooting", "Windows", "customer service", "SQL"], "match": None, "commute": None},
  {"id": "job_pt000005", "mode": "parttime", "title": "Line Cook", "company": "Taco Bus",
   "address": "913 E Hillsborough Ave, Tampa, FL 33604", "lat": 27.9960, "lng": -82.4480,
   "apply_url": "http://localhost:5173/mock-workday/job_pt000005",
   "shifts": [{"day": "Sat", "start": "11:00", "end": "19:00"}, {"day": "Sun", "start": "11:00", "end": "19:00"}],
   "pay": 15.5, "skills": ["food prep", "kitchen operations", "teamwork"], "match": None, "commute": None},
]


def load_part_time() -> list[dict[str, Any]]:
  """Teammate B owns part_time_jobs.json; create placeholders only if it doesn't exist yet."""
  if not PART_TIME_FILE.exists():
    PART_TIME_FILE.write_text(json.dumps(PLACEHOLDER_PART_TIME, indent=2), encoding="utf-8")
  # Teammate B's file may omit the contract's match/commute keys; Job requires them.
  return [{"match": None, "commute": None, **j} for j in json.loads(PART_TIME_FILE.read_text(encoding="utf-8"))]


def find_job(job_id: str) -> Optional[dict[str, Any]]:
  """Look up a job without network: cached internships + part-time file."""
  for job in [normalize(x) for x in cached_listings()] + load_part_time():
    if job["id"] == job_id:
      return job
  return None
