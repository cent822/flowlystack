"""Codex source: own SQLite file (data/codex.db), own lock, same route functions as the Claude queries.

Nothing here touches the Claude path. Any error is kept in `error` and shows as N/A for this source only.
"""
import threading

from .. import na
from . import ingest, queries
from .db import connect

LABEL = "Codex"
_lock = threading.Lock()
_con = None
error = None


def _db():
    global _con
    if _con is None:
        _con = connect()
    return _con


def scan() -> int:
    """Pick up new rollout lines. Returns how many were processed; failures are recorded, not raised."""
    global error
    try:
        with _lock:
            n = ingest.scan(_db())
        error = None
        return n
    except Exception as e:
        error = str(e)
        return 0


def _run(fn, *a):
    if error:
        return na(f"Codex could not be read: {error}")
    with _lock:
        return fn(_db(), *a)


def overview(): return _run(queries.overview)
def limits(): return _run(queries.limits)
def sessions(limit=40): return _run(queries.sessions, limit)
def daily(days=120): return _run(queries.daily, days)
def heatmap(): return _run(queries.heatmap)
def projects(): return _run(queries.projects)
def tools(): return _run(queries.tools)
def live(): return na("Codex does not expose running sessions.")
