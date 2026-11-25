#!/usr/bin/env python3
"""Checks Claude Code live sync and the Import button: nothing doubles, deleted prompts stay deleted, only new bytes are read.
No server, temp folders only.
    .venv/bin/python scripts/check_claude_sync.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="flowlystack-claude-sync-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(tmp / "prompts")   # before the backend is imported: config reads it once
sys.path.insert(0, str(ROOT))
from backend import promptstore, promptsync  # noqa: E402
from backend.promptsync import claude  # noqa: E402

claude.PROJECTS_DIR = tmp / "projects"
root = tmp / "prompts"
log = tmp / "projects" / "demo" / "s1.jsonl"
log.parent.mkdir(parents=True)
fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def line(text, ts, **more):
    stamp = datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": "user", "sessionId": "s1", "timestamp": stamp, "cwd": "/x/demo",
                       "message": {"role": "user", "content": text}, **more}) + "\n"


def add(*lines):
    with open(log, "a") as f:
        f.write("".join(lines))


def texts():
    return sorted(o["prompt"] for o in promptstore.load_all(root))


old = round(time.time()) - 3600
check("Claude Code is offered", promptsync.status()["claude"]["available"])
check("live sync is off until switched on", not promptsync.is_enabled("claude"))
check("a missing history folder imports nothing", claude.import_all({"seen": set(), "files": {}}, root)["imported"] == 0)

promptstore.write_prompt("from hook", old + 2.5, "s1", source="hook", root=root)
gone = promptstore.write_prompt("trashed one", old + 100, "s1", source="hook", root=root)
promptstore.trash(gone, root)
add(line("from hook", old), line("trashed one", old + 100), line("new one", old + 200), line("yes", old + 300),
    line("summary", old + 310, isCompactSummary=True), line("[Request interrupted by user]", old + 320),
    line("meta", old + 330, isMeta=True))
check("live sync saves only what is new", promptsync.run("claude") == 2)
check("hook, trashed and machine-written lines are skipped", texts() == ["from hook", "new one", "yes"])
check("saved as source sync", {o["source"] for o in promptstore.load_all(root) if o["prompt"] == "yes"} == {"sync"})

ledger = root / ".sources" / "claude.json"
before = ledger.stat().st_mtime_ns
check("nothing new saves nothing and leaves the ledger alone", promptsync.run("claude") == 0 and ledger.stat().st_mtime_ns == before)

add(line("yes", old + 340))
check("the same words sent again later are kept", promptsync.run("claude") == 1 and texts().count("yes") == 2)

add(line("half", old + 400).rstrip("\n"))
check("a partly written line waits", promptsync.run("claude") == 0)
add("\n")
check("and is saved once complete", promptsync.run("claude") == 1)

now = time.time()
add(line("just sent", now))
check("a very new prompt waits for the hook", promptsync.run("claude") == 0)
promptstore.write_prompt("just sent", now + 1, "s1", source="hook", root=root)
claude.SETTLE = 0
check("the hook's copy is not doubled", promptsync.run("claude") == 0 and texts().count("just sent") == 1)

for o in promptstore.load_all(root):
    if o["prompt"] == "new one":
        promptstore.trash(o["id"], root)
        promptstore.purge(o["id"], root)
r = promptsync.import_claude()
check("Import does not bring back a prompt deleted for good", r["imported"] == 0 and "new one" not in texts())
check("Import reports what it skipped and the files", r["skipped"] >= 5 and r["files"] == 1)
check("switching live sync on is remembered", promptsync.set_enabled("claude", True)["enabled"] and promptsync.is_enabled("claude"))

sig = promptstore.signature(root)
time.sleep(0.05)
promptstore.write_prompt("signal", time.time(), "s2", root=root)
check("a new prompt file changes the folder signature", promptstore.signature(root) != sig)

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
