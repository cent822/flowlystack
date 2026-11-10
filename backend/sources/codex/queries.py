"""Read-side for Codex: the same JSON shapes as backend/queries.py, so the Dashboard cards stay unchanged.

Billable tokens here are (input - cached) + output: cached tokens are a subset of input and output already
includes reasoning. Cost does not exist in Codex files, so it is null.
"""
import time
from datetime import datetime

LOCAL = "'unixepoch','localtime'"
BILLABLE = "(input - cached + output)"
LIVE_SECONDS = 60   # Codex keeps no process files; "live" means an event in the last minute


def overview(con):
    now = time.time()
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    sess = lambda since: con.execute("SELECT COUNT(*) FROM sessions WHERE first_ts>=?", (since,)).fetchone()[0]
    tot = con.execute(
        "SELECT COALESCE(SUM(input-cached),0) i, COALESCE(SUM(output),0) o, COALESCE(SUM(cached),0) cr,"
        " COALESCE(SUM(input),0) allin, COUNT(*) n FROM turns").fetchone()
    today = con.execute(f"SELECT COALESCE(SUM{BILLABLE},0) FROM turns WHERE ts>=?", (day0,)).fetchone()[0]
    one = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    return {
        "sessions": {"total": sess(0), "today": sess(day0), "week": sess(now - 7 * 86400)},
        "prompts": {"total": one("SELECT COUNT(*) FROM prompts"), "today": one("SELECT COUNT(*) FROM prompts WHERE ts>=?", day0)},
        "api_calls": tot["n"], "tool_calls": one("SELECT COUNT(*) FROM tool_calls"),
        "tokens": {"input": tot["i"], "output": tot["o"], "cache_read": tot["cr"], "cache_create": 0, "today_billable": today},
        "cache_hit_rate": tot["cr"] / tot["allin"] if tot["allin"] else 0,
        "cost_usd": None,
    }


def limits(con):
    """What Codex itself reported last. `five_hour` is the primary window, whatever its length (300 min on Plus, 30 days
    on the free plan: see window_minutes); `weekly` is the secondary window and is null when the plan has none.
    A window already past its reset reads as inactive."""
    r = con.execute("SELECT * FROM limits").fetchone()
    now = time.time()

    def window(used, resets, minutes):
        on = bool(resets) and now < resets
        return {"used": used if on else 0, "cap": 100, "cap_source": "reported by Codex",
                "started_at": resets - minutes * 60 if on else None, "resets_at": resets if on else None,
                "window_minutes": minutes}

    if not r:
        w = {"used": 0, "cap": 100, "cap_source": "reported by Codex", "started_at": None, "resets_at": None, "window_minutes": 300}
        return {"five_hour": {**w, "calls": 0, "peak": 100, "windows_total": 0}, "weekly": None, "plan": None, "estimated": False}
    five = window(r["p_used"], r["p_resets"], r["p_minutes"] or 300)
    calls = con.execute("SELECT COUNT(*) FROM turns WHERE ts>=?", (five["started_at"],)).fetchone()[0] if five["started_at"] else 0
    return {"five_hour": {**five, "calls": calls, "peak": 100, "windows_total": 0},
            "weekly": window(r["s_used"], r["s_resets"], r["s_minutes"]) if r["s_minutes"] else None, "plan": r["plan"], "estimated": False}


def sessions(con, limit=40):
    now = time.time()
    rows = con.execute(
        "SELECT s.*, (SELECT COUNT(*) FROM prompts p WHERE p.session_id=s.id) prompts,"
        " (SELECT COUNT(*) FROM turns t WHERE t.session_id=s.id) calls,"
        f" (SELECT COALESCE(SUM{BILLABLE},0) FROM turns t WHERE t.session_id=s.id) tokens"
        " FROM sessions s WHERE s.first_ts IS NOT NULL ORDER BY s.last_ts DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for s in rows:
        t = con.execute("SELECT input + output ctx, window, model FROM turns WHERE session_id=? ORDER BY total", (s["id"],)).fetchall()
        ctx_now = t[-1]["ctx"] if t else 0
        window = (t[-1]["window"] if t else None) or 0
        step = max(1, len(t) // 60)
        out.append({
            "id": s["id"], "title": s["title"] or s["project"] or s["id"][:8], "project": s["project"],
            "model": (t[-1]["model"] if t else None) or s["model"], "entrypoint": s["originator"],
            "first_ts": s["first_ts"], "last_ts": s["last_ts"], "cost_usd": None,
            "prompts": s["prompts"], "calls": s["calls"], "tokens": s["tokens"],
            "ctx": ctx_now, "ctx_window": window, "ctx_pct": ctx_now / window if window else 0,
            "ctx_series": [x["ctx"] for x in t[::step]], "live": now - (s["last_ts"] or 0) < LIVE_SECONDS,
        })
    return out


def daily(con, days=120):
    since = time.time() - days * 86400
    rows = con.execute(
        f"SELECT strftime('%Y-%m-%d', ts, {LOCAL}) d, model, SUM{BILLABLE} t, SUM(output) o, COUNT(*) n"
        " FROM turns WHERE ts>=? GROUP BY d, model ORDER BY d", (since,)).fetchall()
    sess = {r["d"]: r["n"] for r in con.execute(
        f"SELECT strftime('%Y-%m-%d', first_ts, {LOCAL}) d, COUNT(*) n FROM sessions WHERE first_ts>=? GROUP BY d", (since,))}
    return {"rows": [dict(r) for r in rows], "sessions": sess}


def heatmap(con):
    cells = con.execute(
        f"SELECT CAST(strftime('%w', ts, {LOCAL}) AS INT) dow, CAST(strftime('%H', ts, {LOCAL}) AS INT) hr,"
        f" COUNT(*) n, SUM{BILLABLE} t FROM turns GROUP BY dow, hr").fetchall()
    cal = con.execute(
        f"SELECT strftime('%Y-%m-%d', ts, {LOCAL}) d, COUNT(*) n, SUM{BILLABLE} t FROM turns GROUP BY d ORDER BY d").fetchall()
    return {"cells": [dict(r) for r in cells], "days": [dict(r) for r in cal]}


def projects(con):
    rows = con.execute(
        "SELECT s.project, COUNT(DISTINCT s.id) sessions,"
        f" COALESCE(SUM(t.input - t.cached + t.output),0) tokens, NULL cost"
        " FROM sessions s LEFT JOIN turns t ON t.session_id=s.id WHERE s.project IS NOT NULL"
        " GROUP BY s.project ORDER BY tokens DESC").fetchall()
    return [dict(r) for r in rows]


def tools(con):
    rows = con.execute(
        "SELECT name, COUNT(*) n FROM tool_calls WHERE name IS NOT NULL GROUP BY name ORDER BY n DESC").fetchall()
    return [dict(r) for r in rows]
