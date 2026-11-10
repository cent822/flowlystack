import sqlite3

from ...config import OLLAMA_DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
-- one row per Open WebUI answer that carries Ollama's counters (keyed by Open WebUI's message id)
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, ts REAL NOT NULL, model TEXT,
  input INTEGER DEFAULT 0, output INTEGER DEFAULT 0, eval_ns INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_calls_ts ON calls(ts);
CREATE INDEX IF NOT EXISTS idx_calls_chat ON calls(chat_id);
CREATE TABLE IF NOT EXISTS prompts (id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT);
"""


def open_webui(path) -> sqlite3.Connection:
    """Open Open WebUI's webui.db for reading only (the one place both readers use). Normally mode=ro. A cleanly stopped Open WebUI leaves no
    -shm file, and a read-only mount (Docker) cannot create one, so mode=ro then fails with "unable to open database file": read the file
    as it is (immutable) instead. That fallback is safe here because with no -shm nobody has the database open."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        con.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        return con
    except sqlite3.OperationalError:
        return sqlite3.connect(f"file:{path}?immutable=1", uri=True, timeout=5)


def connect() -> sqlite3.Connection:
    OLLAMA_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OLLAMA_DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con
