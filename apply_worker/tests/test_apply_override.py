"""BULLPEN_APPLY_URL_OVERRIDE: POST /apply passes --apply-url-override; the worker must open only that URL."""
import asyncio
from pathlib import Path
from typing import Any, Optional

import httpx
import pytest

import apply

OVERRIDE: str = "http://localhost:5173/mock-workday/demo"


def test_override_replaces_every_apply_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
  queue: list[dict[str, Any]] = [
    {"job_id": "j1", "title": "A", "company": "X", "apply_url": "https://x.wd5.myworkdayjobs.com/a",
     "resume_url": None, "cover_letter_url": None},
    {"job_id": "j2", "title": "B", "company": "Y", "apply_url": "https://boards.greenhouse.io/y/1",
     "resume_url": None, "cover_letter_url": None},
  ]

  def backend(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"name": "Alex"} if request.url.path == "/profile/current" else queue)
  real_client = httpx.AsyncClient
  monkeypatch.setattr(apply.httpx, "AsyncClient",
                      lambda **kw: real_client(transport=httpx.MockTransport(backend), **kw))
  real_status = apply.StatusFile
  monkeypatch.setattr(apply, "StatusFile", lambda: real_status(tmp_path / "status.json"))  # not the real status.json
  opened: dict[str, list[str]] = {}

  async def fake_open_tabs(jobs: list[dict[str, Any]], profile: dict[str, Any],
                           files: list[dict[str, Optional[Path]]], status: Any) -> None:
    opened["urls"] = [j["apply_url"] for j in jobs]
  monkeypatch.setattr(apply, "open_tabs", fake_open_tabs)

  asyncio.run(apply.run("http://backend.test", OVERRIDE))
  assert opened["urls"] == [OVERRIDE, OVERRIDE]
  asyncio.run(apply.run("http://backend.test"))  # off by default: the real URLs
  assert opened["urls"] == [q["apply_url"] for q in queue]
