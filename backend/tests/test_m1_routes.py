"""Every route responds with contract-shaped data (Gemini and network mocked)."""
from typing import Any

from fastapi.testclient import TestClient

from models import Commute, Job, Profile

PDF_BYTES: bytes = b"%PDF-1.4\n%fake\n"
PNG_BYTES: bytes = b"\x89PNG\r\n\x1a\nfake"


def _post_profile(client: TestClient) -> dict[str, Any]:
  res = client.post(
    "/profile",
    files={"resume": ("resume.pdf", PDF_BYTES, "application/pdf"),
           "schedule": ("schedule.png", PNG_BYTES, "image/png")},
    data={"name": "Sam Bull", "work_authorization": "needs_sponsorship", "min_pay": "16"},
  )
  assert res.status_code == 200, res.text
  return res.json()


def test_profile_form_overrides(client: TestClient) -> None:
  profile: dict[str, Any] = _post_profile(client)
  Profile.model_validate(profile)
  assert profile["name"] == "Sam Bull"
  assert profile["work_authorization"] == "needs_sponsorship"
  assert profile["preferences"]["min_pay"] == 16.0
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


def test_commute_stub(client: TestClient) -> None:
  _post_profile(client)
  job_id: str = client.get("/jobs?mode=parttime").json()[0]["id"]
  Commute.model_validate(client.get(f"/jobs/{job_id}/commute").json())
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


def test_teammate_stubs(client: TestClient) -> None:
  _post_profile(client)
  assert client.post("/apply").json() == {"status": "started"}
  job: dict[str, Any] = client.get("/jobs?mode=parttime").json()[0]
  assert client.post("/myjob", json=job).json()["status"] == "saved"
  today: dict[str, Any] = client.get("/myjob/today").json()
  assert today["job"]["id"] == job["id"]
  Commute.model_validate(today["commute"])
  ics = client.get("/myjob/calendar.ics")
  assert ics.headers["content-type"].startswith("text/calendar") and "BEGIN:VEVENT" in ics.text
  assert client.post("/chat", json={"message": "when do I work?"}).json()["reply"]


def test_cors_allows_frontend(client: TestClient) -> None:
  res = client.options("/jobs?mode=internship", headers={
    "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
  assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
