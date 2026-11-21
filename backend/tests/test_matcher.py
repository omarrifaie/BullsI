"""M3: Scout selection, Matcher gates, score bounds, reasons."""
import copy
import itertools
from typing import Any

import pytest

from agents import matcher, scout
from conftest import NOW, RAW_LISTINGS, raw_listing
from fake_data import FAKE_PROFILE


def _profile(**overrides: Any) -> dict[str, Any]:
  p: dict[str, Any] = copy.deepcopy(FAKE_PROFILE)
  p.update(overrides)
  return p


def _parttime(shifts: list[dict[str, str]], **extra: Any) -> dict[str, Any]:
  return {"id": "job_pt_test", "mode": "parttime", "title": "Barista", "company": "Cafe", "address": "Tampa, FL",
          "lat": 28.07, "lng": -82.42, "apply_url": "", "shifts": shifts, "pay": 15.0,
          "skills": ["customer service"], "match": None, "commute": None, **extra}


@pytest.fixture(autouse=True)
def no_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setattr(matcher, "write_reasons", lambda *_args: {})


# ---------- gates ----------

@pytest.mark.parametrize("auth,sponsorship,visible", [
  ("citizen", "U.S. Citizenship is Required", True),
  ("permanent_resident", "U.S. Citizenship is Required", False),
  ("needs_sponsorship", "U.S. Citizenship is Required", False),
  ("needs_sponsorship", "Does Not Offer Sponsorship", False),
  ("permanent_resident", "Does Not Offer Sponsorship", True),
  ("needs_sponsorship", "Offers Sponsorship", True),
  ("needs_sponsorship", "Other", True),
])
def test_work_auth_gate_hides_mismatch(auth: str, sponsorship: str, visible: bool) -> None:
  job: dict[str, Any] = scout.normalize(raw_listing("ffffffff-1", "Software Intern", "X", ["Tampa, FL"],
                                                    sponsorship=sponsorship))
  ranked: list[dict[str, Any]] = matcher.rank(_profile(work_authorization=auth), [job], now=NOW)
  assert (len(ranked) == 1) is visible


# Profile classes: Mon/Wed 09:30-10:45, Tue/Thu 11:00-12:15 -> Tue busy 10:30-12:45 with buffer.
@pytest.mark.parametrize("shift,visible", [
  ({"day": "Tue", "start": "11:30", "end": "14:00"}, False),  # direct overlap with class
  ({"day": "Tue", "start": "12:30", "end": "16:00"}, False),  # starts inside 30-min after-class buffer
  ({"day": "Tue", "start": "08:00", "end": "10:45"}, False),  # ends inside 30-min before-class buffer
  ({"day": "Tue", "start": "12:45", "end": "18:00"}, True),   # starts exactly when the buffer ends
  ({"day": "Tue", "start": "07:00", "end": "10:30"}, True),   # ends exactly when the buffer starts
  ({"day": "Fri", "start": "09:00", "end": "17:00"}, True),   # no class that day
])
def test_schedule_gate_with_30_min_buffer(shift: dict[str, str], visible: bool) -> None:
  ranked: list[dict[str, Any]] = matcher.rank(_profile(), [_parttime([shift])], now=NOW)
  assert (len(ranked) == 1) is visible


def test_one_bad_shift_hides_whole_job() -> None:
  shifts: list[dict[str, str]] = [{"day": "Sat", "start": "10:00", "end": "14:00"},
                                  {"day": "Mon", "start": "10:00", "end": "12:00"}]
  assert matcher.rank(_profile(), [_parttime(shifts)], now=NOW) == []


def test_internships_ignore_class_schedule() -> None:
  job: dict[str, Any] = scout.normalize(RAW_LISTINGS[0])
  assert len(matcher.rank(_profile(), [job], now=NOW)) == 1


# ---------- scores ----------

def test_scores_always_between_0_and_100() -> None:
  empty: dict[str, Any] = _profile(skills=[], experience=[], projects=[], class_schedule=[],
                                   education=[{"school": "USF", "graduation": "", "year_in_school": ""}],
                                   preferences={"preferred_cities": [], "min_pay": None})
  rich: dict[str, Any] = _profile(skills=[s for _, ws in scout.TITLE_SKILLS for s in ws] + ["customer service"],
                                  preferences={"preferred_cities": ["Austin, TX"], "min_pay": 1.0})
  internships: list[dict[str, Any]] = [
    scout.normalize(raw_listing(f"a{i}", title, company, locs, days_old=age, degrees=deg, terms=terms))
    for i, (title, company, locs, age, deg, terms) in enumerate(itertools.product(
      ["Data Engineering Intern", "PhD Research Intern", "Barista"], ["Raymond James", "Nobody Inc"],
      [["Tampa, FL"], ["Remote"], ["Austin, TX"], []], [0, 30, 400], [["Bachelor's"], ["PhD"], []],
      [["Summer 2027"], ["Summer 2025"], ["Fall 2030"], ["N/A"]]))
  ]
  parttime: list[dict[str, Any]] = [
    _parttime([{"day": "Sat", "start": "10:00", "end": "14:00"}], lat=lat, lng=-82.41, pay=pay,
              commute=commute, skills=skills)
    for lat, pay, commute, skills in itertools.product(
      [28.06, 28.3, 40.0], [None, 0.0, 7.0, 15.0, 99.0],
      [None, {"minutes": 5, "car_free": True, "transfers": 0, "co2_saved_kg_week": 0, "steps": []},
       {"minutes": 500, "car_free": False, "transfers": 3, "co2_saved_kg_week": 0, "steps": []}],
      [[], ["customer service"], ["rocket surgery"]])
  ]
  for profile in (empty, rich, _profile()):
    ranked: list[dict[str, Any]] = matcher.rank(profile, internships + parttime, now=NOW)
    assert ranked
    for job in ranked:
      assert 0 <= job["match"]["score"] <= 100
      assert isinstance(job["match"]["score"], int)


def test_local_skill_match_outranks_far_mismatch() -> None:
  near: dict[str, Any] = scout.normalize(raw_listing("n1", "Data Engineering Intern", "Raymond James", ["Tampa, FL"]))
  far: dict[str, Any] = scout.normalize(raw_listing("f1", "iOS Mobile Intern", "Nobody Inc", ["Seattle, WA"],
                                                    days_old=50))
  ranked: list[dict[str, Any]] = matcher.rank(_profile(), [far, near], now=NOW)
  assert [j["id"] for j in ranked] == [near["id"], far["id"]]


def test_parttime_commute_uses_teammate_data_when_present() -> None:
  fast: dict[str, Any] = {"minutes": 10, "car_free": True, "transfers": 0, "co2_saved_kg_week": 1, "steps": []}
  slow: dict[str, Any] = {**fast, "minutes": 70}
  shift: list[dict[str, str]] = [{"day": "Sat", "start": "10:00", "end": "14:00"}]
  a, _ = matcher.score_parttime(_profile(), _parttime(shift, commute=fast))
  b, _ = matcher.score_parttime(_profile(), _parttime(shift, commute=slow))
  assert a - b == 25


# ---------- scout ----------

def test_scout_filters_and_keeps_local_listings() -> None:
  old_local: dict[str, Any] = raw_listing("99999999-old", "Software Intern", "Jabil", ["Tampa, FL"], days_old=300)
  newer: list[dict[str, Any]] = [raw_listing(f"n{i}", "Software Intern", "Big Co", ["Austin, TX"]) for i in range(150)]
  selected: list[dict[str, Any]] = scout.select_listings(RAW_LISTINGS + newer + [old_local])
  ids: set[str] = {x["id"] for x in selected}
  assert "99999999-old" in ids                          # old but Tampa -> always kept
  assert "dddddddd-0000-0000-0000-000000000004" not in ids  # Hardware category dropped
  assert "eeeeeeee-0000-0000-0000-000000000005" not in ids  # inactive dropped
  assert sum(1 for x in selected if x["locations"] == ["Austin, TX"]) == 98  # newest 100 = 2 fixture rows + 98 Austin


def test_normalized_job_matches_contract() -> None:
  job: dict[str, Any] = scout.normalize(RAW_LISTINGS[0])
  assert job["id"] == "job_aaaaaaaa"
  assert job["apply_url"] == RAW_LISTINGS[0]["url"]
  assert job["shifts"] == [] and job["pay"] is None and job["commute"] is None
  assert "SQL" in job["skills"]


# ---------- reasons ----------

def test_reasons_over_11_words_fall_back_to_template(monkeypatch: pytest.MonkeyPatch) -> None:
  long: str = "one two three four five six seven eight nine ten eleven twelve"
  assert matcher._clean_reason(long) is None
  assert matcher._clean_reason("Tampa role using your SQL and dbt skills.") == "Tampa role using your SQL and dbt skills"
  jobs: list[dict[str, Any]] = [scout.normalize(x) for x in RAW_LISTINGS[:2]]
  monkeypatch.setattr(matcher, "write_reasons", lambda *_args: {jobs[0]["id"]: "Great local fit"})
  ranked: dict[str, str] = {j["id"]: j["match"]["reason"] for j in matcher.rank(_profile(), jobs, now=NOW)}
  assert ranked[jobs[0]["id"]] == "Great local fit"
  assert ranked[jobs[1]["id"]] and len(ranked[jobs[1]["id"]].split()) < 12  # template fallback


@pytest.mark.parametrize("location,remote", [("Remote", True), ("Remote in USA", True), ("Remote in US", True),
                                             ("Remote in Canada", False), ("Remote in UK", False), ("Tampa, FL", False)])
def test_only_us_remote_counts(location: str, remote: bool) -> None:
  assert matcher._is_us_remote(location) is remote


def test_write_reasons_survives_gemini_error(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.undo()
  def boom(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError("quota")
  monkeypatch.setattr(matcher.gemini, "generate_json", boom)
  job: dict[str, Any] = scout.normalize(RAW_LISTINGS[0])
  assert matcher.write_reasons(_profile(), [(job, {})]) == {}
