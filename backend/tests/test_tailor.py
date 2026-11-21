"""M4: Tailor validation (no invented experience) and /prepare error isolation."""
import copy
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import gemini
from agents import tailor as tailor_agent
from conftest import fake_tailor_output
from fake_data import FAKE_PROFILE
from latex.render import LatexError
from test_m1_routes import _post_profile

JOB: dict[str, Any] = {"id": "job_x", "title": "Data Intern", "company": "Jabil", "address": "Tampa, FL",
                       "skills": ["SQL"], "meta": {}}


def _out(**changes: Any) -> tailor_agent.TailorOutput:
  return fake_tailor_output().model_copy(update=changes)


def test_rejects_unknown_bullet_id() -> None:
  bad: tailor_agent.TailorOutput = _out(bullets=[
    tailor_agent.SelectedBullet(id="exp1_b1", text="Resolved tickets"),
    tailor_agent.SelectedBullet(id="exp9_b1", text="Led a team of 50 engineers at Google"),
  ])
  with pytest.raises(tailor_agent.TailorValidationError, match="exp9_b1"):
    tailor_agent.validate(FAKE_PROFILE, bad)


def test_rejects_duplicates_and_wrong_paragraph_count() -> None:
  dup: list[tailor_agent.SelectedBullet] = [tailor_agent.SelectedBullet(id="exp1_b1", text="a")] * 2
  with pytest.raises(tailor_agent.TailorValidationError):
    tailor_agent.validate(FAKE_PROFILE, _out(bullets=dup))
  with pytest.raises(tailor_agent.TailorValidationError):
    tailor_agent.validate(FAKE_PROFILE, _out(cover_letter_paragraphs=["only one"]))


def test_reverts_rewrites_that_add_numbers_and_drops_unknown_skills() -> None:
  out: tailor_agent.TailorOutput = tailor_agent.validate(FAKE_PROFILE, _out(bullets=[
    tailor_agent.SelectedBullet(id="exp1_b1", text="Resolved 400+ weekly tickets"),  # 400 not in original
    tailor_agent.SelectedBullet(id="exp1_b2", text="Built a Python auto-tagger that cut triage time 30%"),
  ]))
  assert out.bullets[0].text == FAKE_PROFILE["experience"][0]["bullets"][0]["text"]
  assert out.bullets[1].text == "Built a Python auto-tagger that cut triage time 30%"
  assert out.featured_skills == ["Python", "SQL"]  # "Kubernetes" isn't in the profile


def test_tailor_retries_once_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
  calls: list[int] = []
  bad: tailor_agent.TailorOutput = _out(bullets=[tailor_agent.SelectedBullet(id="nope", text="x")])
  monkeypatch.setattr(tailor_agent, "ask_gemini", lambda *_a: calls.append(1) or bad)
  with pytest.raises(tailor_agent.TailorValidationError):
    tailor_agent.tailor(FAKE_PROFILE, JOB)
  assert len(calls) == 2
  responses: list[tailor_agent.TailorOutput] = [bad, fake_tailor_output()]
  monkeypatch.setattr(tailor_agent, "ask_gemini", lambda *_a: responses.pop(0))
  out, warnings = tailor_agent.tailor(FAKE_PROFILE, JOB)
  assert [b.id for b in out.bullets] == ["exp1_b2", "proj1_b1"] and warnings == []


def test_resume_groups_bullets_under_their_entries() -> None:
  ctx: dict[str, Any] = tailor_agent.resume_context(copy.deepcopy(FAKE_PROFILE), fake_tailor_output())
  assert [e["organization"] for e in ctx["experience"]] == ["USF Information Technology"]
  assert ctx["projects"][0]["bullets"] == ["Built a live campus shuttle map used by 300+ students"]
  assert "Python" not in ctx["other_skills"].split(", ")


def test_gemini_client_is_created_once_across_threads(monkeypatch: pytest.MonkeyPatch) -> None:
  """Regression: concurrent /prepare threads each built a client; the orphan was GC'd and closed mid-request."""
  created: list[object] = []

  class SlowClient:
    def __init__(self, **_kwargs: Any) -> None:
      time.sleep(0.05)
      created.append(self)
  monkeypatch.setattr(gemini, "_client", None)
  monkeypatch.setattr(gemini.genai, "Client", SlowClient)
  monkeypatch.setenv("GEMINI_API_KEY", "test-key")
  with ThreadPoolExecutor(max_workers=8) as pool:
    clients: list[object] = list(pool.map(lambda _i: gemini.client(), range(8)))
  assert len(created) == 1 and all(c is created[0] for c in clients)


def test_prepare_reports_compile_error_without_crashing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
  _post_profile(client)
  ids: list[str] = [j["id"] for j in client.get("/jobs?mode=internship").json()][:2]
  for job_id in ids:
    client.post(f"/queue/{job_id}")

  def flaky_build(profile: dict[str, Any], job: dict[str, Any], out: Any, out_dir: Path) -> Any:
    if job["id"] == ids[0]:
      raise LatexError("LaTeX compile failed for resume: ! Undefined control sequence.")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "resume.pdf").write_bytes(b"%PDF-1.4\n")
    (out_dir / "cover_letter.pdf").write_bytes(b"%PDF-1.4\n")
  monkeypatch.setattr(tailor_agent, "build_documents", flaky_build)
  res = client.post("/prepare")
  assert res.status_code == 200
  docs: dict[str, dict[str, Any]] = {d["job_id"]: d for d in res.json()["documents"]}
  assert docs[ids[0]]["status"] == "error" and "Undefined control sequence" in docs[ids[0]]["error"]
  assert docs[ids[0]]["resume_url"] is None
  assert docs[ids[1]]["status"] == "ready" and docs[ids[1]]["resume_url"].endswith(f"{ids[1]}/resume.pdf")
