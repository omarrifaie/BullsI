"""Job description fetcher for queued internships. Greenhouse/Lever public JSON APIs, else Gemini URL context.
Hard 10 s budget, never raises, result (including "not found") cached per job id so each job pays at most once."""
import html
import logging
import re
from typing import Any, Optional

import httpx
from google.genai import types
from pydantic import BaseModel

import db
import gemini

logger: logging.Logger = logging.getLogger("bullpen.jobdesc")

TIMEOUT_S: float = 10.0
MAX_CHARS: int = 6000
GREENHOUSE_RE: re.Pattern[str] = re.compile(
  r"^https://(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?P<board>[\w-]+)/jobs/(?P<id>\d+)")
LEVER_RE: re.Pattern[str] = re.compile(
  r"^https://jobs\.lever\.co/(?P<company>[\w.-]+)/(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


class FetchedDescription(BaseModel):
  found: bool
  description: str


def html_to_text(raw: str) -> str:
  text: str = html.unescape(html.unescape(raw))  # Greenhouse double-encodes its HTML
  text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text, flags=re.IGNORECASE)
  text = re.sub(r"<[^>]+>", " ", text)
  return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()


def _greenhouse(m: re.Match[str]) -> str:
  url: str = f"https://boards-api.greenhouse.io/v1/boards/{m['board']}/jobs/{m['id']}"
  return html_to_text(httpx.get(url, timeout=TIMEOUT_S).raise_for_status().json().get("content", ""))


def _lever(m: re.Match[str]) -> str:
  data: dict[str, Any] = httpx.get(f"https://api.lever.co/v0/postings/{m['company']}/{m['id']}",
                                   timeout=TIMEOUT_S).raise_for_status().json()
  parts: list[str] = [data.get("descriptionPlain", "")]
  for section in data.get("lists") or []:
    parts += [section.get("text", ""), html_to_text(section.get("content", ""))]
  parts.append(data.get("additionalPlain", ""))
  return "\n".join(p for p in parts if p)


def _gemini_url_context(url: str) -> str:
  out: FetchedDescription = gemini.generate_json(
    [f"Read this job posting and return its full description text (responsibilities and requirements): {url}"],
    FetchedDescription,
    tools=[types.Tool(url_context=types.UrlContext())],
    timeout_ms=int(TIMEOUT_S * 1000),
  )
  return out.description if out.found else ""


def fetch(job: dict[str, Any]) -> Optional[str]:
  """Description text, or None. Never raises."""
  key: str = f"jd:{job['id']}"
  cached: Optional[str] = db.cache_get(key)
  if cached is not None:
    return cached or None
  url: str = job.get("apply_url") or ""
  text: str = ""
  try:
    if gh := GREENHOUSE_RE.match(url):
      text = _greenhouse(gh)
    elif lv := LEVER_RE.match(url):
      text = _lever(lv)
    elif url.startswith("https://"):
      text = _gemini_url_context(url)
  except Exception as exc:
    logger.info("No description for %s (%s)", job["id"], type(exc).__name__)
  text = text.strip()[:MAX_CHARS]
  db.cache_set(key, text)
  return text or None
