#!/usr/bin/env python3
"""Adds or removes the FlowlyStack prompt-capture hook in a Claude Code or Codex hooks JSON file. Standard library only.

    merge_hooks.py add    <file> <command>     # merge a UserPromptSubmit hook that runs <command>
    merge_hooks.py remove <file> <command>     # take exactly that hook out again

It runs inside a one-off container on a COPY of the user's file, so the host needs no Python. It never replaces other hooks or
other keys, does nothing when the hook is already there (add) or not there (remove), keeps the file's indentation, and refuses
(exit 2, file untouched) when the file is not valid JSON of the expected shape. Prints one word: added, already, removed or absent.
"""
import json
import re
import sys
from pathlib import Path

EVENT = "UserPromptSubmit"


def _style(raw: str):
    """(indent, separators) that rewrite the file the way it was written: indented, or compact on one line (with or without spaces)."""
    m = re.search(r"^( +|\t+)\S", raw, re.M)
    if m:
        return (m.group(1) if m.group(1).startswith("\t") else len(m.group(1))), None
    if raw.strip() and "\n" not in raw.strip():
        return None, ((", ", ": ") if re.search(r'"\s*:\s', raw) else (",", ":"))
    return 2, None


def _entries(data: dict) -> list:
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        raise ValueError('"hooks" is not an object')
    lst = hooks.get(EVENT)
    if not isinstance(lst, list):
        raise ValueError(f'"hooks.{EVENT}" is not a list')
    return lst


def _has(entry, command: str) -> bool:
    return isinstance(entry, dict) and any(isinstance(h, dict) and h.get("command") == command for h in entry.get("hooks") or [])


def merge(raw: str, action: str, command: str):
    """Returns (new_text, status). raw may be empty (no file yet)."""
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        raise ValueError("the file is not a JSON object")
    indent, seps = _style(raw)
    tail = "\n" if raw.endswith("\n") or not raw else ""
    if action == "add":
        data.setdefault("hooks", {})
        if not isinstance(data["hooks"], dict):
            raise ValueError('"hooks" is not an object')
        data["hooks"].setdefault(EVENT, [])
        lst = _entries(data)
        if any(_has(e, command) for e in lst):
            return raw, "already"
        lst.append({"hooks": [{"type": "command", "command": command}]})
        status = "added"
    else:
        if "hooks" not in data or EVENT not in (data["hooks"] if isinstance(data["hooks"], dict) else {}):
            return raw, "absent"
        lst = _entries(data)
        kept = []
        for e in lst:
            if _has(e, command):
                rest = [h for h in e["hooks"] if not (isinstance(h, dict) and h.get("command") == command)]
                if rest:
                    kept.append({**e, "hooks": rest})
            else:
                kept.append(e)
        if len(kept) == len(lst) and all(a is b for a, b in zip(kept, lst)):
            return raw, "absent"
        if kept:
            data["hooks"][EVENT] = kept
        else:
            del data["hooks"][EVENT]
            if not data["hooks"]:
                del data["hooks"]
        status = "removed"
    return json.dumps(data, indent=indent, separators=seps, ensure_ascii=False) + tail, status


def main(argv) -> int:
    if len(argv) != 4 or argv[1] not in ("add", "remove"):
        print(__doc__, file=sys.stderr)
        return 64
    path, command = Path(argv[2]), argv[3]
    try:
        raw = path.read_text(encoding="utf-8-sig") if path.exists() else ""   # Windows editors often add a byte-order mark
        text, status = merge(raw, argv[1], command)
    except (ValueError, OSError) as e:   # JSONDecodeError is a ValueError
        print(f"refused: {e}", file=sys.stderr)
        return 2
    if text != raw:
        path.write_text(text, encoding="utf-8")
    print(status)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
