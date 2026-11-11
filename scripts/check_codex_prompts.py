#!/usr/bin/env python3
"""Checks that typed Codex prompts are found in both rollout formats, by the Library importer and by the Dashboard counter.
No server, temp folders only.
    .venv/bin/python scripts/check_codex_prompts.py
Older Codex writes `event_msg` / `user_message`; current Codex (0.167) writes `event_msg` / `item_completed` with a `UserMessage` item.
Injected user-role context (AGENTS.md, environment) is never a typed prompt."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="flowlystack-codex-prompts-check-"))
os.environ["CODEX_HOME"] = str(tmp / "codex")                    # before the backend is imported: config reads it once
os.environ["FLOWLYSTACK_CODEX_DB"] = str(tmp / "codex.db")
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(tmp / "state-prompts")     # where the Import button keeps its state file
sys.path.insert(0, str(ROOT))
from backend import promptstore  # noqa: E402
from backend.promptsync import codex as importer  # noqa: E402
from backend.sources.codex import db, ingest  # noqa: E402

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def item(text, ts):
    return {"timestamp": ts, "type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "UserMessage", "id": "i", "client_id": "c", "content": [{"type": "text", "text": text, "text_elements": []}]}}}


def old(text, ts):
    return {"timestamp": ts, "type": "event_msg", "payload": {"type": "user_message", "message": text}}


context = {"timestamp": "2026-11-11T10:00:01Z", "type": "response_item",
           "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# AGENTS.md instructions"}]}}
other = {"timestamp": "2026-11-11T10:00:02Z", "type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "AgentMessage"}}}


def rollout(day, uuid, lines):
    d = tmp / "codex" / "sessions" / "2026" / "11" / day
    d.mkdir(parents=True, exist_ok=True)
    (d / f"rollout-2026-11-{day}T10-00-00-{uuid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))


# 1. the helper, line by line
check("new format: typed text found", promptstore.codex_typed_text(item("hello", "t")) == "hello")
check("new format: several text parts are joined", promptstore.codex_typed_text(
    {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": [
        {"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}}}) == "a\nb")
check("old format: typed text found", promptstore.codex_typed_text(old("hi", "t")) == "hi")
check("injected user-role context is not a prompt", promptstore.codex_typed_text(context) is None)
check("other items are not prompts", promptstore.codex_typed_text(other) is None)

# 2. the Library importer and the Dashboard counter, on one old-format and one new-format session
rollout("10", "11111111-1111-1111-1111-111111111111", [old("first old prompt", "2026-11-10T10:00:00Z"), context])
rollout("11", "22222222-2222-2222-2222-222222222222",
        [context, item("first new prompt", "2026-11-11T10:00:00Z"), other, item("second new prompt", "2026-11-11T10:05:00Z")])

root = tmp / "prompts"
st = {"files": {}, "seen": set(), "cwd": {}}
n = importer.pull(st, root)
texts = sorted(o["prompt"] for o in promptstore.load_all(root))
check("importer saves 3 typed prompts from both formats", n == 3)
check("the saved texts are the typed ones only", texts == ["first new prompt", "first old prompt", "second new prompt"])
check("a second pass saves nothing again", importer.pull(st, root) == 0)

con = db.connect()
ingest.scan(con)
check("Dashboard counts 3 prompts", con.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 3)

# 3. Files read to the end by the OLD reader (which found no prompts) must be read again once, or the fix never shows on an
#    install that already had Live sync / the Dashboard running. The remembered positions are what an old install has on disk.
import sqlite3  # noqa: E402

sizes = {str(p): p.stat().st_size for p in importer._rollouts()}
state_dir = tmp / "state-prompts" / ".sources"
state_dir.mkdir(parents=True)
(state_dir / "codex.json").write_text(json.dumps({"enabled": True, "imported": 0, "seen": [], "files": sizes, "cwd": {}}))   # no "parse" key
from backend import promptsync  # noqa: E402
r = promptsync.run_once("codex")
check("an old install's Import re-reads files it had skipped", r["imported"] == 3)
check("the state now remembers the new reading rules", json.loads((state_dir / "codex.json").read_text()).get("parse") == promptsync.PARSER["codex"])
check("pressing Import again saves nothing more", promptsync.run_once("codex")["imported"] == 0)

old_db = tmp / "old.db"
raw = sqlite3.connect(old_db)
raw.executescript(db.SCHEMA)
raw.executemany("INSERT INTO files VALUES(?,?)", sizes.items())   # user_version is 0, as before the change
raw.commit()
raw.close()
db.CODEX_DB_PATH = old_db
con2 = db.connect()
ingest.scan(con2)
check("an old Dashboard cache re-reads its files and counts 3 prompts", con2.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 3)
n_before = con2.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
con2.execute("DELETE FROM files")
ingest.scan(con2)
check("reading a file twice does not double anything", con2.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 3
      and con2.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == n_before)

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
