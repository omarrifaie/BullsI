"""W2: the worker against the mock Workday page (headless). One test per safety rule / spec item."""
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Optional

import pytest
from playwright.async_api import Page, async_playwright

import apply
import fill
from conftest import HERE, MOCK_URL

VOLUNTARY_IDS: list[str] = ["gender", "ethnicityDropdown", "hispanicOrLatino", "veteranStatus"]


def test_fills_every_mapped_field_and_uploads_both_pdfs(run_mock: Any, profile: dict[str, Any],
                                                        files: dict[str, Optional[Path]]) -> None:
  out: dict[str, Any] = run_mock(profile, files)
  assert "error" not in out["result"], out["result"]
  f: dict[str, Any] = out["state"]["fields"]
  assert f["legalNameSection_firstName"] == "Alex" and f["legalNameSection_lastName"] == "Rivera"
  assert f["addressSection_addressLine1"] == "4202 E Fowler Ave" and f["addressSection_city"] == "Tampa"
  assert f["addressSection_countryRegion"] == "Florida" and f["addressSection_postalCode"] == "33620"
  assert f["email"] == "alexrivera@usf.edu" and f["phone-number"] == "8135550142"
  assert f["workAuthorizationQuestion"] == "Yes" and f["sponsorshipQuestion"] == "No"  # citizen
  assert f["countryDropdown"] == "United States of America" and f["phone-device-type"] == "Mobile"
  assert f["sourcePrompt"] == "Select One"  # how_heard not set in the profile
  assert out["state"]["work"] == {
    "jobTitle": "IT Help Desk Assistant", "company": "USF Information Technology", "location": "Tampa, FL",
    "currentlyWorkHere": True, "formField-startDate": "08/2025", "formField-endDate": "/",
    "description": "- Resolved 40+ weekly student tickets for Wi-Fi, Canvas, and account access issues\n"
                   "- Wrote a Python script that auto-tags tickets, cutting triage time by 30%"}
  assert out["state"]["work2"] is None  # one experience entry -> exactly one Add click
  assert out["state"]["education"] == {
    "school": "University of South Florida", "degree": "Bachelor's Degree", "fieldOfStudy": "Computer Science",
    "gpa": "3.7", "formField-lastYearAttended": "05/2028"}
  assert out["state"]["files"] == ["resume.pdf", "cover_letter.pdf"]
  assert out["status"]["status"] == "ready_for_review" and out["status"]["filled_count"] == out["result"]["filled"] == 24  # 12 + 6 work + 5 education + 1 upload


def test_profile_gaps_stay_blank(run_mock: Any, profile: dict[str, Any], files: dict[str, Optional[Path]]) -> None:
  """No guessing: unset signup answers stay blank, an answer that isn't an option stays blank, and F-1 students
  decide 'authorized to work' themselves."""
  out: dict[str, Any] = run_mock({**profile, "work_authorization": "needs_sponsorship", "country": "",
                                  "phone_device_type": "", "how_heard": "TikTok"}, files)
  f: dict[str, Any] = out["state"]["fields"]
  for field_id in ("countryDropdown", "sourcePrompt", "phone-device-type", "workAuthorizationQuestion"):
    assert f[field_id] == "Select One", field_id
  assert f["sponsorshipQuestion"] == "Yes"


def test_how_heard_is_picked_when_set(run_mock: Any, profile: dict[str, Any],
                                      files: dict[str, Optional[Path]]) -> None:
  out: dict[str, Any] = run_mock({**profile, "how_heard": "career fair"}, files)  # matched case-insensitively
  assert out["state"]["fields"]["sourcePrompt"] == "Career Fair"
  assert out["status"]["needs_you"] == []


def test_voluntary_disclosures_stay_empty(run_mock: Any, profile: dict[str, Any],
                                          files: dict[str, Optional[Path]]) -> None:
  out: dict[str, Any] = run_mock(profile, files)
  f: dict[str, Any] = out["state"]["fields"]
  assert all(f[v] == "Select One" for v in VOLUNTARY_IDS) and f["disabilityStatus"] is False
  assert not [c for c in out["state"]["clicks"] if c in ("Female", "Male", "Asian", "White", "Yes, I have a disability")]
  assert out["result"]["your_choice"] == ["Gender", "Race/Ethnicity", "Are you Hispanic or Latino?", "Veteran Status",
                                          "I have a disability (or previously had a disability)"]
  assert "Your choice" in out["state"]["panelText"]


def test_submit_is_never_clicked(run_mock: Any, profile: dict[str, Any], files: dict[str, Optional[Path]]) -> None:
  out: dict[str, Any] = run_mock(profile, files)
  assert out["state"]["submitClicks"] == 0
  allowed_buttons: set[str] = {"Apply", "Apply Manually", "Save and Continue", "Add"}
  page_buttons: list[str] = [c for c in out["state"]["clicks"] if c in allowed_buttons or re.search("submit", c, re.I)]
  assert page_buttons == ["Apply", "Apply Manually", "Save and Continue", "Add", "Add"]


def test_stops_on_my_experience(run_mock: Any, profile: dict[str, Any], files: dict[str, Optional[Path]]) -> None:
  out: dict[str, Any] = run_mock(profile, files)
  assert out["state"]["step"] == "My Experience"
  assert out["state"]["clicks"].count("Save and Continue") == 1


def test_blanks_are_highlighted_and_listed(run_mock: Any, profile: dict[str, Any],
                                           files: dict[str, Optional[Path]]) -> None:
  no_gpa: dict[str, Any] = {**profile, "education": [{**profile["education"][0], "gpa": ""}]}
  out: dict[str, Any] = run_mock(no_gpa, files)
  state: dict[str, Any] = out["state"]
  assert "gpa" in state["highlighted"] and "Overall Result (GPA)" in state["blanks"]
  assert state["panelLinks"] == ["Overall Result (GPA)"]  # clickable: it's on the page the student is looking at
  for text in ("Filled 23 fields", "My Information: How Did You Hear About Us?",
               "Software Engineering Intern at BullPen Test Co"):
    assert text in state["panelText"], text
  assert out["status"]["needs_you"] == ["Overall Result (GPA)", "My Information: How Did You Hear About Us?"]
  panel: dict[str, float] = state["panelRect"]
  for b in state["pageButtons"]:  # the panel never covers the page's own buttons
    overlaps: bool = b["x"] < panel["x"] + panel["w"] and panel["x"] < b["x"] + b["w"] \
      and b["y"] < panel["y"] + panel["h"] and panel["y"] < b["y"] + b["h"]
    assert not overlaps, b


def test_waits_for_signin_until_continue_is_clicked(run_mock: Any, profile: dict[str, Any],
                                                    files: dict[str, Optional[Path]]) -> None:
  async def student(page: Page, status: apply.StatusFile, task: "asyncio.Task[dict[str, Any]]") -> None:
    banner_continue = page.locator("#bullpen-continue")
    await banner_continue.wait_for(timeout=15_000)
    assert status.jobs["mock"]["status"] == "waiting_for_signin"
    first_name = page.locator('[data-automation-id="legalNameSection_firstName"]')
    await asyncio.sleep(1.0)
    assert not task.done() and await first_name.input_value() == ""
    await page.click('[data-automation-id="signInSubmitButton"]')  # the student signs in...
    await asyncio.sleep(1.0)
    assert not task.done() and await first_name.input_value() == ""  # ...but the worker waits for Continue
    assert status.jobs["mock"]["status"] == "waiting_for_signin"
    await banner_continue.click()

  out: dict[str, Any] = run_mock(profile, files, query="?signin=1", during=student)
  assert out["state"]["fields"]["legalNameSection_firstName"] == "Alex"
  assert out["state"]["password"] == ""  # the worker never typed into the password field
  # Worker: Apply, Apply Manually. Student: Sign In, then the banner's Continue. The worker never clicks Sign In.
  assert out["state"]["clicks"][:4] == ["Apply", "Apply Manually", "Sign In", "Continue"]
  assert out["state"]["clicks"].count("Sign In") == 1
  assert out["status"]["status"] == "ready_for_review"


def test_safe_click_refuses_submit() -> None:
  async def scenario() -> None:
    async with async_playwright() as pw:
      browser = await pw.chromium.launch()
      page: Page = await browser.new_page()
      await page.goto(MOCK_URL)
      for automation_id in ("adventureButton", "applyManually", "bottom-navigation-next-button",
                            "bottom-navigation-next-button"):
        await page.click(f'[data-automation-id="{automation_id}"]')  # the test (not the worker) walks to Review
      submit = page.locator('[data-automation-id="bottom-navigation-next-button"]')
      assert await submit.text_content() == "Submit"
      for allowed in (fill.NEXT_TEXTS, fill.START_TEXTS, {"submit"}):
        with pytest.raises(fill.UnsafeClick):
          await fill.safe_click(submit, allowed)
      assert await page.evaluate("window.__submitClicks") == 0
      await browser.close()
  asyncio.run(scenario())


def test_profile_values_never_guess() -> None:
  v: dict[str, Any] = fill.profile_values({"name": "Prince", "address": "Tampa, FL", "phone": "+1 (813) 555-0142",
                                           "work_authorization": "needs_sponsorship",
                                           "experience": [{"title": "TA", "start": "2024", "end": "May 2025"}],
                                           "education": [{"school": "USF", "degree": "Certificate"}]})
  assert v["first_name"] == "Prince" and v["last_name"] is None
  assert v["address_line1"] is v["city"] is v["state"] is v["postal_code"] is None
  assert v["phone"] == "8135550142" and v["authorized_to_work"] is None and v["needs_sponsorship"] == "Yes"
  assert v["experience"][0]["start"] is None and v["experience"][0]["end"] == ("05", "2025")
  assert v["education"][0]["degree"] is None and v["education"][0]["graduation"] is None


GENERIC_FORM: str = """<form>
  <label for="fn">First Name *</label><input id="fn" type="text" required>
  <label for="ln">Last Name *</label><input id="ln" type="text" required>
  <label for="em">Email *</label><input id="em" type="email" required>
  <label for="ph">Phone</label><input id="ph" type="tel">
  <label for="li">LinkedIn Profile *</label><input id="li" type="text" required>
  <div class="field"><span>Resume/CV</span><input id="resume" type="file"></div>
  <div class="field"><span>Cover Letter</span><input id="cover" type="file"></div>
  <label for="g">Gender</label><select id="g"><option value=""></option><option>Female</option></select>
  <button type="submit">Submit Application</button>
</form>"""


def test_generic_page_fills_by_label(files: dict[str, Optional[Path]], profile: dict[str, Any]) -> None:
  async def scenario() -> dict[str, Any]:
    async with async_playwright() as pw:
      browser = await pw.chromium.launch()
      page: Page = await browser.new_page()
      await page.set_content(GENERIC_FORM)
      result: dict[str, Any] = await fill.fill_generic(page, fill.profile_values(profile), files)
      needs: list[str] = await apply.panel.inject_panel(page, {"title": "Intern", "company": "Acme"}, result)
      state: dict[str, Any] = await page.evaluate("""() => ({
        values: [...document.querySelectorAll('input:not([type=file]), select')].map(e => e.value),
        files: [...document.querySelectorAll('input[type=file]')].map(e => e.files[0]?.name || null),
        highlighted: [...document.querySelectorAll('.bullpen-needs')].map(e => e.id)})""")
      await browser.close()
      return {"result": result, "needs": needs, **state}
  out: dict[str, Any] = asyncio.run(scenario())
  assert out["values"] == ["Alex", "Rivera", "alexrivera@usf.edu", "(813) 555-0142", "", ""]
  assert out["files"] == ["resume.pdf", "cover_letter.pdf"] and out["result"]["filled"] == 6
  assert out["highlighted"] == ["li"] and out["needs"] == ["LinkedIn Profile"]
  assert out["result"]["your_choice"] == ["Gender"]


def test_mock_and_spec_use_the_same_ids() -> None:
  spec: dict[str, Any] = json.loads((HERE / "workday_fields.json").read_text(encoding="utf-8"))
  html: str = (HERE / "mock" / "workday_mock.html").read_text(encoding="utf-8")
  md: str = (HERE / "MOCK_FIELDS.md").read_text(encoding="utf-8")
  ids: list[str] = [f["automation_id"] for f in spec["fields"] + spec["voluntary"]["fields"] + spec["other_mock_ids"]]
  ids += [b["automation_id"] for b in spec["buttons"].values()] + [g["section"] for g in spec["groups"].values()]
  ids += list(spec["date_parts"].values()) + [spec["current_step"]]
  assert [i for i in ids if f'"{i}"' not in html] == []
  react: str = (HERE.parent / "frontend" / "src" / "pages" / "MockWorkday.jsx").read_text(encoding="utf-8")
  assert [i for i in ids if f'"{i}"' not in react] == []
  assert [i for i in ids if f"`{i}`" not in md] == []
