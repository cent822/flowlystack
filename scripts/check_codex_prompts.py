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

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
