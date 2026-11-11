import sqlite3

from ...config import CODEX_DB_PATH

PARSER_VERSION = 2   # 2: typed prompts also come from current Codex's UserMessage items (see promptstore.codex_typed_text)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, offset INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, project TEXT, cwd TEXT, title TEXT, originator TEXT, version TEXT, model TEXT,
  first_ts REAL, last_ts REAL
);
-- one row per distinct running total in a rollout (Codex repeats token_count events; repeats are dropped)
CREATE TABLE IF NOT EXISTS turns (
  session_id TEXT NOT NULL, total INTEGER NOT NULL, ts REAL NOT NULL, model TEXT,
  input INTEGER DEFAULT 0, cached INTEGER DEFAULT 0, output INTEGER DEFAULT 0, reasoning INTEGER DEFAULT 0,
  window INTEGER,
  PRIMARY KEY (session_id, total)
);
CREATE INDEX IF NOT EXISTS idx_turns_ts ON turns(ts);
CREATE TABLE IF NOT EXISTS prompts (id TEXT PRIMARY KEY, session_id TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS tool_calls (id TEXT PRIMARY KEY, session_id TEXT, ts REAL, name TEXT);
-- the newest rate_limits Codex reported (one row)
CREATE TABLE IF NOT EXISTS limits (
  id INTEGER PRIMARY KEY CHECK (id = 1), ts REAL, plan TEXT,
  p_used REAL, p_resets REAL, p_minutes INTEGER, s_used REAL, s_resets REAL, s_minutes INTEGER
);
"""


def connect() -> sqlite3.Connection:
    CODEX_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(CODEX_DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    if con.execute("PRAGMA user_version").fetchone()[0] < PARSER_VERSION:
        # The reader learned a new file format: forget how far each rollout was read so every file is read again once.
        # Every table is written with INSERT OR IGNORE / guarded updates, so reading twice changes nothing but what was missed.
        con.execute("DELETE FROM files")
        con.execute(f"PRAGMA user_version = {PARSER_VERSION}")
        con.commit()
    return con
