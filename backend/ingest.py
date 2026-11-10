"""Incrementally parse ~/.claude/projects/*/*.jsonl into SQLite.

Each file is tailed from its last byte offset, so a re-scan only reads new lines.
"""
import json
import os
from datetime import datetime

from .config import PROJECTS_DIR


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _is_human_prompt(o: dict) -> bool:
    if o.get("isMeta") or o.get("isSidechain"):
        return False
    c = o.get("message", {}).get("content")
    if isinstance(c, str):
        return not c.startswith("<")
    if isinstance(c, list):
        return any(b.get("type") == "text" and not b["text"].startswith("<") for b in c if isinstance(b, dict)) \
            and not any(b.get("type") == "tool_result" for b in c if isinstance(b, dict))
    return False


def _touch_session(con, sid, ts, o):
    cwd = o.get("cwd")
    con.execute(
        """INSERT INTO sessions(id, cwd, project, entrypoint, version, first_ts, last_ts)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             first_ts = MIN(COALESCE(first_ts, excluded.first_ts), COALESCE(excluded.first_ts, first_ts)),
             last_ts = MAX(COALESCE(last_ts, excluded.last_ts), COALESCE(excluded.last_ts, last_ts)),
             cwd = COALESCE(sessions.cwd, excluded.cwd),
             project = COALESCE(sessions.project, excluded.project),
             entrypoint = COALESCE(sessions.entrypoint, excluded.entrypoint),
             version = COALESCE(excluded.version, sessions.version)""",
        (sid, cwd, os.path.basename(cwd) if cwd else None, o.get("entrypoint"), o.get("version"), ts, ts),
    )


def _ingest_line(con, o: dict, fallback_sid: str):
    sid = o.get("sessionId") or fallback_sid
    t = o.get("type")
    ts = _ts(o.get("timestamp"))

    if t in ("custom-title", "agent-name"):
        title = o.get("customTitle") or o.get("agentName")
        if title:
            con.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
            con.execute("UPDATE sessions SET title=? WHERE id=?", (title, sid))
        return
    if t == "cost-state":
        con.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
        con.execute("UPDATE sessions SET cost_usd=? WHERE id=?", (o.get("totalCostUSD") or 0, sid))
        return
    if ts is None or t not in ("assistant", "user"):
        return

    _touch_session(con, sid, ts, o)

    if t == "user":
        if _is_human_prompt(o) and o.get("uuid"):
            con.execute("INSERT OR IGNORE INTO prompts VALUES(?,?,?)", (o["uuid"], sid, ts))
        return

    m = o.get("message", {})
    u = m.get("usage")
    if not u or not m.get("id"):
        return
    model = m.get("model")
    if model == "<synthetic>":
        return
    con.execute(
        "INSERT OR REPLACE INTO messages VALUES(?,?,?,?,?,?,?,?,?,?)",
        (sid, m["id"], ts, model, 1 if o.get("isSidechain") else 0,
         u.get("input_tokens") or 0, u.get("output_tokens") or 0,
         u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0,
         (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
    )
    for b in m.get("content") or []:
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id"):
            con.execute("INSERT OR IGNORE INTO tool_calls VALUES(?,?,?,?)", (b["id"], sid, ts, b.get("name")))


def scan(con) -> int:
    """Ingest new bytes from every transcript. Returns number of lines processed."""
    n = 0
    for path in sorted(PROJECTS_DIR.glob("*/*.jsonl")):
        key = str(path)
        size = path.stat().st_size
        row = con.execute("SELECT offset FROM files WHERE path=?", (key,)).fetchone()
        offset = row["offset"] if row else 0
        if offset > size:   # file was rewritten
            offset = 0
        if offset == size:
            continue
        with open(path, "rb") as f:
            f.seek(offset)
            while True:
                line = f.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):   # partial write, retry next scan
                    break
                offset += len(line)
                try:
                    _ingest_line(con, json.loads(line), path.stem)
                except (json.JSONDecodeError, KeyError, TypeError):
                    continue
                n += 1
        con.execute("INSERT OR REPLACE INTO files VALUES(?,?)", (key, offset))
        con.commit()
    return n
