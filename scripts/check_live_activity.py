#!/usr/bin/env python3
"""Checks the Docker "running now" mode (FLOWLYSTACK_LIVE_BY_ACTIVITY=1, backend/queries.py): a session counts as running while its transcript
changed in the last two minutes; the default mode (process ids from ~/.claude/sessions) is unchanged. Temp dirs, no server.
    .venv/bin/python scripts/check_live_activity.py"""
import os
import sys
import tempfile
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp())
os.environ["HOME"] = str(HOME)   # config reads Path.home() once, before the backend is imported
os.environ.pop("FLOWLYSTACK_LIVE_BY_ACTIVITY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import queries  # noqa: E402

proj = HOME / ".claude" / "projects" / "-work-demo"
proj.mkdir(parents=True)
fresh, old, other = proj / "aaa.jsonl", proj / "bbb.jsonl", proj / "notes.txt"
for f in (fresh, old, other):
    f.write_text("{}\n")
os.utime(old, (time.time() - 600, time.time() - 600))

assert queries.live_sessions() == [], "default mode reads ~/.claude/sessions (empty here), never the transcripts"
os.environ["FLOWLYSTACK_LIVE_BY_ACTIVITY"] = "1"
live = queries.live_sessions()
assert [s["session_id"] for s in live] == ["aaa"], live            # the recent transcript only; the old one and the .txt are not sessions
assert live[0]["status"] is None and live[0]["name"] is None       # no busy status, no name in this mode
os.utime(fresh, (time.time() - queries.ACTIVE_SECONDS - 5,) * 2)
assert queries.live_sessions() == [], "a transcript older than two minutes is no longer running"
os.environ["FLOWLYSTACK_LIVE_BY_ACTIVITY"] = "off"
assert queries.live_sessions() == []
print("check_live_activity: ok")
