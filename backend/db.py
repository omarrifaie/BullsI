"""Plain sqlite3 storage. One "current profile" = the newest row in profiles."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_DB: Path = Path(__file__).parent / "bullpen.db"

SCHEMA: str = """
CREATE TABLE IF NOT EXISTS profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS queue (
  profile_id INTEGER,
  job_id TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (profile_id, job_id)
);
CREATE TABLE IF NOT EXISTS documents (
  profile_id INTEGER,
  job_id TEXT NOT NULL,
  status TEXT NOT NULL,
  resume_url TEXT,
  cover_letter_url TEXT,
  error TEXT,
  warnings TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (profile_id, job_id)
);
CREATE TABLE IF NOT EXISTS cache (
  key TEXT PRIMARY KEY,
  json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def connect() -> sqlite3.Connection:
  conn: sqlite3.Connection = sqlite3.connect(os.environ.get("BULLPEN_DB", str(DEFAULT_DB)))
  conn.row_factory = sqlite3.Row
  return conn


@contextmanager
def _db() -> Iterator[sqlite3.Connection]:
  """Commit on success, roll back on error, always close (sqlite3's own `with` never closes)."""
  conn: sqlite3.Connection = connect()
  try:
    with conn:
      yield conn
  finally:
    conn.close()


def init_db() -> None:
  with _db() as conn:
    conn.executescript(SCHEMA)
    columns: set[str] = {row["name"] for row in conn.execute("PRAGMA table_info(documents)")}
    if "warnings" not in columns:  # bullpen.db files created before M5
      conn.execute("ALTER TABLE documents ADD COLUMN warnings TEXT")
    myjob_columns: set[str] = {row["name"] for row in conn.execute("PRAGMA table_info(myjob)")}
    if "json" in myjob_columns:  # pre-merge stub schema; teammate B's routes_b.py owns myjob and reads "data"
      conn.execute("ALTER TABLE myjob RENAME COLUMN json TO data")


def save_profile(profile: dict[str, Any]) -> int:
  with _db() as conn:
    cur: sqlite3.Cursor = conn.execute("INSERT INTO profiles (json) VALUES (?)", (json.dumps(profile),))
    return int(cur.lastrowid)


def latest_profile() -> Optional[dict[str, Any]]:
  with _db() as conn:
    row: Optional[sqlite3.Row] = conn.execute("SELECT id, json FROM profiles ORDER BY id DESC LIMIT 1").fetchone()
  if row is None:
    return None
  profile: dict[str, Any] = json.loads(row["json"])
  profile["id"] = row["id"]
  return profile


def add_to_queue(profile_id: Optional[int], job_id: str) -> None:
  with _db() as conn:
    conn.execute("INSERT OR IGNORE INTO queue (profile_id, job_id) VALUES (?, ?)", (profile_id, job_id))


def remove_from_queue(profile_id: Optional[int], job_id: str) -> None:
  with _db() as conn:
    conn.execute("DELETE FROM queue WHERE profile_id IS ? AND job_id = ?", (profile_id, job_id))


def get_queue(profile_id: Optional[int]) -> list[str]:
  with _db() as conn:
    rows: list[sqlite3.Row] = conn.execute(
      "SELECT job_id FROM queue WHERE profile_id IS ? ORDER BY created_at", (profile_id,)
    ).fetchall()
  return [r["job_id"] for r in rows]


def save_document(profile_id: Optional[int], doc: dict[str, Any]) -> None:
  with _db() as conn:
    conn.execute(
      "INSERT OR REPLACE INTO documents (profile_id, job_id, status, resume_url, cover_letter_url, error, warnings)"
      " VALUES (?, ?, ?, ?, ?, ?, ?)",
      (profile_id, doc["job_id"], doc["status"], doc.get("resume_url"), doc.get("cover_letter_url"), doc.get("error"),
       json.dumps(doc.get("warnings") or [])),
    )


def latest_document(job_id: str) -> Optional[dict[str, Any]]:
  """Newest document row for a job across all profiles (files in generated/<job_id>/ belong to this row)."""
  with _db() as conn:
    row: Optional[sqlite3.Row] = conn.execute(
      "SELECT * FROM documents WHERE job_id = ? ORDER BY rowid DESC LIMIT 1", (job_id,)).fetchone()
  if row is None:
    return None
  doc: dict[str, Any] = dict(row)
  doc["warnings"] = json.loads(doc["warnings"] or "[]")
  return doc


def cache_get(key: str) -> Optional[Any]:
  with _db() as conn:
    row: Optional[sqlite3.Row] = conn.execute("SELECT json FROM cache WHERE key = ?", (key,)).fetchone()
  return json.loads(row["json"]) if row else None


def cache_set(key: str, value: Any) -> None:
  with _db() as conn:
    conn.execute("INSERT OR REPLACE INTO cache (key, json) VALUES (?, ?)", (key, json.dumps(value)))

