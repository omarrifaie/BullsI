"""Render .tex.j2 templates with LaTeX-safe Jinja delimiters and compile them with the tectonic CLI."""
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

import jinja2

from latex.escape import escape_latex

logger: logging.Logger = logging.getLogger("bullpen.latex")
TEMPLATE_DIR: Path = Path(__file__).resolve().parent
COMPILE_TIMEOUT_S: int = 300  # first run downloads tectonic's package bundle


class LatexError(RuntimeError):
  pass


def _finalize(value: Any) -> str:
  """Every \\VAR{} output goes through escape_latex, so no user/Gemini text reaches LaTeX raw."""
  return "" if value is None else escape_latex(str(value))


ENV: jinja2.Environment = jinja2.Environment(
  loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
  block_start_string=r"\BLOCK{",
  block_end_string="}",
  variable_start_string=r"\VAR{",
  variable_end_string="}",
  comment_start_string=r"\#{",
  comment_end_string="}",
  trim_blocks=True,
  lstrip_blocks=True,
  autoescape=False,
  undefined=jinja2.StrictUndefined,
  finalize=_finalize,
)


def render(template_name: str, context: dict[str, Any]) -> str:
  return ENV.get_template(template_name).render(**context)


def tectonic_path() -> Optional[str]:
  return os.environ.get("TECTONIC_PATH") or shutil.which("tectonic")


def compile_pdf(tex_source: str, out_dir: Path, stem: str) -> Path:
  """Write <stem>.tex into out_dir and compile it to <stem>.pdf. Raises LatexError with tectonic's output."""
  exe: Optional[str] = tectonic_path()
  if not exe:
    raise LatexError("tectonic not found on PATH (set TECTONIC_PATH in .env)")
  out_dir.mkdir(parents=True, exist_ok=True)
  tex_file: Path = out_dir / f"{stem}.tex"
  tex_file.write_text(tex_source, encoding="utf-8")
  try:
    proc: subprocess.CompletedProcess[str] = subprocess.run(
      [exe, "--chatter", "minimal", "--outdir", str(out_dir), str(tex_file)],
      capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S,
    )
  except subprocess.TimeoutExpired as exc:
    raise LatexError(f"tectonic timed out after {COMPILE_TIMEOUT_S}s") from exc
  pdf: Path = out_dir / f"{stem}.pdf"
  if proc.returncode != 0 or not pdf.exists():
    lines: list[str] = (proc.stderr or proc.stdout).strip().splitlines()
    logger.error("tectonic failed for %s:\n%s", tex_file, "\n".join(lines[-15:]))
    first_error: str = next((ln for ln in lines if ln.startswith("error:")), lines[-1] if lines else "unknown error")
    raise LatexError(f"LaTeX compile failed for {stem}: {first_error}")
  return pdf
