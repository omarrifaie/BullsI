"""Routes the apply worker reads: /profile/current, /queue, /apply, /apply/status."""
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
from test_m1_routes import _post_profile


def test_profile_current(client: TestClient) -> None:
  assert client.get("/profile/current").status_code == 400
  profile: dict[str, Any] = _post_profile(client)
  assert client.get("/profile/current").json() == profile


def test_queue_lists_apply_url_and_documents(client: TestClient) -> None:
  _post_profile(client)
  internship: dict[str, Any] = client.get("/jobs?mode=internship").json()[0]
  parttime: dict[str, Any] = client.get("/jobs?mode=parttime").json()[0]
  client.post(f"/queue/{internship['id']}")
  client.post(f"/queue/{parttime['id']}")
  client.post("/prepare")
  queue: list[dict[str, Any]] = client.get("/queue").json()
  by_id: dict[str, dict[str, Any]] = {q["job_id"]: q for q in queue}
  assert set(by_id) == {internship["id"], parttime["id"]}
  done: dict[str, Any] = by_id[internship["id"]]
  assert done["apply_url"] == internship["apply_url"] and done["title"] == internship["title"]
  assert done["status"] == "ready" and done["cached"] is True
  assert done["resume_url"].endswith(f"/generated/{internship['id']}/resume.pdf")
  assert done["cover_letter_url"].endswith(f"/generated/{internship['id']}/cover_letter.pdf")
  assert client.get(done["resume_url"]).content.startswith(b"%PDF")
  pt: dict[str, Any] = by_id[parttime["id"]]
  assert pt["status"] == "not_prepared" and pt["resume_url"] is None and pt["warnings"] == [] and pt["cached"] is False


def test_delete_queue_removes_only_that_job(client: TestClient) -> None:
  _post_profile(client)
  first, second = [j["id"] for j in client.get("/jobs?mode=internship").json()[:2]]
  client.post(f"/queue/{first}")
  client.post(f"/queue/{second}")
  assert client.delete(f"/queue/{first}").json() == {"status": "removed", "job_id": first}
  assert [q["job_id"] for q in client.get("/queue").json()] == [second]
  assert client.delete(f"/queue/{first}").status_code == 200  # already gone: still fine


def test_queue_fixes_legacy_absolute_urls(client: TestClient) -> None:
  profile: dict[str, Any] = _post_profile(client)
  job_id: str = client.get("/jobs?mode=internship").json()[0]["id"]
  client.post(f"/queue/{job_id}")
  client.post("/prepare")
  main.db.save_document(profile["id"], {"job_id": job_id, "status": "ready",
                                        "resume_url": f"http://old:8000/generated/{job_id}/resume.pdf",
                                        "cover_letter_url": f"http://old:8000/generated/{job_id}/cover_letter.pdf"})
  item: dict[str, Any] = client.get("/queue").json()[0]
  assert item["resume_url"] == f"http://testserver/generated/{job_id}/resume.pdf"


def test_apply_status_reads_worker_file(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(main, "APPLY_WORKER_DIR", tmp_path)
  assert client.get("/apply/status").json() == {"jobs": []}
  status: dict[str, Any] = {"jobs": [{"job_id": "j1", "status": "filling", "filled_count": 3, "needs_you": ["Phone"]}]}
  (tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")
  assert client.get("/apply/status").json() == status


class FakeProc:
  def __init__(self) -> None:
    self.running: bool = True

  def poll(self) -> Any:
    return None if self.running else 0


def test_apply_starts_worker_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
  calls: list[dict[str, Any]] = []
  proc: FakeProc = FakeProc()

  def fake_popen(args: list[str], cwd: Path) -> FakeProc:
    calls.append({"args": args, "cwd": cwd})
    return proc
  monkeypatch.setattr(main, "_apply_proc", None)
  monkeypatch.setattr(main.subprocess, "Popen", fake_popen)
  assert client.post("/apply").json() == {"status": "started"}
  assert client.post("/apply").json() == {"status": "already_running"}
  proc.running = False
  assert client.post("/apply").json() == {"status": "started"}
  assert len(calls) == 2
  assert calls[0]["args"][1:] == ["apply.py", "--backend", "http://testserver"]
  assert calls[0]["cwd"] == main.APPLY_WORKER_DIR


def test_init_db_migrates_old_myjob_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
  """bullpen.db files from before the person-b merge have myjob(json); teammate B's routes read myjob(data)."""
  import sqlite3
  path: Path = tmp_path / "old.db"
  with sqlite3.connect(path) as conn:
    conn.execute("CREATE TABLE myjob (id INTEGER PRIMARY KEY CHECK (id = 1), json TEXT NOT NULL)")
    conn.execute("INSERT INTO myjob VALUES (1, '{}')")
  monkeypatch.setenv("BULLPEN_DB", str(path))
  main.db.init_db()
  main.db.init_db()  # idempotent
  with sqlite3.connect(path) as conn:
    assert [r[1] for r in conn.execute("PRAGMA table_info(myjob)")] == ["id", "data"]
