"""Regenerate MOCK_FIELDS.md from workday_fields.json: python make_mock_fields.py"""
import json
from pathlib import Path
from typing import Any

HERE: Path = Path(__file__).resolve().parent
PAGE_NAMES: dict[str, str] = {"posting": "Posting", "signin": "Sign in", "my_information": "1. My Information",
                              "my_experience": "2. My Experience", "review": "3. Review", "all": "All"}


def _status(item: dict[str, Any]) -> str:
  if item.get("mock_only"):
    return "mock only"
  return "verified" if item.get("verified") else "provisional"


def render(spec: dict[str, Any]) -> str:
  lines: list[str] = [
    "# Mock Workday fields",
    "",
    "Generated from `workday_fields.json` by `python make_mock_fields.py`. Don't edit by hand.",
    "",
    "The React `/mock-workday/:jobId` page must use these exact `data-automation-id` values, the same page order",
    "(Posting -> Apply modal -> optional Sign in -> My Information -> My Experience -> Review), and the same widget",
    "behavior as `apply_worker/mock/workday_mock.html`:",
    "",
    "- **text / textarea**: a plain `<input type=text>` / `<textarea>` with the id on the input.",
    "- **dropdown**: a `<button>` with the id that shows `Select One`. Clicking it opens the next sibling",
    "  `<ul role=listbox>` with `<li role=option>` items. Picking one sets the button text to the option text.",
    "  Escape closes an open listbox.",
    "- **Button texts must match exactly** (the worker only clicks allowlisted texts): `Apply`, `Apply Manually`,",
    "  `Save and Continue`, `Add`. The Review page's button must say `Submit` (the worker refuses it).",
    "- **checkbox**: an `<input type=checkbox>` with the id.",
    "- **date**: a wrapper with the id containing two inputs: `dateSectionMonth-input` (MM) and",
    "  `dateSectionYear-input` (YYYY).",
    "- **file**: one `<input type=file multiple>`. The worker uploads the resume and cover letter PDFs together.",
    "- Required fields have `aria-required=\"true\"`.",
    "- The current step in the progress bar has `data-automation-id=\"progressBarActiveStep\"` and its text is the",
    "  page name. The footer button `bottom-navigation-next-button` reads `Save and Continue` on pages 1-2 and",
    "  `Submit` on Review. The worker never clicks it on page 2 or later.",
    "- Work experience and education rows are added with the `add-button` inside each section. Each row is wrapped",
    "  in `workExperience-N` / `education-N` (N starts at 1).",
    "",
    "Status: **provisional** = a standard Workday id, to be checked on a live posting in W3. **mock only** = real",
    "Workday generates these per company (the worker matches them by question text).",
    "",
    "## Fields the worker fills",
    "",
    "| data-automation-id | Field | Input type | Page | Section | Required | Status |",
    "|---|---|---|---|---|---|---|",
  ]
  groups: dict[str, Any] = spec["groups"]
  for f in spec["fields"]:
    section: str = groups[f["group"]]["section"] + " > " + groups[f["group"]]["entry_prefix"] + "N" if f.get("group") else ""
    lines.append(f"| `{f['automation_id']}` | {f['label']} | {f['type']} | {PAGE_NAMES[f['page']]} | {section} | "
                 f"{'yes' if f.get('required') else 'no'} | {_status(f)} |")
  lines += ["", f"## Voluntary disclosures (never filled, inside `{spec['voluntary']['section']}`)", "",
            "| data-automation-id | Field | Input type | Page | Status |", "|---|---|---|---|---|"]
  for f in spec["voluntary"]["fields"]:
    lines.append(f"| `{f['automation_id']}` | {f['label']} | {f['type']} | {PAGE_NAMES[f['page']]} | {_status(f)} |")
  lines += ["", "## Buttons", "", "| data-automation-id | Text | Status |", "|---|---|---|"]
  for b in spec["buttons"].values():
    lines.append(f"| `{b['automation_id']}` | {b['text']} | {_status(b)} |")
  lines += ["", "## Other ids", "", "| data-automation-id | Purpose | Page |", "|---|---|---|"]
  for name in (spec["current_step"], spec["date_parts"]["month"], spec["date_parts"]["year"]):
    lines.append(f"| `{name}` | see widget rules above | {PAGE_NAMES['all']} |")
  for g in groups.values():
    lines.append(f"| `{g['section']}` | section wrapper, rows are `{g['entry_prefix']}N` | {PAGE_NAMES['my_experience']} |")
  for o in spec["other_mock_ids"]:
    lines.append(f"| `{o['automation_id']}` | {o['label']} | {PAGE_NAMES[o['page']]} |")
  lines.append("")
  return "\n".join(lines)


if __name__ == "__main__":
  spec: dict[str, Any] = json.loads((HERE / "workday_fields.json").read_text(encoding="utf-8"))
  (HERE / "MOCK_FIELDS.md").write_text(render(spec), encoding="utf-8")
  print("wrote MOCK_FIELDS.md")
