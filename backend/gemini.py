"""Thin wrapper: every Gemini call returns JSON validated against a Pydantic model."""
import os
import threading
from typing import Any, Optional, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL: str = "gemini-3.8-flash"  # newest stable Flash per ai.google.dev models page (Nov 2026)
TIMEOUT_MS: int = 90_000  # never let a demo request hang on Gemini
_client: Optional[genai.Client] = None
_client_lock: threading.Lock = threading.Lock()


def model_name() -> str:
  return os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


def client() -> genai.Client:
  """One shared client. Locked: /prepare calls this from several threads, and a client built by a losing
  thread gets garbage-collected and closed mid-request ("client has been closed")."""
  global _client
  with _client_lock:
    if _client is None:
      api_key: Optional[str] = os.environ.get("GEMINI_API_KEY")
      if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set in the repo-root .env")
      _client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    return _client


def generate_json(contents: list[Any], schema: type[T], system: Optional[str] = None,
                  tools: Optional[list[types.Tool]] = None, timeout_ms: Optional[int] = None) -> T:
  response: types.GenerateContentResponse = client().models.generate_content(
    model=model_name(),
    contents=contents,
    config=types.GenerateContentConfig(
      response_mime_type="application/json",
      response_schema=schema,
      system_instruction=system,
      temperature=0.2,
      # Default (high) thinking hit a 504 after ~89s on resume+schedule; LOW finishes in ~13s.
      thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
      tools=tools,
      http_options=types.HttpOptions(timeout=timeout_ms) if timeout_ms else None,
    ),
  )
  return schema.model_validate_json(response.text or "")
