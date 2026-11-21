"""BullPen apply worker. Opens one visible Chromium tab per queued job, fills what it can, never submits.

Run by hand: .venv\\Scripts\\python apply.py --backend http://localhost:8000
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

HERE: Path = Path(__file__).resolve().parent
STATUS_FILE: Path = HERE / "status.json"
TMP_DIR: Path = HERE / "tmp"
BROWSER_PROFILE: Path = HERE / "browser_profile"


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


async def process_job(page: Page, job: dict[str, Any], files: dict[str, Optional[Path]], status: StatusFile) -> None:
  """One tab. W1: open the posting and mark it ready. Filling comes in W2."""
  try:
    await status.update(job["job_id"], status="opening")
    await page.goto(job["apply_url"], wait_until="domcontentloaded")
    await status.update(job["job_id"], status="ready_for_review")
  except Exception as exc:  # one broken posting must not take down the other tabs
    await status.update(job["job_id"], status="error", error=f"{type(exc).__name__}: {exc}"[:300])


async def run(backend: str) -> None:
  async with httpx.AsyncClient(base_url=backend, timeout=30) as client:
    (await client.get("/profile/current")).raise_for_status()
    queue: list[dict[str, Any]] = (await client.get("/queue")).json()
    files: list[dict[str, Optional[Path]]] = [await download_documents(client, job) for job in queue]
  if not queue:
    print("Queue is empty. Queue some jobs first.")
    return
  status: StatusFile = StatusFile()
  for job in queue:
    await status.update(job["job_id"], status="opening")
  async with async_playwright() as pw:
    context: BrowserContext = await pw.chromium.launch_persistent_context(
      user_data_dir=str(BROWSER_PROFILE), headless=False, no_viewport=True)
    pages: list[Page] = list(context.pages[:1])
    while len(pages) < len(queue):
      pages.append(await context.new_page())
    await asyncio.gather(*(process_job(p, j, f, status) for p, j, f in zip(pages, queue, files)))
    print(f"Opened {len(queue)} tab(s). Review and submit each one yourself, then close the browser.")
    await context.wait_for_event("close", timeout=0)


def main() -> None:
  parser: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--backend", default="http://localhost:8000")
  args: argparse.Namespace = parser.parse_args()
  asyncio.run(run(args.backend.rstrip("/")))


if __name__ == "__main__":
  main()
