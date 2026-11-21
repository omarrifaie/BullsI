"""M4: LaTeX escaping, template rendering, and a real tectonic compile."""
import copy
from pathlib import Path
from typing import Any

import pytest

from agents import tailor as tailor_agent
from conftest import fake_tailor_output
from fake_data import FAKE_PROFILE
from latex.escape import escape_latex
from latex.render import LatexError, compile_pdf, render, tectonic_path

needs_tectonic = pytest.mark.skipif(tectonic_path() is None, reason="tectonic not on PATH / TECTONIC_PATH")


@pytest.mark.parametrize("raw,escaped", [
  ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
  ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
  ("\\", r"\textbackslash{}"),
])
def test_escapes_each_special_character(raw: str, escaped: str) -> None:
  assert escape_latex(raw) == escaped


def test_escape_is_single_pass_and_keeps_plain_text() -> None:
  assert escape_latex(r"C:\{x}") == r"C:\textbackslash{}\{x\}"  # braces from \textbackslash{} not re-escaped
  assert escape_latex("Cut costs 30% & saved $5k for R&D_team #1 ~2^3") == \
    r"Cut costs 30\% \& saved \$5k for R\&D\_team \#1 \textasciitilde{}2\textasciicircum{}3"
  assert escape_latex("Plain résumé text, ok.") == "Plain résumé text, ok."


def _hostile_profile() -> dict[str, Any]:
  p: dict[str, Any] = copy.deepcopy(FAKE_PROFILE)
  p["name"] = r"Alex_{Rivera} \input{/etc/passwd}"
  p["skills"] = ["C#", "R&D", "100%", "$HOME", "a_b", "{x}", "~", "^", "\\"]
  return p


def test_templates_escape_every_inserted_string() -> None:
  out: tailor_agent.TailorOutput = fake_tailor_output()
  tex: str = render("resume.tex.j2", tailor_agent.resume_context(_hostile_profile(), out))
  assert r"\input{/etc/passwd}" not in tex
  assert r"Alex\_\{Rivera\} \textbackslash{}input\{/etc/passwd\}" in tex
  assert r"C\#, R\&D, 100\%, \$HOME, a\_b, \{x\}" in tex
  assert r"cutting triage time by 30\%" in tex
  cover: str = render("cover_letter.tex.j2",
                      tailor_agent.cover_context(_hostile_profile(), {"company": "A&B", "address": "Tampa, FL",
                                                                      "title": "Intern_1"}, out))
  assert r"A\&B" in cover and r"Intern\_1" in cover and r"role \& excited" in cover


def test_contact_line_never_prints_street() -> None:
  p: dict[str, Any] = {"phone": "", "email": "a@b.c", "address": "4202 E Fowler Ave, Tampa, FL 33620"}
  assert tailor_agent.contact_line(p) == "a@b.c  |  Tampa, FL"


@needs_tectonic
def test_fake_profile_compiles_to_real_pdf(tmp_path: Path) -> None:
  job: dict[str, Any] = {"id": "job_test", "company": "Raymond James & Associates", "address": "St. Petersburg, FL",
                         "title": "Software Engineering Intern"}
  resume, cover = tailor_agent.build_documents(_hostile_profile(), job, fake_tailor_output(), tmp_path)
  for pdf in (resume, cover):
    data: bytes = pdf.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5000


@needs_tectonic
def test_compile_failure_raises_clear_error(tmp_path: Path) -> None:
  with pytest.raises(LatexError, match="LaTeX compile failed for broken"):
    compile_pdf(r"\documentclass{article}\begin{document}\undefinedcommand\end{document}", tmp_path, "broken")
