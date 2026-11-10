#!/usr/bin/env python3
"""Checks for backend/rag/chat.py: small-talk detection, the retrieval switch, message assembly and trimming. No server, standard library only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.rag import chat  # noqa: E402


def step(msg: str) -> None:
    print("ok  ", msg)


for m in ("hi", "Hello there!", "thanks a lot", "ok cool", "good morning", "who are you?"):
    assert chat.is_small_talk(m), m
for m in ("what is our refund policy", "hi, can you summarise the billing document for me please", "thanks, now explain the invoices flow in detail", ""):
    assert not chat.is_small_talk(m), m
assert chat.should_search("auto", "refund window?") and not chat.should_search("auto", "hello") and chat.should_search("on", "hello") and not chat.should_search("off", "refund window?")
step("Auto skips small talk only; On always searches; Off never does")

P = lambda i, n=400: {"id": f"d#{i}", "name": "guide.md", "locator": "Billing", "text": "x" * n}
r = chat.build_messages("q?", [P(0), P(1)], "", [], 6, 8192)
assert [m["role"] for m in r["messages"]] == ["system", "user", "user"] and r["messages"][0]["content"] == chat.DEFAULT_INSTRUCTIONS
assert r["context"].startswith("Passages from my files") and "[1] guide.md · Billing" in r["context"] and "[2] guide.md" in r["context"] and r["included"] == ["d#0", "d#1"]
assert "x" * 10 not in r["system"] and r["dropped"] == 0 and r["trimmed"] == 0
step("the passages are one numbered reference message; the system message never holds document text")

assert chat.build_messages("q?", [], "Be brief.")["messages"][0]["content"] == "Be brief." and [m["role"] for m in chat.build_messages("q?", [])["messages"]] == ["system", "user"]
step("your instructions replace the built-in text; no passages means no reference message")

hist = [{"prompt": f"p{i}", "response": f"r{i}"} for i in range(10)]
r = chat.build_messages("q?", [], "", hist, 3, 8192)
assert [m["content"] for m in r["messages"][1:-1]] == ["p7", "r7", "p8", "r8", "p9", "r9"] and r["trimmed"] == 7
step("only the last few exchanges are sent")

r = chat.build_messages("q?", [P(i) for i in range(10)], "", [], 6, 1024)
assert 0 < len(r["included"]) < 10 and r["dropped"] == 10 - len(r["included"]) and r["included"] == [f"d#{i}" for i in range(len(r["included"]))]
r = chat.build_messages("q?", [P(0, 3000)], "", [], 6, 512)
assert r["cut"] == 1 and r["context"].endswith("-" * 10) and "[…]" in r["context"] and len(r["context"]) < 1000
r = chat.build_messages("q?", [P(0), P(1)], "", [{"prompt": "a" * 2000, "response": "b" * 2000}], 6, 1024)
assert r["trimmed"] == 1 and r["included"]   # earlier exchanges go before passages
step("over the window: old exchanges go first, then the lowest-ranked passages, then one long passage is shortened")

print("\nall chat checks passed")
