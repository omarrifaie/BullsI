"""Tailor agent: Gemini picks + lightly rewords existing bullets and writes a cover letter.
Code rejects any bullet id that isn't in the profile, so the resume can never contain invented experience."""
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

import gemini
from latex.render import compile_pdf, render

logger: logging.Logger = logging.getLogger("bullpen.tailor")

MAX_BULLETS: int = 14
MAX_PER_ENTRY: int = 4


class SelectedBullet(BaseModel):
  id: str
  text: str


class TailorOutput(BaseModel):
  bullets: list[SelectedBullet]
  featured_skills: list[str]
  cover_letter_paragraphs: list[str]


class TailorValidationError(ValueError):
  pass


SYSTEM: str = f"""You tailor a student's resume and write a cover letter for one internship.
Resume rules:
- Choose {MAX_BULLETS - 4} to {MAX_BULLETS} bullets from the profile, at most {MAX_PER_ENTRY} per job or project, most relevant first.
- Use ONLY bullet ids that appear in the profile. Never invent experience.
- "text" is a LIGHT rewording of that same bullet: same facts, same numbers, no new tools, metrics, or claims.
- featured_skills: up to 8 skills copied from the profile's skills list that matter most for this job.
Cover letter rules:
- Exactly 3 paragraphs, 60-110 words each, first person, no greeting or sign-off.
- Paragraph 1: the role and why this company. Paragraph 2: 2-3 concrete experiences from the profile.
  Paragraph 3: what the student would contribute and a short close.
- Only use facts from the profile and the posting. You have no job description, so do NOT describe the
  company's products, mission, or industry; refer to it only by name and the role title.
"""


def bullet_index(profile: dict[str, Any]) -> dict[str, str]:
  return {b["id"]: b["text"] for item in profile["experience"] + profile["projects"] for b in item["bullets"]}


def _numbers(text: str) -> set[str]:
  return set(re.findall(r"\d+(?:\.\d+)?", text))


def validate(profile: dict[str, Any], out: TailorOutput) -> TailorOutput:
  """Reject unknown or duplicate bullet ids. Keep only real profile skills. Revert rewrites that add numbers."""
  known: dict[str, str] = bullet_index(profile)
  ids: list[str] = [b.id for b in out.bullets]
  unknown: list[str] = [i for i in ids if i not in known]
  if unknown:
    raise TailorValidationError(f"Unknown bullet ids: {unknown}")
  if len(set(ids)) != len(ids):
    raise TailorValidationError("Duplicate bullet ids")
  if not ids:
    raise TailorValidationError("No bullets selected")
  if len(out.cover_letter_paragraphs) != 3:
    raise TailorValidationError(f"Cover letter has {len(out.cover_letter_paragraphs)} paragraphs, expected 3")
  bullets: list[SelectedBullet] = []
  per_entry: dict[str, int] = {}
  for b in out.bullets:
    entry: str = b.id.split("_")[0]
    if len(bullets) >= MAX_BULLETS or per_entry.get(entry, 0) >= MAX_PER_ENTRY:
      continue
    per_entry[entry] = per_entry.get(entry, 0) + 1
    original: str = known[b.id]
    text: str = b.text.strip() if b.text.strip() and _numbers(b.text) <= _numbers(original) else original
    bullets.append(SelectedBullet(id=b.id, text=text))
  have: dict[str, str] = {s.lower(): s for s in profile["skills"]}
  skills: list[str] = list(dict.fromkeys(have[s.lower()] for s in out.featured_skills if s.lower() in have))
  return TailorOutput(bullets=bullets, featured_skills=skills, cover_letter_paragraphs=out.cover_letter_paragraphs)


def ask_gemini(profile: dict[str, Any], job: dict[str, Any]) -> TailorOutput:
  posting: dict[str, Any] = {
    "title": job["title"], "company": job["company"], "location": job["address"], "skills": job["skills"],
    **{k: v for k, v in (job.get("meta") or {}).items() if k in ("category", "terms", "degrees")},
  }
  slim_profile: dict[str, Any] = {k: profile[k] for k in ("name", "education", "experience", "projects", "skills")}
  prompt: str = f"JOB POSTING:\n{json.dumps(posting)}\n\nPROFILE:\n{json.dumps(slim_profile)}"
  return gemini.generate_json([prompt], TailorOutput, system=SYSTEM)


def tailor(profile: dict[str, Any], job: dict[str, Any], attempts: int = 2) -> TailorOutput:
  """Ask Gemini, validate; retry once if it invents ids or breaks the format."""
  last_error: Optional[TailorValidationError] = None
  for _ in range(attempts):
    try:
      return validate(profile, ask_gemini(profile, job))
    except TailorValidationError as exc:
      logger.warning("Tailor output rejected for %s: %s", job["id"], exc)
      last_error = exc
  raise last_error or TailorValidationError("Tailor failed")


# ---------- LaTeX context ----------

def contact_line(profile: dict[str, Any]) -> str:
  # City/state only: drop zip codes and any part with digits (street lines) so no street address is printed.
  parts: list[str] = [re.sub(r"\b\d{5}(-\d{4})?\b", "", p).strip() for p in (profile.get("address") or "").split(",")]
  city: str = ", ".join([p for p in parts if p and not re.search(r"\d", p)][-2:])
  return "  |  ".join(p for p in (profile.get("phone"), profile.get("email"), city) if p)


def resume_context(profile: dict[str, Any], out: TailorOutput) -> dict[str, Any]:
  chosen: dict[str, list[str]] = {}
  for b in out.bullets:
    chosen.setdefault(b.id.split("_")[0], []).append(b.text)
  experience: list[dict[str, Any]] = [
    {"title": e["title"], "organization": e["organization"], "location": e.get("location", ""),
     "dates": " -- ".join(d for d in (e.get("start"), e.get("end")) if d), "bullets": chosen[e["id"]]}
    for e in profile["experience"] if e["id"] in chosen
  ]
  projects: list[dict[str, Any]] = [
    {"name": p["name"], "tech": ", ".join(p.get("tech") or []), "bullets": chosen[p["id"]]}
    for p in profile["projects"] if p["id"] in chosen
  ]
  education: list[dict[str, Any]] = [
    {"school": e["school"], "graduation": e.get("graduation", ""),
     "degree_line": ", ".join(x for x in (e.get("degree"), e.get("major")) if x),
     "gpa_line": f"GPA: {e['gpa']}" if e.get("gpa") else ""}
    for e in profile["education"]
  ]
  featured: set[str] = {s.lower() for s in out.featured_skills}
  return {
    "name": profile["name"], "contact_line": contact_line(profile), "education": education,
    "experience": experience, "projects": projects,
    "featured_skills": ", ".join(out.featured_skills),
    "other_skills": ", ".join(s for s in profile["skills"] if s.lower() not in featured),
  }


def cover_context(profile: dict[str, Any], job: dict[str, Any], out: TailorOutput) -> dict[str, Any]:
  return {
    "name": profile["name"], "contact_line": contact_line(profile),
    "date": date.today().strftime("%B %d, %Y").replace(" 0", " "),
    "company": job["company"], "location": job["address"].split(";")[0], "job_title": job["title"],
    "paragraphs": out.cover_letter_paragraphs,
  }


def build_documents(profile: dict[str, Any], job: dict[str, Any], out: TailorOutput, out_dir: Path) -> tuple[Path, Path]:
  resume: Path = compile_pdf(render("resume.tex.j2", resume_context(profile, out)), out_dir, "resume")
  cover: Path = compile_pdf(render("cover_letter.tex.j2", cover_context(profile, job, out)), out_dir, "cover_letter")
  return resume, cover


def run(profile: dict[str, Any], job: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
  return build_documents(profile, job, tailor(profile, job), out_dir)
