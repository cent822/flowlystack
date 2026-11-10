#!/usr/bin/env python3
"""Codex UserPromptSubmit hook: save every prompt you submit into FlowlyStack's prompts folder, labelled `codex`.

Codex sends the hook JSON on stdin (session_id, cwd, prompt, model, ...). Anything printed on stdout is added to the
model's context by Codex, so this prints nothing, and it always exits 0 so it can never block or break your typing.
Uses only the standard library; any python3 works.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.promptstore import clean_codex_prompt, write_prompt

    data = json.load(sys.stdin)
    text = clean_codex_prompt(data.get("prompt"))
    if text:
        model = data.get("model")
        write_prompt(text, time.time(), data.get("session_id") or "", data.get("cwd") or "", source="hook",
                     extra={"agent": "codex", **({"model": model} if isinstance(model, str) and model else {})})
except Exception as e:   # never fail the user's prompt
    print(f"flowlystack codex hook: {e}", file=sys.stderr)
sys.exit(0)
