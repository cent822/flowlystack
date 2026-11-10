import sqlite3
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, offset INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, project TEXT, cwd TEXT, title TEXT, entrypoint TEXT, version TEXT,
  first_ts REAL, last_ts REAL, cost_usd REAL DEFAULT 0
);
-- one row per assistant API message (deduped by message id; streaming repeats overwrite)
CREATE TABLE IF NOT EXISTS messages (
  session_id TEXT NOT NULL, msg_id TEXT NOT NULL, ts REAL NOT NULL, model TEXT,
  sidechain INTEGER DEFAULT 0,
  input INTEGER DEFAULT 0, output INTEGER DEFAULT 0,
  cache_read INTEGER DEFAULT 0, cache_create INTEGER DEFAULT 0, thinking INTEGER DEFAULT 0,
  PRIMARY KEY (session_id, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE TABLE IF NOT EXISTS prompts (uuid TEXT PRIMARY KEY, session_id TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS tool_calls (id TEXT PRIMARY KEY, session_id TEXT, ts REAL, name TEXT);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con
