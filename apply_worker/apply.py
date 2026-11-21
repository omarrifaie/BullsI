"""BullPen apply worker. Opens one visible Chromium tab per queued job, fills what it can, never submits.

Run by hand: .venv\\Scripts\\python apply.py --backend http://localhost:8000
Mock run, no backend: .venv\\Scripts\\python apply.py --mock [--signin] [--mock-url http://localhost:5173/mock-workday/demo]
POST /apply on the backend starts this same script as a subprocess.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from playwright.async_api import BrowserContext, Page, async_playwright

import fill
import panel

HERE: Path = Path(__file__).resolve().parent
STATUS_FILE: Path = HERE / "status.json"
TMP_DIR: Path = HERE / "tmp"
BROWSER_PROFILE: Path = HERE / "browser_profile"
MOCK_DIR: Path = HERE / "mock"


class StatusFile:
  """Per-job progress in status.json; GET /apply/status on the backend serves it. One lock, atomic writes."""

  def __init__(self, path: Path = STATUS_FILE) -> None:
    self.path: Path = path
    self.jobs: dict[str, dict[str, Any]] = {}
    self.lock: asyncio.Lock = asyncio.Lock()

  async def update(self, job_id: str, **fields: Any) -> None:
    async with self.lock:
      job: dict[str, Any] = self.jobs.setdefault(
        job_id, {"job_id": job_id, "status": "opening", "filled_count": 0, "needs_you": []})
      job.update(fields)
      tmp: Path = self.path.with_suffix(".json.tmp")
      tmp.write_text(json.dumps({"jobs": list(self.jobs.values())}, indent=2), encoding="utf-8")
      os.replace(tmp, self.path)


async def download_documents(client: httpx.AsyncClient, job: dict[str, Any]) -> dict[str, Optional[Path]]:
  """Save the job's tailored PDFs to tmp/<job_id>/ so they can go into set_input_files."""
  out: dict[str, Optional[Path]] = {"resume": None, "cover_letter": None}
  folder: Path = TMP_DIR / job["job_id"]
  for key in out:
    url: Optional[str] = job.get(f"{key}_url")
    if not url:
      continue
    res: httpx.Response = await client.get(url)
    res.raise_for_status()
    folder.mkdir(parents=True, exist_ok=True)
    path: Path = folder / f"{key}.pdf"
    path.write_bytes(res.content)
    out[key] = path
  return out


async def wait_for_signin(page: Page, job_id: str, status: StatusFile, clicked: asyncio.Event) -> None:
  """Banner + wait with no timeout until the student clicks its Continue button. Never reads or types passwords.
  The banner is re-added every second in case a sign-in navigation wiped it."""
  await status.update(job_id, status="waiting_for_signin")
  clicked.clear()
  while not clicked.is_set():
    await panel.show_signin_banner(page)
    try:
      await asyncio.wait_for(clicked.wait(), timeout=1.0)
    except asyncio.TimeoutError:
      pass
  await status.update(job_id, status="filling")


async def process_job(page: Page, job: dict[str, Any], profile: dict[str, Any], files: dict[str, Optional[Path]],
                      status: StatusFile) -> dict[str, Any]:
  """One tab: open, fill what the profile answers, highlight the rest, add the checklist. Never submits."""
  job_id: str = job["job_id"]
  clicked: asyncio.Event = asyncio.Event()
  await page.expose_function("bullpenContinue", clicked.set)  # the banner's Continue button calls this
  try:
    await status.update(job_id, status="opening")
    await page.goto(job["apply_url"], wait_until="domcontentloaded")
    await status.update(job_id, status="filling")
    values: dict[str, Any] = fill.profile_values(profile)
    if fill.is_workday(job["apply_url"]):
      result: dict[str, Any] = await fill.fill_workday(
        page, values, files, lambda: wait_for_signin(page, job_id, status, clicked))
    else:
      if await fill.signin_visible(page):
        await wait_for_signin(page, job_id, status, clicked)
      result = await fill.fill_generic(page, values, files)
    needs_you: list[str] = await panel.inject_panel(page, job, result)
    await status.update(job_id, status="ready_for_review", filled_count=result["filled"], needs_you=needs_you)
    return result
  except Exception as exc:  # one broken posting must not take down the other tabs; the tab stays open
    await status.update(job_id, status="error", error=f"{type(exc).__name__}: {exc}"[:300])
    return {"filled": 0, "needs_you": [], "error": exc}


async def open_tabs(jobs: list[dict[str, Any]], profile: dict[str, Any], files: list[dict[str, Optional[Path]]],
                    status: StatusFile) -> None:
  async with async_playwright() as pw:
    context: BrowserContext = await pw.chromium.launch_persistent_context(
      user_data_dir=str(BROWSER_PROFILE), headless=False, no_viewport=True)
    pages: list[Page] = list(context.pages[:1])
    while len(pages) < len(jobs):
      pages.append(await context.new_page())
    await asyncio.gather(*(process_job(p, j, profile, f, status) for p, j, f in zip(pages, jobs, files)))
    print(f"Opened {len(jobs)} tab(s). Review and submit each one yourself, then close the browser.", flush=True)
    await context.wait_for_event("close", timeout=0)


async def run(backend: str) -> None:
  async with httpx.AsyncClient(base_url=backend, timeout=30) as client:
    profile_res: httpx.Response = await client.get("/profile/current")
    profile_res.raise_for_status()
    queue: list[dict[str, Any]] = (await client.get("/queue")).json()
    files: list[dict[str, Optional[Path]]] = [await download_documents(client, job) for job in queue]
  if not queue:
    print("Queue is empty. Queue some jobs first.")
    return
  status: StatusFile = StatusFile()
  for job in queue:
    await status.update(job["job_id"], status="opening")
  await open_tabs(queue, profile_res.json(), files, status)


def mock_files(folder: Path) -> dict[str, Optional[Path]]:
  """Two tiny placeholder PDFs so the mock run exercises the uploads."""
  folder.mkdir(parents=True, exist_ok=True)
  out: dict[str, Optional[Path]] = {}
  for key in ("resume", "cover_letter"):
    path: Path = folder / f"{key}.pdf"
    path.write_bytes(b"%PDF-1.4\n%BullPen mock\n")
    out[key] = path
  return out


async def run_mock(signin: bool, mock_url: Optional[str]) -> None:
  """No backend: the mock Workday page (or mock_url, e.g. the React one), a fake profile, placeholder PDFs."""
  profile: dict[str, Any] = json.loads((MOCK_DIR / "fake_profile.json").read_text(encoding="utf-8"))
  url: str = (mock_url or (MOCK_DIR / "workday_mock.html").as_uri()) + ("?signin=1" if signin else "")
  job: dict[str, Any] = {"job_id": "mock", "title": "Software Engineering Intern", "company": "BullPen Test Co",
                         "apply_url": url}
  await open_tabs([job], profile, [mock_files(TMP_DIR / "mock")], StatusFile())


def main() -> None:
  parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--backend", default="http://localhost:8000")
  parser.add_argument("--mock", action="store_true", help="fill mock/workday_mock.html with mock/fake_profile.json")
  parser.add_argument("--signin", action="store_true", help="with --mock: show the sign-in page first")
  parser.add_argument("--mock-url", help="with --mock: fill this page instead, e.g. http://localhost:5173/mock-workday/demo")
  args: argparse.Namespace = parser.parse_args()
  asyncio.run(run_mock(args.signin, args.mock_url) if args.mock else run(args.backend.rstrip("/")))


if __name__ == "__main__":
  main()
