"""Read-side for Ollama (via Open WebUI): the same JSON shapes as backend/queries.py, so the Dashboard cards stay unchanged.

A chat is a "session", a model call is an "API call", tokens are prompt + generated. There is no cost, cache, plan limit,
context size, project or tool concept: those fields are null and the frontend draws N/A. Two cards are reused: Projects
lists models (tokens), and the Tools card shows speed per model (tokens per second, weighted by generation time).
"""
import time
from datetime import datetime

LOCAL = "'unixepoch','localtime'"
TOK = "(input + output)"
# only chats that have at least one Ollama answer: Open WebUI also talks to other providers
CHATS = "chat_id IN (SELECT DISTINCT chat_id FROM calls)"


def _tps(output, ns):
    return round(output / (ns / 1e9), 1) if ns else None


def overview(con):
    now = time.time()
    day0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    one = lambda sql, *a: con.execute(sql, a).fetchone()[0]
    firsts = "(SELECT MIN(ts) f FROM (SELECT chat_id, ts FROM calls UNION ALL SELECT chat_id, ts FROM prompts WHERE " + CHATS + ") GROUP BY chat_id)"
    sess = lambda since: one(f"SELECT COUNT(*) FROM {firsts} WHERE f>=?", since)
    t = con.execute("SELECT COALESCE(SUM(input),0) i, COALESCE(SUM(output),0) o, COUNT(*) n,"
                    " COALESCE(SUM(CASE WHEN eval_ns>0 THEN output END),0) go, COALESCE(SUM(eval_ns),0) ns FROM calls").fetchone()
    return {
        "sessions": {"total": sess(0), "today": sess(day0), "week": sess(now - 7 * 86400)},
        "prompts": {"total": one(f"SELECT COUNT(*) FROM prompts WHERE {CHATS}"),
                    "today": one(f"SELECT COUNT(*) FROM prompts WHERE {CHATS} AND ts>=?", day0)},
        "api_calls": t["n"], "tool_calls": None,
        "tokens": {"input": t["i"], "output": t["o"], "cache_read": 0, "cache_create": 0,
                   "today_billable": one(f"SELECT COALESCE(SUM{TOK},0) FROM calls WHERE ts>=?", day0)},
        "cache_hit_rate": None, "cost_usd": None,
        "speed": {"avg_tps": _tps(t["go"], t["ns"])},
    }


def limits(con):
    from .. import na
    return na("Ollama has no usage limits.")


def sessions(con, limit=40):
    rows = con.execute(
        "SELECT c.chat_id id, ch.title title, MIN(c.ts) first_ts, MAX(c.ts) last_ts, COUNT(*) calls,"
        f" SUM{TOK} tokens, (SELECT COUNT(*) FROM prompts p WHERE p.chat_id=c.chat_id) prompts,"
        " (SELECT model FROM calls x WHERE x.chat_id=c.chat_id ORDER BY ts DESC LIMIT 1) model"
        " FROM calls c LEFT JOIN chats ch ON ch.id=c.chat_id GROUP BY c.chat_id ORDER BY last_ts DESC LIMIT ?", (limit,)).fetchall()
    return [{
        "id": r["id"], "title": r["title"] or (r["model"] or "chat"), "project": None, "model": r["model"],
        "entrypoint": "open-webui", "first_ts": r["first_ts"], "last_ts": r["last_ts"], "cost_usd": None,
        "prompts": r["prompts"], "calls": r["calls"], "tokens": r["tokens"],
        "ctx": None, "ctx_window": None, "ctx_pct": None, "ctx_series": [], "live": False,
    } for r in rows]


def daily(con, days=120):
    since = time.time() - days * 86400
    rows = con.execute(
        f"SELECT strftime('%Y-%m-%d', ts, {LOCAL}) d, model, SUM{TOK} t, SUM(output) o, COUNT(*) n"
        " FROM calls WHERE ts>=? GROUP BY d, model ORDER BY d", (since,)).fetchall()
    sess = {r["d"]: r["n"] for r in con.execute(
        f"SELECT strftime('%Y-%m-%d', f, {LOCAL}) d, COUNT(*) n FROM (SELECT MIN(ts) f FROM calls GROUP BY chat_id)"
        " WHERE f>=? GROUP BY d", (since,))}
    return {"rows": [dict(r) for r in rows], "sessions": sess}


def heatmap(con):
    cells = con.execute(
        f"SELECT CAST(strftime('%w', ts, {LOCAL}) AS INT) dow, CAST(strftime('%H', ts, {LOCAL}) AS INT) hr,"
        f" COUNT(*) n, SUM{TOK} t FROM calls GROUP BY dow, hr").fetchall()
    cal = con.execute(
        f"SELECT strftime('%Y-%m-%d', ts, {LOCAL}) d, COUNT(*) n, SUM{TOK} t FROM calls GROUP BY d ORDER BY d").fetchall()
    return {"cells": [dict(r) for r in cells], "days": [dict(r) for r in cal]}


def projects(con):
    """The Projects card, reused as "Models": tokens per model."""
    rows = con.execute(
        f"SELECT model project, COUNT(DISTINCT chat_id) sessions, SUM{TOK} tokens, NULL cost"
        " FROM calls WHERE model IS NOT NULL GROUP BY model ORDER BY tokens DESC").fetchall()
    return [dict(r) for r in rows]


def tools(con):
    """The Tools card, reused as "Speed by model": tokens per second while generating."""
    rows = con.execute(
        "SELECT model, SUM(output) o, SUM(eval_ns) ns FROM calls WHERE eval_ns>0 AND model IS NOT NULL GROUP BY model").fetchall()
    out = [{"name": r["model"], "n": _tps(r["o"], r["ns"])} for r in rows]
    return sorted((x for x in out if x["n"]), key=lambda x: -x["n"])
