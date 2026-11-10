"""Read-side: turn rows into the JSON shapes the dashboard draws."""
import json
import os
import time
from datetime import datetime

from .config import CONFIG, PROJECTS_DIR, SESSIONS_DIR

LOCAL = "'unixepoch','localtime'"
MODEL_WINDOWS = {"claude-sonnet-5": 1_000_000, "claude-opus-5": 1_000_000, "claude-fable": 1_000_000}
BILLABLE = "(input + output + cache_create)"   # cache reads are excluded: they are nearly free


def _window_for(model: str | None, observed_max: int) -> int:
    cw = CONFIG["context_windows"]
    for prefix, size in MODEL_WINDOWS.items():
        if model and model.startswith(prefix):
            return size
    if observed_max > cw["default"]:
        return cw["1m"]
    return cw["default"]


def overview(con):
    now = time.time()
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    sess = lambda since: con.execute("SELECT COUNT(*) FROM sessions WHERE first_ts>=?", (since,)).fetchone()[0]
    tot = con.execute(
        "SELECT COALESCE(SUM(input),0) i, COALESCE(SUM(output),0) o, COALESCE(SUM(cache_read),0) cr,"
        " COALESCE(SUM(cache_create),0) cc, COUNT(*) n FROM messages").fetchone()
    today = con.execute(
        f"SELECT COALESCE(SUM{BILLABLE},0) t, COUNT(*) n FROM messages WHERE ts>=?", (day0,)).fetchone()
    cost = con.execute("SELECT COALESCE(SUM(cost_usd),0) FROM sessions").fetchone()[0]
    prompts = con.execute("SELECT COUNT(*) FROM prompts").fetchone()[0]
    prompts_today = con.execute("SELECT COUNT(*) FROM prompts WHERE ts>=?", (day0,)).fetchone()[0]
    tools = con.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]
    reads, fresh = tot["cr"], tot["i"] + tot["cc"]
    return {
        "sessions": {"total": sess(0), "today": sess(day0), "week": sess(now - 7 * 86400)},
        "prompts": {"total": prompts, "today": prompts_today},
        "api_calls": tot["n"], "tool_calls": tools,
        "tokens": {"input": tot["i"], "output": tot["o"], "cache_read": tot["cr"], "cache_create": tot["cc"],
                   "today_billable": today["t"]},
        "cache_hit_rate": reads / (reads + fresh) if (reads + fresh) else 0,
        "cost_usd": cost,
    }


def limits(con):
    """Current 5-hour window, estimated from billable tokens against your own peak window."""
    rows = con.execute(f"SELECT ts, {BILLABLE} t FROM messages ORDER BY ts").fetchall()
    span = CONFIG["session_window_hours"] * 3600
    now = time.time()

    windows, cur = [], None            # a window opens at the first message after the last one closed
    for r in rows:
        if cur is None or r["ts"] >= cur["start"] + span:
            cur = {"start": r["ts"], "tokens": 0, "calls": 0}
            windows.append(cur)
        cur["tokens"] += r["t"]
        cur["calls"] += 1

    active = windows[-1] if windows and now < windows[-1]["start"] + span else None
    peak5 = max((w["tokens"] for w in windows), default=0)

    cap5 = CONFIG["limits"]["session_tokens"] or peak5 or 1
    return {
        "five_hour": {
            "used": active["tokens"] if active else 0, "cap": cap5,
            "cap_source": "config" if CONFIG["limits"]["session_tokens"] else "your peak window",
            "started_at": active["start"] if active else None,
            "resets_at": active["start"] + span if active else None,
            "calls": active["calls"] if active else 0,
            "peak": peak5,
            "windows_total": len(windows),
        },
        "estimated": True,
    }


def sessions(con, limit=40):
    out = []
    srows = con.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM prompts p WHERE p.session_id=s.id) prompts,"
        " (SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) calls,"
        f" (SELECT COALESCE(SUM{BILLABLE},0) FROM messages m WHERE m.session_id=s.id) tokens"
        " FROM sessions s WHERE s.first_ts IS NOT NULL ORDER BY s.last_ts DESC LIMIT ?", (limit,)).fetchall()
    live = {l["session_id"] for l in live_sessions()}
    for s in srows:
        main = con.execute(
            "SELECT ts, model, input + cache_read + cache_create ctx FROM messages"
            " WHERE session_id=? AND sidechain=0 ORDER BY ts", (s["id"],)).fetchall()
        ctx_now = main[-1]["ctx"] if main else 0
        model = main[-1]["model"] if main else None
        peak = max((m["ctx"] for m in main), default=0)
        window = _window_for(model, peak)
        step = max(1, len(main) // 60)
        out.append({
            "id": s["id"], "title": s["title"] or s["project"] or s["id"][:8], "project": s["project"],
            "model": model, "entrypoint": s["entrypoint"],
            "first_ts": s["first_ts"], "last_ts": s["last_ts"], "cost_usd": s["cost_usd"],
            "prompts": s["prompts"], "calls": s["calls"], "tokens": s["tokens"],
            "ctx": ctx_now, "ctx_window": window, "ctx_pct": ctx_now / window if window else 0,
            "ctx_series": [m["ctx"] for m in main[::step]], "live": s["id"] in live,
        })
    return out


def daily(con, days=120):
    since = time.time() - days * 86400
    rows = con.execute(
        f"SELECT strftime('%Y-%m-%d', ts, {LOCAL}) d, model, SUM{BILLABLE} t, SUM(output) o, COUNT(*) n"
        " FROM messages WHERE ts>=? GROUP BY d, model ORDER BY d", (since,)).fetchall()
    sess = {r["d"]: r["n"] for r in con.execute(
        f"SELECT strftime('%Y-%m-%d', first_ts, {LOCAL}) d, COUNT(*) n FROM sessions"
        " WHERE first_ts>=? GROUP BY d", (since,))}
    return {"rows": [dict(r) for r in rows], "sessions": sess}


def heatmap(con):
    rows = con.execute(
        f"SELECT CAST(strftime('%w', ts, {LOCAL}) AS INT) dow, CAST(strftime('%H', ts, {LOCAL}) AS INT) hr,"
        f" COUNT(*) n, SUM{BILLABLE} t FROM messages GROUP BY dow, hr").fetchall()
    cal = con.execute(
        f"SELECT strftime('%Y-%m-%d', ts, {LOCAL}) d, COUNT(*) n, SUM{BILLABLE} t FROM messages"
        " GROUP BY d ORDER BY d").fetchall()
    return {"cells": [dict(r) for r in rows], "days": [dict(r) for r in cal]}


def projects(con):
    rows = con.execute(
        f"SELECT s.project, COUNT(DISTINCT s.id) sessions, COALESCE(SUM(m.input+m.output+m.cache_create),0) tokens,"
        " COALESCE((SELECT SUM(cost_usd) FROM sessions x WHERE x.project=s.project),0) cost"
        " FROM sessions s LEFT JOIN messages m ON m.session_id=s.id WHERE s.project IS NOT NULL"
        " GROUP BY s.project ORDER BY tokens DESC").fetchall()
    return [dict(r) for r in rows]


def tools(con):
    rows = con.execute(
        "SELECT name, COUNT(*) n FROM tool_calls WHERE name IS NOT NULL GROUP BY name ORDER BY n DESC").fetchall()
    return [dict(r) for r in rows]


ACTIVE_SECONDS = 120   # Docker: a session counts as running while its transcript changed this recently


def _active_sessions():
    """Docker mode (FLOWLYSTACK_LIVE_BY_ACTIVITY=1): a container cannot see the host's processes and the `sessions` folder is not mounted
    (it also holds session keys), so a session counts as running when its transcript changed in the last two minutes. No name, no busy status."""
    now, out = time.time(), []
    for f in PROJECTS_DIR.glob("*/*.jsonl"):
        try:
            m = f.stat().st_mtime
        except OSError:
            continue
        if now - m <= ACTIVE_SECONDS:
            out.append({"session_id": f.stem, "name": None, "cwd": None, "status": None, "entrypoint": None, "started_at": 0, "updated_at": m})
    return sorted(out, key=lambda x: -x["updated_at"])


def live_sessions():
    """Running Claude processes, from ~/.claude/sessions/<pid>.json. Stale pid files are dropped."""
    if os.environ.get("FLOWLYSTACK_LIVE_BY_ACTIVITY", "").strip().lower() in ("1", "true", "yes", "on"):
        return _active_sessions()
    out = []
    if not SESSIONS_DIR.exists():
        return out
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
            os.kill(d["pid"], 0)
        except (ValueError, KeyError, OSError):
            continue
        out.append({"session_id": d.get("sessionId"), "name": d.get("name"), "cwd": d.get("cwd"),
                    "status": d.get("status"), "entrypoint": d.get("entrypoint"),
                    "started_at": (d.get("startedAt") or 0) / 1000, "updated_at": (d.get("updatedAt") or 0) / 1000})
    return sorted(out, key=lambda x: -x["updated_at"])
