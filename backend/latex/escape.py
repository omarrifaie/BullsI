"""Escape user/Gemini text for LaTeX. Single regex pass so replacements are never re-escaped."""
import re

REPLACEMENTS: dict[str, str] = {
  "\\": r"\textbackslash{}",
  "&": r"\&",
  "%": r"\%",
  "$": r"\$",
  "#": r"\#",
  "_": r"\_",
  "{": r"\{",
  "}": r"\}",
  "~": r"\textasciitilde{}",
  "^": r"\textasciicircum{}",
}
_PATTERN: re.Pattern[str] = re.compile("|".join(re.escape(ch) for ch in REPLACEMENTS))


def escape_latex(text: str) -> str:
  return _PATTERN.sub(lambda m: REPLACEMENTS[m.group(0)], text)
