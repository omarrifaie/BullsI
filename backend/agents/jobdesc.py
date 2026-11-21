"""Job description fetcher for queued internships. Greenhouse/Lever public JSON APIs, else Gemini URL context.

POST /queue starts a background fetch (30 s budget). /prepare waits at most 10 s for it, then goes title-only;
the background fetch keeps running and caches its result for later. Never raises. Results (including "not found")
are cached per job id so each job is fetched at most once."""
import html
import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Optional

import httpx
from google.genai import types
from pydantic import BaseModel

import db
import gemini

logger: logging.Logger = logging.getLogger("bullpen.jobdesc")

TIMEOUT_S: float = 30.0  # background fetch budget (Gemini URL context measured at 14-23 s)
WAIT_S: float = 10.0  # longest /prepare waits for an in-flight fetch
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
  if not out.found:
    logger.warning("Gemini could not read a description from %s", url.split("/")[2])
  return out.description if out.found else ""


_pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="jobdesc")
_inflight: dict[str, Future[str]] = {}
_inflight_lock: threading.Lock = threading.Lock()


def _key(job: dict[str, Any]) -> str:
  return f"jd:{job['id']}"


def _fetch_and_cache(job: dict[str, Any]) -> str:
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
    logger.warning("No description for %s (%s: %s)", job["id"], type(exc).__name__, str(exc)[:120])
  text = text.strip()[:MAX_CHARS]
  try:
    db.cache_set(_key(job), text)
  finally:
    with _inflight_lock:
      _inflight.pop(job["id"], None)
  return text


def prefetch(job: dict[str, Any]) -> Optional[Future[str]]:
  """Start a background fetch unless one is cached or already running. Returns immediately."""
  if db.cache_get(_key(job)) is not None:
    return None
  with _inflight_lock:
    future: Optional[Future[str]] = _inflight.get(job["id"])
    if future is None:
      future = _pool.submit(_fetch_and_cache, job)
      _inflight[job["id"]] = future
  return future


def fetch(job: dict[str, Any], wait_s: float = WAIT_S) -> Optional[str]:
  """Description text, or None. Waits at most wait_s for the (possibly already running) fetch. Never raises."""
  cached: Optional[str] = db.cache_get(_key(job))
  if cached is not None:
    return cached or None
  future: Optional[Future[str]] = prefetch(job)
  if future is None:  # finished between the two checks
    return db.cache_get(_key(job)) or None
  try:
    return future.result(timeout=wait_s) or None
  except FutureTimeout:
    logger.info("Description for %s still loading after %ss; using title only", job["id"], wait_s)
    return None
  except Exception as exc:  # e.g. the cache write failed in the background thread
    logger.warning("Description fetch for %s failed (%s)", job["id"], type(exc).__name__)
    return None
