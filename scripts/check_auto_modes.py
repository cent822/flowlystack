#!/usr/bin/env python3
"""How well does Auto guess? Labeled messages for both pages (Studio Assistant "Prompt text" and Collections "Search before answering"), in several
styles and languages, scored against the real rules. Prints the misses so they can be looked at; the asserts only keep accuracy from dropping
below the level reached when this file was written. Also checks the conversation memory and the relevance cutoff. No server, standard library only.

A label is what a sensible user wants: STUDIO "prompt" = the message is about the prompt on screen (send its text), "chat" = ordinary chat.
COLLECTIONS "files" = the answer should come from the documents, "chat" = chit-chat that needs none.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.assistant.prompting import include_prompt, include_why  # noqa: E402
from backend.rag import chat  # noqa: E402

STUDIO = [
    # about the prompt
    ("rewrite this to be shorter", "prompt"), ("Can you polish the wording?", "prompt"), ("make this friendlier", "prompt"), ("tighten the second paragraph", "prompt"),
    ("what is missing from my prompt", "prompt"), ("improve it", "prompt"), ("translate it to French", "prompt"), ("expand the examples", "prompt"),
    ("is the {{topic}} variable clear?", "prompt"), ("critique this draft", "prompt"), ("make it stricter", "prompt"), ("simplify the instructions above", "prompt"),
    ("Schreibe den Prompt kürzer", "prompt"), ("verbessere das bitte", "prompt"), ("reescribe esto más claro", "prompt"), ("reformule ce texte", "prompt"),
    ("shorten pls", "prompt"),
    # ordinary chat
    ("hello buddy, how are you doing", "chat"), ("tell me a joke", "chat"), ("thanks for the joke, it was funny", "chat"), ("what's the capital of France", "chat"),
    ("hi", "chat"), ("good morning", "chat"), ("what is a good book to read this weekend", "chat"), ("wie geht es dir", "chat"), ("hola, ¿cómo estás?", "chat"),
    ("can you explain how git rebase works", "chat"), ("lol", "chat"), ("ok", "chat"), ("who are you", "chat"),
    # no cue words and no way to tell without context: expected misses in Auto (On fixes them)
    ("make it sound less robotic", "prompt"), ("Mach es lockerer", "prompt"), ("hazlo más corto", "prompt"), ("rewrte this plz", "prompt"),
]
KNOWN_STUDIO_MISSES = {"make it sound less robotic", "Mach es lockerer", "hazlo más corto", "rewrte this plz"}   # no cue word, or a typo in it

COLLECTIONS = [
    ("what does the document say about refunds", "files"), ("summarise the billing doc", "files"), ("how do I configure the retrieval switch", "files"),
    ("go through the file once and then we dive in", "files"), ("what is our refund policy", "files"), ("explain the invoices flow in detail", "files"),
    ("Was steht im Dokument über Rückerstattungen?", "files"), ("¿qué dice el documento sobre la facturación?", "files"), ("refund windw?", "files"),
    ("thanks for the joke, it was funny. Now I want to discuss our document, can you go through it once", "files"),
    ("hello", "chat"), ("hi buddy", "chat"), ("thanks", "chat"), ("thank you so much", "chat"), ("good morning", "chat"), ("who are you?", "chat"),
    ("ok cool", "chat"), ("bye", "chat"), ("what can you do", "chat"),
]

def score(rows, decide):
    miss = [(m, want, got) for m, want in rows if (got := decide(m)) != want]
    return 1 - len(miss) / len(rows), miss

acc, miss = score(STUDIO, lambda m: "prompt" if include_prompt("auto", m) else "chat")
print(f"Studio Auto: {acc:.0%} of {len(STUDIO)}")
for m, want, got in miss:
    print(f"   miss: {m!r} wanted {want}, got {got}")
assert acc >= 0.85, acc
assert {m for m, _, _ in miss} <= KNOWN_STUDIO_MISSES, "a message outside the known misses is now wrong"
for m in KNOWN_STUDIO_MISSES:
    assert include_prompt("on", m) and not include_prompt("off", m)   # the manual switches always fix a miss

acc, miss = score(COLLECTIONS, lambda m: "files" if chat.should_search("auto", m) else "chat")
print(f"Collections Auto: {acc:.0%} of {len(COLLECTIONS)}")
for m, want, got in miss:
    print(f"   miss: {m!r} wanted {want}, got {got}")
assert acc >= 0.95, acc

# Studio conversation memory: a short reply after a message that sent the prompt text still is about the prompt; chit-chat and long messages are not
assert include_prompt("auto", "and the second line?", True) and include_why("auto", "go on", True) == "follow_up"
assert not include_prompt("auto", "and the second line?", False) and not include_prompt("auto", "thanks", True) and not include_prompt("auto", "hello there", True)
assert not include_prompt("auto", "tell me something about your favourite movies from the nineties", True)
assert include_prompt("on", "hello", False) and not include_prompt("off", "go on", True)
print("Studio memory: ok")

# Collections relevance cutoff
P = lambda i, vs, kr=None: {"id": f"d#{i}", "vector_score": vs, "keyword_rank": kr}
ps = [P(0, 0.70), P(1, 0.40), P(2, 0.35, kr=2), P(3, None, kr=1), P(4, None)]
kept, out, best = chat.apply_cutoff(ps, 0.5)
assert [p["id"] for p in kept] == ["d#0", "d#2", "d#3", "d#4"] and [p["id"] for p in out] == ["d#1"] and best == 0.70   # exact-word matches and unscored ones stay
assert chat.apply_cutoff(ps, 0)[0] == ps and chat.apply_cutoff(ps, 0)[1] == [] and chat.apply_cutoff([], 0.5) == ([], [], None)
kept, out, best = chat.apply_cutoff([P(0, 0.2), P(1, 0.3)], 0.5)
assert kept == [] and len(out) == 2 and best == 0.3   # nothing relevant: nothing is sent
assert [chat.why_search(m, x) for m, x in (("on", "hi"), ("off", "q"), ("auto", "hi"), ("auto", "refund window?"))] == ["on", "off", "small_talk", "question"]
print("Collections cutoff: ok")
print("\nall auto-mode checks passed")
