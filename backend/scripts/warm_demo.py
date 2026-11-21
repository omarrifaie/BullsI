"""Warm every demo path for the current profile so judging clicks are served from cache.

Run from backend/ with the server already up:
  .venv\\Scripts\\python scripts\\warm_demo.py            (BULLPEN_URL defaults to http://localhost:8000)
"""
import os
import sys
import time
from typing import Any

import httpx

BASE_URL: str = os.environ.get("BULLPEN_URL", "http://localhost:8000")
TOP_N: int = 3


def call(client: httpx.Client, method: str, path: str) -> Any:
  start: float = time.monotonic()
  res: httpx.Response = client.request(method, path)
  print(f"  {method:<4} {path:<28} {res.status_code}  {time.monotonic() - start:5.1f}s")
  res.raise_for_status()
  return res.json()


def main() -> int:
  with httpx.Client(base_url=BASE_URL, timeout=300) as client:
    try:
      health: dict[str, Any] = call(client, "GET", "/health")
    except httpx.HTTPError as exc:
      print(f"Backend not reachable at {BASE_URL}: {type(exc).__name__}. Start uvicorn first.")
      return 1
    if health["profile_id"] is None:
      print("No profile yet. POST /profile first.")
      return 1
    problems: list[str] = [name for name in ("tectonic", "gemini_key_loaded") if not health[name]]
    if problems:
      print(f"Warning: {', '.join(problems)} not available; PDFs or reasons may fail.")
    print(f"Warming profile {health['profile_id']} at {BASE_URL}")

    internships: list[dict[str, Any]] = call(client, "GET", "/jobs?mode=internship")
    call(client, "GET", "/jobs?mode=parttime")
    top: list[dict[str, Any]] = internships[:TOP_N]
    for job in top:
      call(client, "POST", f"/queue/{job['id']}")
    docs: list[dict[str, Any]] = call(client, "POST", "/prepare")["documents"]
    # Second pass proves the demo path is cached end to end.
    call(client, "GET", "/jobs?mode=internship")
    call(client, "POST", "/prepare")

  by_id: dict[str, dict[str, Any]] = {j["id"]: j for j in internships}
  print()
  print(f"{'job':<46} {'score':>5}  {'status':<6} {'cached':<6} warnings")
  print("-" * 100)
  for doc in docs:
    job: dict[str, Any] = by_id.get(doc["job_id"], {})
    label: str = f"{job.get('title', doc['job_id'])} @ {job.get('company', '?')}"[:46]
    score: Any = job.get("match", {}).get("score", "-")
    notes: str = "; ".join(doc["warnings"]) or (doc["error"] or "")
    print(f"{label:<46} {score:>5}  {doc['status']:<6} {str(doc['cached']):<6} {notes}")
  failed: int = sum(1 for d in docs if d["status"] != "ready")
  print(f"\n{len(docs) - failed}/{len(docs)} ready. Top {TOP_N} queued: {', '.join(j['id'] for j in top)}")
  return 1 if failed else 0


if __name__ == "__main__":
  sys.exit(main())
