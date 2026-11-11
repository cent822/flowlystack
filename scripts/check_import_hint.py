#!/usr/bin/env python3
"""Checks that the Claude Code import tells "no history folder" apart from "nothing new". No server, temp folders only.
    .venv/bin/python scripts/check_import_hint.py
The import result carries `files`, the number of transcript files found. The Prompt Library page shows a hint to connect the
history folder when it is 0; "Imported 0, skipped N" with files > 0 is a normal repeat."""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import promptstore  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="flowlystack-import-hint-check-"))
fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


empty = tmp / "empty"
empty.mkdir()
r = promptstore.import_transcripts(empty, tmp / "p1")
check("an empty history folder reports files = 0", r == {"imported": 0, "skipped": 0, "files": 0})
check("a missing history folder reports files = 0", promptstore.import_transcripts(tmp / "nope", tmp / "p1")["files"] == 0)

proj = tmp / "proj" / "-Users-x-demo"
proj.mkdir(parents=True)
line = {"type": "user", "sessionId": "s1", "timestamp": "2026-11-11T10:00:00Z", "cwd": "/x", "message": {"role": "user", "content": "hello there"}}
(proj / "s1.jsonl").write_text(json.dumps(line) + "\n")
r1 = promptstore.import_transcripts(tmp / "proj", tmp / "p2")
r2 = promptstore.import_transcripts(tmp / "proj", tmp / "p2")
check("one transcript file is counted and imported", r1["files"] == 1 and r1["imported"] == 1)
check("a repeat finds the file, imports nothing, skips it", r2 == {"imported": 0, "skipped": 1, "files": 1})

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
