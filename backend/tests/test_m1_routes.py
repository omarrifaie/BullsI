"""Every route responds with contract-shaped data (Gemini and network mocked)."""
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents import commute as commute_agent

from models import Commute, Job, Profile

PDF_BYTES: bytes = b"%PDF-1.4\n%fake\n"
PNG_BYTES: bytes = b"\x89PNG\r\n\x1a\nfake"


def _post_profile(client: TestClient) -> dict[str, Any]:
  res = client.post(
    "/profile",
    files={"resume": ("resume.pdf", PDF_BYTES, "application/pdf"),
           "schedule": ("schedule.png", PNG_BYTES, "image/png")},
    data={"name": "Sam Bull", "work_authorization": "needs_sponsorship", "min_pay": "16", "phone_device_type": "Mobile"},
  )
  assert res.status_code == 200, res.text
  return res.json()


def test_profile_form_overrides(client: TestClient) -> None:
  profile: dict[str, Any] = _post_profile(client)
  Profile.model_validate(profile)
  assert profile["name"] == "Sam Bull"
  assert profile["work_authorization"] == "needs_sponsorship"
  assert profile["preferences"]["min_pay"] == 16.0
  assert profile["phone_device_type"] == "Mobile" and profile["how_heard"] == ""
  assert profile["country"] == "United States of America"
  assert profile["id"] == 1


def test_jobs_require_profile(client: TestClient) -> None:
  assert client.get("/jobs?mode=internship").status_code == 400


def test_jobs_match_contract(client: TestClient) -> None:
  _post_profile(client)
  for mode in ("internship", "parttime"):
    jobs: list[dict[str, Any]] = client.get(f"/jobs?mode={mode}").json()
    assert jobs
    scores: list[int] = [j["match"]["score"] for j in jobs]
    assert scores == sorted(scores, reverse=True)
    for job in jobs:
      Job.model_validate(job)
      assert "meta" not in job
      assert job["mode"] == mode
      assert 0 <= job["match"]["score"] <= 100 and job["match"]["reason"]
      if mode == "internship":
        assert job["commute"] is None and job["shifts"] == [] and job["pay"] is None
      else:
        assert job["apply_url"] == f"http://localhost:5173/mock-workday/{job['id']}"
        if job["commute"] is not None:
          Commute.model_validate(job["commute"])
  assert client.get("/jobs?mode=bogus").status_code == 422


def test_commute_route(client: TestClient, fake_routes: list[dict[str, Any]]) -> None:
  profile: dict[str, Any] = _post_profile(client)
  job_id: str = client.get("/jobs?mode=parttime").json()[0]["id"]
  commute: dict[str, Any] = client.get(f"/jobs/{job_id}/commute").json()
  Commute.model_validate(commute)
  assert commute["minutes"] == 25 and commute["car_free"]
  assert fake_routes and all(body["origin"] == {"address": profile["address"]} for body in fake_routes)  # not campus
  assert client.get("/jobs/job_nope/commute").status_code == 404


def test_queue_prepare_serves_pdfs(client: TestClient) -> None:
  _post_profile(client)
  job_id: str = client.get("/jobs?mode=internship").json()[0]["id"]
  assert client.post(f"/queue/{job_id}").json() == {"status": "queued", "job_id": job_id}
  docs: list[dict[str, Any]] = client.post("/prepare").json()["documents"]
  assert [d["job_id"] for d in docs] == [job_id]
  pdf = client.get(docs[0]["resume_url"])
  assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_auto_threshold(client: TestClient) -> None:
  _post_profile(client)
  scores: dict[str, int] = {j["id"]: j["match"]["score"] for j in client.get("/jobs?mode=internship").json()}
  threshold: int = max(scores.values())
  body: dict[str, Any] = client.post(f"/auto?threshold={threshold}").json()
  assert body["queued"] and all(scores[i] >= threshold for i in body["queued"])
  assert len(body["documents"]) == len(body["queued"])


def test_myjob_routes(client: TestClient, fake_routes: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("GEMINI_API_KEY", "test-key")
  monkeypatch.setattr(commute_agent, "answer_missed_bus", lambda message, ctx: f"Next bus for {ctx['employer']}")
  assert client.get("/myjob/today").status_code == 404
  job: dict[str, Any] = {"employer": "Bulls Brew Cafe", "address": "5010 E Fowler Ave, Tampa, FL 33617",
                         "shifts": [{"day": "Tue", "start": "15:00", "end": "21:00"}]}
  assert client.post("/myjob", json=job).json() == {"ok": True}
  today: dict[str, Any] = client.get("/myjob/today").json()
  assert today["employer"] == "Bulls Brew Cafe" and today["minutes"] == 25 and today["leave_by"]
  ics = client.get("/myjob/calendar.ics")
  assert ics.headers["content-type"].startswith("text/calendar") and ics.text.count("BEGIN:VEVENT") == 4
  assert client.post("/chat", json={"message": "I missed the bus"}).json() == {"reply": "Next bus for Bulls Brew Cafe"}


def test_cors_allows_frontend(client: TestClient) -> None:
  res = client.options("/jobs?mode=internship", headers={
    "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
  assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
