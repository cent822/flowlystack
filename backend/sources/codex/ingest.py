"""Incrementally parse ~/.codex rollout files into SQLite (read-only on ~/.codex).

Facts this relies on: cached tokens sit inside
input_tokens, reasoning tokens inside output_tokens, token_count events repeat, the session id is the
uuid in the file name, and repeated session_meta lines belong to the same session.
"""
import json
import os
from datetime import datetime

from ...config import CODEX_HOME


def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _files():
    yield from sorted((CODEX_HOME / "sessions").glob("*/*/*/rollout-*.jsonl"))
    yield from sorted((CODEX_HOME / "archived_sessions").glob("rollout-*.jsonl"))


def _touch(con, sid, **kw):
    con.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
    for k, v in kw.items():
        if v is not None:
            con.execute(f"UPDATE sessions SET {k}=? WHERE id=?", (v, sid))


def _title(text):
    line = (text or "").strip().split("\n", 1)[0].strip()
    return line[:80] or None


def _line(con, o, sid, pos, ts):
    t, pl = o.get("type"), o.get("payload") or {}
    sub = pl.get("type")
    if t == "session_meta":
        cwd = pl.get("cwd")
        _touch(con, sid, cwd=cwd, project=os.path.basename(cwd) if cwd else None,
               originator=pl.get("originator"), version=pl.get("cli_version"))
    elif t == "turn_context":
        cwd = pl.get("cwd")
        _touch(con, sid, model=pl.get("model"), cwd=cwd, project=os.path.basename(cwd) if cwd else None)
    elif t == "event_msg" and sub == "user_message":
        con.execute("INSERT OR IGNORE INTO prompts VALUES(?,?,?)", (f"{sid}:{pos}", sid, ts))
        con.execute("UPDATE sessions SET title=? WHERE id=? AND title IS NULL", (_title(pl.get("message")), sid))
    elif t == "event_msg" and sub == "token_count":
        info = pl.get("info")
        if info:
            tot, last = info["total_token_usage"], info["last_token_usage"]
            model = con.execute("SELECT model FROM sessions WHERE id=?", (sid,)).fetchone()
            con.execute("INSERT OR IGNORE INTO turns VALUES(?,?,?,?,?,?,?,?,?)",
                        (sid, tot.get("total_tokens") or 0, ts, model[0] if model else None,
                         last.get("input_tokens") or 0, last.get("cached_input_tokens") or 0,
                         last.get("output_tokens") or 0, last.get("reasoning_output_tokens") or 0,
                         info.get("model_context_window")))
        rl = pl.get("rate_limits") or {}
        p, s = rl.get("primary") or {}, rl.get("secondary") or {}
        if p:
            con.execute(
                "INSERT INTO limits VALUES(1,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ts=excluded.ts,"
                " plan=excluded.plan, p_used=excluded.p_used, p_resets=excluded.p_resets, p_minutes=excluded.p_minutes,"
                " s_used=excluded.s_used, s_resets=excluded.s_resets, s_minutes=excluded.s_minutes WHERE excluded.ts>=limits.ts",
                (ts, rl.get("plan_type"), p.get("used_percent"), p.get("resets_at"), p.get("window_minutes"),
                 s.get("used_percent"), s.get("resets_at"), s.get("window_minutes")))
    elif t == "response_item" and sub in ("function_call", "custom_tool_call") and pl.get("call_id"):
        con.execute("INSERT OR IGNORE INTO tool_calls VALUES(?,?,?,?)", (pl["call_id"], sid, ts, pl.get("name")))


def scan(con) -> int:
    """Ingest new bytes from every rollout. Returns the number of lines processed."""
    n = 0
    for path in _files():
        key, size = str(path), path.stat().st_size
        row = con.execute("SELECT offset FROM files WHERE path=?", (key,)).fetchone()
        offset = row["offset"] if row else 0
        if offset > size:   # file was rewritten
            offset = 0
        if offset == size:
            continue
        sid = path.stem[-36:]   # rollout-<timestamp>-<uuid>
        lo = hi = None
        with open(path, "rb") as f:
            f.seek(offset)
            while True:
                pos = offset
                line = f.readline()
                if not line or not line.endswith(b"\n"):   # end, or a partial write: retry next scan
                    break
                offset += len(line)
                try:
                    o = json.loads(line)
                    ts = _ts(o.get("timestamp"))
                    _line(con, o, sid, pos, ts) if ts is not None else None
                except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
                    continue
                if ts is not None:
                    lo, hi = min(lo or ts, ts), max(hi or ts, ts)
                n += 1
        if lo is not None:
            con.execute("INSERT OR IGNORE INTO sessions(id) VALUES(?)", (sid,))
            con.execute("UPDATE sessions SET first_ts=MIN(COALESCE(first_ts,?),?), last_ts=MAX(COALESCE(last_ts,?),?) WHERE id=?",
                        (lo, lo, hi, hi, sid))
        con.execute("INSERT OR REPLACE INTO files VALUES(?,?)", (key, offset))
        con.commit()
    return n
