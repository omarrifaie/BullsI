"""Headless runs of the worker against mock/workday_mock.html, or the React page with
--mock-url http://localhost:5173/mock-workday/demo (Vite must be running)."""
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import pytest
from playwright.async_api import Page, async_playwright

HERE: Path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import apply  # noqa: E402

MOCK_URL: str = (HERE / "mock" / "workday_mock.html").as_uri()


def pytest_addoption(parser: pytest.Parser) -> None:
  parser.addoption("--mock-url", default=None, help="run the mock tests against this page instead of the HTML mock")


def pytest_configure(config: pytest.Config) -> None:
  global MOCK_URL  # test modules import MOCK_URL after this runs
  MOCK_URL = config.getoption("--mock-url") or MOCK_URL

# Everything a test wants to know about the mock after the worker is done, read straight from the DOM.
STATE_JS: str = """() => {
  const read = el => !el ? null : el.matches('input[type=checkbox]') ? el.checked
    : el.matches('input, textarea') ? el.value : el.textContent.trim();
  const byId = (id, root = document) => read(root.querySelector(`[data-automation-id="${id}"]`));
  const date = (root, id) => {
    const w = root.querySelector(`[data-automation-id="${id}"]`);
    return byId('dateSectionMonth-input', w) + '/' + byId('dateSectionYear-input', w);
  };
  const row = (id, fields, dates) => {
    const r = document.querySelector(`[data-automation-id="${id}"]`);
    if (!r) return null;
    const out = Object.fromEntries(fields.map(f => [f, byId(f, r)]));
    dates.forEach(d => out[d] = date(r, d));
    return out;
  };
  const singles = ['sourcePrompt', 'countryDropdown', 'legalNameSection_firstName', 'legalNameSection_lastName',
    'addressSection_addressLine1', 'addressSection_city', 'addressSection_countryRegion', 'addressSection_postalCode',
    'email', 'phone-device-type', 'phone-number', 'workAuthorizationQuestion', 'sponsorshipQuestion',
    'gender', 'ethnicityDropdown', 'hispanicOrLatino', 'veteranStatus', 'disabilityStatus'];
  const panel = document.getElementById('bullpen-panel');
  const rect = el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; };
  return {
    fields: Object.fromEntries(singles.map(id => [id, byId(id)])),
    work: row('workExperience-1', ['jobTitle', 'company', 'location', 'currentlyWorkHere', 'description'],
              ['formField-startDate', 'formField-endDate']),
    work2: row('workExperience-2', ['jobTitle'], []),
    education: row('education-1', ['school', 'degree', 'fieldOfStudy', 'gpa'], ['formField-lastYearAttended']),
    files: [...document.querySelector('[data-automation-id="file-upload-input-ref"]').files].map(f => f.name),
    password: document.querySelector('input[type=password]').value,
    step: document.querySelector('[data-automation-id="progressBarActiveStep"]')?.textContent.trim(),
    clicks: window.__clicks,
    submitClicks: window.__submitClicks,
    blanks: [...document.querySelectorAll('[data-bullpen-blank]')].map(el => el.getAttribute('data-bullpen-blank')),
    highlighted: [...document.querySelectorAll('.bullpen-needs')].map(el => el.getAttribute('data-automation-id')),
    panelText: panel ? panel.innerText : null,
    panelLinks: panel ? [...panel.querySelectorAll('.bullpen-needs-item')].map(a => a.textContent) : [],
    panelRect: panel ? rect(panel) : null,
    pageButtons: [...document.querySelectorAll('button')]
      .filter(b => !b.closest('#bullpen-panel') && b.offsetParent !== null).map(b => ({text: b.textContent.trim(), ...rect(b)})),
  };
}"""

During = Callable[[Page, "apply.StatusFile", "asyncio.Task[dict[str, Any]]"], Awaitable[None]]


@pytest.fixture()
def profile() -> dict[str, Any]:
  return json.loads((HERE / "mock" / "fake_profile.json").read_text(encoding="utf-8"))


@pytest.fixture()
def files(tmp_path: Path) -> dict[str, Optional[Path]]:
  return apply.mock_files(tmp_path / "pdfs")


@pytest.fixture()
def run_mock(tmp_path: Path) -> Callable[..., dict[str, Any]]:
  """run_mock(profile, files, query="", during=None) -> {"result", "state", "status"}."""
  def run(profile: dict[str, Any], files: dict[str, Optional[Path]], query: str = "",
          during: Optional[During] = None) -> dict[str, Any]:
    async def scenario() -> dict[str, Any]:
      async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page: Page = await browser.new_page(viewport={"width": 1280, "height": 720})
        status: apply.StatusFile = apply.StatusFile(tmp_path / "status.json")
        job: dict[str, Any] = {"job_id": "mock", "title": "Software Engineering Intern", "company": "BullPen Test Co",
                               "apply_url": MOCK_URL + query}
        task: asyncio.Task[dict[str, Any]] = asyncio.create_task(apply.process_job(page, job, profile, files, status))
        if during:
          await during(page, status, task)
        result: dict[str, Any] = await asyncio.wait_for(task, timeout=60)
        state: dict[str, Any] = await page.evaluate(STATE_JS)
        await browser.close()
        return {"result": result, "state": state, "status": status.jobs["mock"]}
    return asyncio.run(scenario())
  return run
