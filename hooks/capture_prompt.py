#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook: save every prompt you submit into FlowlyStack's prompts folder.

Reads the hook JSON from stdin, writes one file, prints nothing (stdout from this hook would be
fed to Claude as context) and always exits 0 so it can never block or break your typing.
Uses only the standard library; any python3 works.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.promptstore import write_prompt

    data = json.load(sys.stdin)
    text = data.get("prompt")
    if isinstance(text, str) and text.strip():
        write_prompt(text, time.time(), data.get("session_id") or "", data.get("cwd") or "", source="hook")
except Exception as e:   # never fail the user's prompt
    print(f"flowlystack hook: {e}", file=sys.stderr)
sys.exit(0)
