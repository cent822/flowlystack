"""Read Ollama usage out of Open WebUI's chat database (read-only; the file is never written).

Ollama keeps no usage history, but Open WebUI stores each answer's `usage` counters (prompt_eval_count, eval_count,
eval_duration) in chat_message. Only counts, timestamps, model ids and chat titles are read: never message content.
Rows whose usage lacks Ollama's counters (llama.cpp or OpenAI-style providers) are skipped.
Answers are keyed by Open WebUI's message id, so a re-read is harmless; a chat deleted later in Open WebUI stays in
this cache until data/ollama.db is deleted.
"""
import json
import sqlite3

from ...config import WEBUI_DIR
from .db import open_webui


def _secs(t):
    """Open WebUI writes epoch seconds, but be safe about milliseconds or nanoseconds."""
    if t is None:
        return None
    t = float(t)
    return t / 1e9 if t > 1e14 else t / 1e3 if t > 1e11 else t


def _usage(raw):
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except (ValueError, TypeError):
        return None
    if isinstance(d, dict) and d.get("eval_count") is not None and d.get("prompt_eval_count") is not None:
        return d
    return None


def _model(m):
    return m.rsplit("/", 1)[-1] if m and "/" in m else m   # a GGUF path shows as its file name


def _stamp():
    """Size and mtime of the db and its WAL: when unchanged there is nothing new to read."""
    out = []
    for n in ("webui.db", "webui.db-wal"):
        try:
            st = (WEBUI_DIR / n).stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return json.dumps(out)


def scan(con) -> int:
    """Pull answers and messages newer than the stored watermark. Returns the number of rows kept."""
    stamp = _stamp()
    st = dict(con.execute("SELECT key, value FROM state").fetchall())
    if st.get("stamp") == stamp:
        return 0
    wm = float(st.get("wm") or 0)
    src = open_webui(WEBUI_DIR / "webui.db")
    try:
        src.execute("PRAGMA query_only=ON")
        rows = src.execute(
            "SELECT id, chat_id, role, model_id, usage, created_at, updated_at FROM chat_message"
            " WHERE role IN ('user','assistant') AND updated_at >= ? ORDER BY updated_at", (wm,)).fetchall()
        n, new_wm, chats = 0, wm, set()
        for mid, chat_id, role, model, usage, created, updated in rows:
            new_wm = max(new_wm, updated or 0)
            ts = _secs(created)
            if ts is None:
                continue
            if role == "user":
                n += con.execute("INSERT OR IGNORE INTO prompts VALUES(?,?,?)", (mid, chat_id, ts)).rowcount
                continue
            u = _usage(usage)
            if not u:
                continue
            con.execute("INSERT OR REPLACE INTO calls VALUES(?,?,?,?,?,?,?)",
                        (mid, chat_id, ts, _model(model), u["prompt_eval_count"] or 0, u["eval_count"] or 0,
                         u.get("eval_duration") or 0))
            chats.add(chat_id)
            n += 1
        ids = sorted(chats)
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            for cid, title in src.execute(f"SELECT id, title FROM chat WHERE id IN ({','.join('?' * len(part))})", part):
                con.execute("INSERT OR REPLACE INTO chats VALUES(?,?)", (cid, title))
    finally:
        src.close()
    con.executemany("INSERT OR REPLACE INTO state VALUES(?,?)", [("wm", str(new_wm)), ("stamp", stamp)])
    con.commit()
    return n
