"""Open WebUI prompts: the user messages in `chat_message` of webui.db (read-only), from every chat whatever model answered.

Open WebUI stores message text as a JSON-encoded string, so it is decoded here. A message is keyed by its Open WebUI id
and imported once (a later edit in Open WebUI does not create a second copy). The model shown on a prompt is the one that
answered it. Only text is read: no files, no sources.
"""
import json
import sqlite3

from .. import promptstore
from ..config import WEBUI_DIR
from ..sources.ollama.db import open_webui


def _secs(t):
    t = float(t)
    return t / 1e9 if t > 1e14 else t / 1e3 if t > 1e11 else t


def _text(raw) -> str:
    try:
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except ValueError:
        d = raw
    if isinstance(d, list):   # multimodal content parts: keep the text parts
        d = "\n\n".join(p.get("text", "") for p in d if isinstance(p, dict) and p.get("type") == "text")
    return d.strip() if isinstance(d, str) else ""


def _stamp():
    out = []
    for n in ("webui.db", "webui.db-wal"):
        try:
            s = (WEBUI_DIR / n).stat()
            out.append((s.st_mtime_ns, s.st_size))
        except OSError:
            out.append(None)
    return json.dumps(out)


def pull(st, root) -> int:
    stamp = _stamp()
    if st.get("stamp") == stamp:   # neither the database nor its WAL changed
        return 0
    src = open_webui(WEBUI_DIR / "webui.db")
    n, wm = 0, float(st.get("wm") or 0)
    try:
        src.execute("PRAGMA query_only=ON")
        rows = src.execute(
            "SELECT u.id, u.chat_id, u.content, u.created_at, u.updated_at,"
            " (SELECT a.model_id FROM chat_message a WHERE a.chat_id=u.chat_id AND a.role='assistant'"
            "  AND a.created_at>=u.created_at ORDER BY a.created_at LIMIT 1)"
            " FROM chat_message u WHERE u.role='user' AND u.updated_at>=? ORDER BY u.updated_at", (wm,)).fetchall()
    finally:
        src.close()
    for mid, chat_id, content, created, updated, model in rows:
        wm = max(wm, updated or 0)
        text = _text(content)
        if mid in st["seen"] or not text or created is None:
            continue
        extra = {"agent": "ollama", **({"model": model.rsplit("/", 1)[-1]} if model else {})}
        promptstore.write_prompt(text, _secs(created), chat_id, "", source="sync", root=root, extra=extra)
        st["seen"].add(mid)
        n += 1
    st["wm"], st["stamp"] = wm, stamp
    return n
