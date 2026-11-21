"""Field filling. Workday by data-automation-id (workday_fields.json); other sites by label text.

Safety rules enforced here:
  - safe_click() is the only way a button gets clicked; it refuses anything not on the allowlist, and anything that
    looks like a submit ("Submit", "Send Application", "Apply Now", "Finish").
  - The worker moves My Information -> My Experience and never presses Next on My Experience or later.
  - Password fields and voluntary disclosure questions are never touched.
  - A field the profile has no answer for is left blank and marked (data-bullpen-blank) for the checklist.
"""
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from playwright.async_api import Locator, Page, expect

import panel
from panel import SPEC
PAGE_TIMEOUT_MS: int = 30_000
NEXT_TIMEOUT_MS: int = 15_000

DENY: re.Pattern[str] = re.compile(r"submit|send application|apply now|finish", re.I)
START_TEXTS: set[str] = {"apply"}
MANUAL_TEXTS: set[str] = {"apply manually"}
NEXT_TEXTS: set[str] = {"save and continue", "next", "continue"}
ADD_TEXTS: set[str] = {"add", "add another"}
VOLUNTARY: re.Pattern[str] = re.compile(SPEC["voluntary"]["label_pattern"], re.I)
VOLUNTARY_SECTION: str = SPEC["voluntary"]["section"]
SKIP: str = "__bullpen_skip__"  # intentionally empty (e.g. end date while "I currently work here"); not a "needs you"

MONTHS: dict[str, str] = {m: f"{i:02d}" for i, m in enumerate(
  ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
US_STATES: dict[str, str] = {
  "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
  "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
  "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky",
  "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
  "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
  "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
  "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
  "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
  "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
ADDRESS_RE: re.Pattern[str] = re.compile(
  r"^\s*(?P<line1>\d+[^,]+),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?\s*$")
DEGREE_KEYWORDS: list[tuple[str, str]] = [
  (r"^(b|bachelor)", "bachelor"), (r"^(m|master)", "master"), (r"^(ph|doctor)", "doctor"), (r"^(a|associate)", "associate")]


class UnsafeClick(RuntimeError):
  """The worker was about to click something outside its allowlist. Nothing was clicked."""


def _id(automation_id: str) -> str:
  return f'[data-automation-id="{automation_id}"]'


def _norm(text: str) -> str:
  return " ".join(text.split()).lower()


def is_workday(url: str) -> bool:
  return bool(re.search(r"myworkdayjobs\.com|/mock-workday/|workday_mock\.html", url))


# ---------- profile -> values ----------

def _month_year(text: str) -> Optional[tuple[str, str]]:
  """"Aug 2025" / "August 2025" / "08/2025" / "2025-08" -> ("08", "2025"). Year only or unknown -> None."""
  text = (text or "").strip().lower()
  if m := re.match(r"^([a-z]{3})[a-z]*\.?\s+(\d{4})$", text):
    return (MONTHS[m[1]], m[2]) if m[1] in MONTHS else None
  if m := re.match(r"^(\d{1,2})/(\d{4})$", text):
    return f"{int(m[1]):02d}", m[2]
  if m := re.match(r"^(\d{4})-(\d{1,2})$", text):
    return f"{int(m[2]):02d}", m[1]
  return None


def _degree_keyword(degree: str) -> Optional[str]:
  d: str = (degree or "").strip().lower()
  return next((kw for pattern, kw in DEGREE_KEYWORDS if d and re.match(pattern, d)), None)


def profile_values(profile: dict[str, Any]) -> dict[str, Any]:
  """Flat answers keyed by workday_fields.json profile_field. None = the profile doesn't say, leave it blank."""
  parts: list[str] = (profile.get("name") or "").split()
  address: Optional[re.Match[str]] = ADDRESS_RE.match(profile.get("address") or "")
  digits: str = re.sub(r"\D", "", profile.get("phone") or "")
  if len(digits) == 11 and digits.startswith("1"):
    digits = digits[1:]
  auth: Optional[str] = profile.get("work_authorization")
  experience: list[dict[str, Any]] = []
  for e in profile.get("experience") or []:
    current: bool = (e.get("end") or "").strip().lower() in ("present", "current", "now")
    experience.append({
      "title": e.get("title") or None, "organization": e.get("organization") or None,
      "location": e.get("location") or None, "current": current, "start": _month_year(e.get("start", "")),
      "end": SKIP if current else _month_year(e.get("end", "")),
      "bullets": "\n".join(f"- {b['text']}" for b in e.get("bullets") or []) or None,
    })
  education: list[dict[str, Any]] = [{
    "school": ed.get("school") or None, "degree": _degree_keyword(ed.get("degree", "")),
    "major": ed.get("major") or None, "gpa": ed.get("gpa") or None, "graduation": _month_year(ed.get("graduation", "")),
  } for ed in profile.get("education") or []]
  return {
    "first_name": parts[0] if parts else None,
    "last_name": parts[-1] if len(parts) > 1 else None,
    "full_name": " ".join(parts) or None,
    "address_line1": address["line1"].strip() if address else None,
    "city": address["city"].strip() if address else None,
    "state": US_STATES.get(address["state"]) if address else None,
    "postal_code": address["zip"] if address else None,
    "email": profile.get("email") or None,
    "phone": digits or None,
    "phone_display": profile.get("phone") or None,
    "phone_type": None,  # the profile doesn't say mobile/home
    "country": None,
    "how_heard": None,
    "authorized_to_work": "Yes" if auth in ("citizen", "permanent_resident") else None,  # F-1 etc: student decides
    "needs_sponsorship": {"citizen": "No", "permanent_resident": "No", "needs_sponsorship": "Yes"}.get(auth or ""),
    "experience": experience,
    "education": education,
  }


# ---------- safe actions ----------

async def safe_click(target: Locator, allowed: set[str]) -> None:
  text: str = _norm(await target.text_content() or await target.get_attribute("aria-label") or "")
  if DENY.search(text) or text not in allowed:
    raise UnsafeClick(f"Refusing to click {text!r} (allowed here: {sorted(allowed)})")
  await target.click()


async def _pick_option(page: Page, opener: Locator, matches: Callable[[str], bool]) -> bool:
  """Workday dropdown: click the opener, then the option whose text matches. Only for mapped fields."""
  await opener.click()
  listbox: Locator = page.locator('[role="listbox"]:visible').last
  await listbox.wait_for(timeout=5_000)
  options: Locator = listbox.locator('[role="option"]')
  texts: list[str] = await options.all_text_contents()
  index: Optional[int] = next((i for i, t in enumerate(texts) if matches(t.strip()) and not DENY.search(t)), None)
  if index is None:
    await page.keyboard.press("Escape")
    return False
  await options.nth(index).click()
  return True


def _option_matcher(field: dict[str, Any], value: str) -> Callable[[str], bool]:
  if field["profile_field"].endswith("degree"):
    return lambda text: value in text.lower()
  return lambda text: text.lower() == value.lower()


async def _is_off_limits(loc: Locator) -> bool:
  """Never touch password inputs or anything in / labelled as a voluntary disclosure."""
  return await loc.evaluate(
    """(el, [section, pattern]) => {
      if (el.matches('input[type=password]') || el.querySelector('input[type=password]')) return true;
      if (el.closest(`[data-automation-id="${section}"]`)) return true;
      const label = (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText)
        || el.getAttribute('aria-label') || el.closest('label')?.innerText || '';
      return new RegExp(pattern, 'i').test(label);
    }""", [VOLUNTARY_SECTION, SPEC["voluntary"]["label_pattern"]])


async def mark_blank(loc: Locator, label: str) -> None:
  await loc.evaluate("(el, label) => el.setAttribute('data-bullpen-blank', label)", label)


# ---------- Workday ----------

async def _fill_field(page: Page, scope: Locator | Page, field: dict[str, Any], value: Any,
                      result: dict[str, Any]) -> None:
  loc: Locator = scope.locator(_id(field["automation_id"])).first
  if not await loc.count() and field.get("label_match"):
    loc = scope.get_by_label(re.compile(field["label_match"], re.I)).first
  if not await loc.count() or not await loc.is_visible() or await _is_off_limits(loc):
    return
  kind: str = field["type"]
  if value == SKIP or (kind == "checkbox" and not value):
    return
  if value is None:
    await mark_blank(loc, field["label"])
    return
  if kind in ("text", "textarea"):
    if await loc.input_value():
      return  # already filled (e.g. from the Workday account); leave the student's value alone
    await loc.fill(str(value))
  elif kind == "dropdown":
    if _norm(await loc.text_content() or "") not in ("", "select one"):
      return
    if not await _pick_option(page, loc, _option_matcher(field, value)):
      await mark_blank(loc, field["label"])
      return
  elif kind == "checkbox":
    await loc.check()
  elif kind == "date":
    month, year = value
    await loc.locator(_id(SPEC["date_parts"]["month"])).fill(month)
    await loc.locator(_id(SPEC["date_parts"]["year"])).fill(year)
  result["filled"] += 1


async def _upload(page: Page, files: dict[str, Optional[Path]], result: dict[str, Any]) -> None:
  field: dict[str, Any] = next(f for f in SPEC["fields"] if f["type"] == "file")
  loc: Locator = page.locator(_id(field["automation_id"])).first
  if not await loc.count():
    return
  paths: list[Path] = [p for p in (files.get("resume"), files.get("cover_letter")) if p]
  if paths:
    await loc.set_input_files(paths if await loc.get_attribute("multiple") is not None else paths[:1])
    result["filled"] += 1
  if not files.get("resume"):
    await mark_blank(loc, "Resume")
  elif not files.get("cover_letter"):
    result["needs_you"].append("Cover letter (upload it yourself)")


async def _current_step(page: Page) -> str:
  return _norm(await page.locator(_id(SPEC["current_step"])).first.text_content() or "")


async def _fill_page(page: Page, page_name: str, values: dict[str, Any], result: dict[str, Any]) -> None:
  for field in SPEC["fields"]:
    if field["page"] == page_name and not field.get("group") and field["type"] != "file":
      await _fill_field(page, page, field, values.get(field["profile_field"]), result)


async def _fill_groups(page: Page, values: dict[str, Any], result: dict[str, Any]) -> None:
  for group_name, group in SPEC["groups"].items():
    section: Locator = page.locator(_id(group["section"]))
    if not await section.count():
      continue
    fields: list[dict[str, Any]] = [f for f in SPEC["fields"] if f.get("group") == group_name]
    for i, entry in enumerate(values[group["profile_list"]], start=1):
      row: Locator = section.locator(_id(f"{group['entry_prefix']}{i}"))
      if not await row.count():
        await safe_click(section.locator(_id(SPEC["buttons"]["add"]["automation_id"])).last, ADD_TEXTS)
        await row.wait_for(timeout=PAGE_TIMEOUT_MS)
      for field in fields:
        await _fill_field(page, row, field, entry.get(field["profile_field"].split("].", 1)[1]), result)


async def signin_visible(page: Page) -> bool:
  markers: str = ", ".join([_id(m) for m in SPEC["signin_markers"]] + ["input[type=password]"])
  return await page.locator(f"{markers} >> visible=true").count() > 0


async def fill_workday(page: Page, values: dict[str, Any], files: dict[str, Optional[Path]],
                       on_signin: Callable[[], Awaitable[None]]) -> dict[str, Any]:
  """Posting -> Apply -> Apply Manually -> (sign-in wait) -> My Information -> Next -> My Experience -> stop."""
  result: dict[str, Any] = {"filled": 0, "needs_you": []}
  step: Locator = page.locator(_id(SPEC["current_step"])).first
  signin: Locator = page.locator(", ".join([_id(m) for m in SPEC["signin_markers"]] + ["input[type=password]"]))
  apply_button: Locator = page.locator(_id(SPEC["buttons"]["apply"]["automation_id"])).first
  manual: Locator = page.locator(_id(SPEC["buttons"]["apply_manually"]["automation_id"])).first

  await apply_button.or_(step).or_(signin).first.wait_for(timeout=PAGE_TIMEOUT_MS)
  if await apply_button.is_visible():
    await safe_click(apply_button, START_TEXTS)
    await manual.or_(step).or_(signin).first.wait_for(timeout=PAGE_TIMEOUT_MS)
    if await manual.is_visible():
      await safe_click(manual, MANUAL_TEXTS)
  await step.or_(signin).first.wait_for(timeout=PAGE_TIMEOUT_MS)
  while await signin_visible(page):
    await on_signin()  # waits, without a timeout, for the student's Continue click
  await step.wait_for(timeout=PAGE_TIMEOUT_MS)

  if "my information" in await _current_step(page):
    await _fill_page(page, "my_information", values, result)
    result["earlier_page_needs"] = [item["label"] for item in await panel.collect_needs(page)]
    next_button: Locator = page.locator(_id(SPEC["buttons"]["next"]["automation_id"])).first
    if "my information" in await _current_step(page):  # re-check right before the only Next click
      await safe_click(next_button, NEXT_TEXTS)
      try:
        await expect(step).not_to_contain_text("My Information", timeout=NEXT_TIMEOUT_MS)
      except AssertionError:
        result["earlier_page_needs"] = []  # Workday kept us here (validation errors): the panel shows this page
  if "my experience" in await _current_step(page):
    await _fill_groups(page, values, result)
    await _fill_page(page, "my_experience", values, result)
    await _upload(page, files, result)
  return result


# ---------- other sites (Greenhouse, Lever, ...) ----------

GENERIC_TEXT: list[tuple[str, str]] = [
  ("first_name", r"^\s*first\s*name"), ("last_name", r"^\s*last\s*name"), ("full_name", r"^\s*(full\s*)?name\b"),
  ("email", r"e-?mail"), ("phone_display", r"phone"),
]


async def fill_generic(page: Page, values: dict[str, Any], files: dict[str, Optional[Path]]) -> dict[str, Any]:
  """Name, email, phone by label; resume and cover letter file inputs by nearby text. No clicks at all."""
  result: dict[str, Any] = {"filled": 0, "needs_you": []}
  await page.wait_for_load_state("domcontentloaded")
  done: set[str] = set()
  for key, pattern in GENERIC_TEXT:
    if key == "full_name" and {"first_name", "last_name"} & done:
      continue
    candidates: Locator = page.get_by_label(re.compile(pattern, re.I))
    for i in range(await candidates.count()):
      loc: Locator = candidates.nth(i)
      kind: str = (await loc.get_attribute("type") or "text").lower()
      if kind not in ("text", "email", "tel") or not await loc.is_visible() or not await loc.is_editable():
        continue
      if await _is_off_limits(loc) or await loc.input_value():
        break
      if values.get(key):
        await loc.fill(values[key])
        result["filled"] += 1
        done.add(key)
      break
  wanted: dict[str, re.Pattern[str]] = {"resume": re.compile(r"resume|\bcv\b", re.I),
                                        "cover_letter": re.compile(r"cover", re.I)}
  inputs: Locator = page.locator("input[type=file]")
  for i in range(await inputs.count()):
    loc = inputs.nth(i)
    context: str = await loc.evaluate(
      """el => [el.id, el.name, el.getAttribute('aria-label'),
                (el.closest('label, fieldset, [class*=field], [class*=upload]') || el.parentElement)?.innerText]
               .filter(Boolean).join(' ').slice(0, 300)""")
    for key, pattern in wanted.items():
      if pattern.search(context) and key not in done and files.get(key):
        await loc.set_input_files(files[key])
        result["filled"] += 1
        done.add(key)
        break
  return result

