"""Cut text into passages for Collections. Standard library only.

A passage is about 500 to 800 tokens; characters stand in for tokens at roughly four per token, so the sizes below are in
characters. They are constants tuned against real documents in phase 3 and the recall check in phase 11. A text that has to
be cut inside one section repeats a short tail at the start of the next piece (OVERLAP) so a sentence on the boundary is
found from either side; pieces from different sections, pages or records never overlap.
"""
from __future__ import annotations

import re

TARGET = 2400     # ~600 tokens: a piece is closed once adding the next paragraph would pass this
MAX = 3200        # ~800 tokens: no merged piece is longer than this
MIN = 400         # ~100 tokens: a piece shorter than this is merged into its neighbour when it fits
OVERLAP = 240     # ~60 tokens repeated when one section is cut in several pieces

_FENCE = re.compile(r"^\s*(```|~~~)")


def blocks(text: str) -> list[str]:
    """Paragraphs (split at blank lines); a fenced code block stays in one piece even when it contains blank lines."""
    out, cur, fence = [], [], None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _FENCE.match(line)
        if m and fence is None:
            fence = m.group(1)
        elif m and m.group(1) == fence:
            fence = None
        if not line.strip() and fence is None:
            if cur:
                out.append("\n".join(cur).strip("\n"))
                cur = []
        else:
            cur.append(line)
    if cur:
        out.append("\n".join(cur).strip("\n"))
    return [b for b in out if b.strip()]


def _tail(text: str) -> str:
    """The last OVERLAP characters, starting at a word."""
    if len(text) <= OVERLAP:
        return text
    t = text[-OVERLAP:]
    i = t.find(" ")
    return t[i + 1:] if 0 <= i < 60 else t


def split_long(text: str) -> list[str]:
    """One long paragraph (or a long code block) cut at whitespace into windows of about TARGET characters with OVERLAP."""
    text = text.strip()
    if len(text) <= MAX:
        return [text] if text else []
    out, i = [], 0
    while i < len(text):
        end = min(i + TARGET, len(text))
        if end < len(text):
            cut = max(text.rfind(" ", i + TARGET // 2, end), text.rfind("\n", i + TARGET // 2, end))
            end = cut + 1 if cut > 0 else end
        piece = text[i:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        nxt = max(end - OVERLAP, i + 1)
        ws = text.find(" ", nxt, nxt + 60)
        i = ws + 1 if ws != -1 else nxt
    return out


def split_text(text: str) -> list[str]:
    """Pack the paragraphs of one section into pieces of about TARGET characters. Cut pieces overlap by a short tail."""
    pieces, buf, size = [], [], 0
    for b in blocks(text):
        parts = split_long(b) if len(b) > MAX else [b]
        for part in parts:
            if buf and size + len(part) + 2 > TARGET:
                done = "\n\n".join(buf)
                pieces.append(done)
                tail = _tail(done)
                buf, size = ([tail] if tail and len(tail) < len(done) else []), len(tail) if len(tail) < len(done) else 0
            buf.append(part)
            size += len(part) + 2
    if buf:
        last = "\n\n".join(buf)
        if not pieces or last.strip() != _tail(pieces[-1]).strip():
            pieces.append(last)
    return [p.strip() for p in pieces if p.strip()]


def merge_small(pieces: list[tuple[str, str]], join=lambda a, b: a) -> list[tuple[str, str]]:
    """Merge a piece shorter than MIN into the next one while the result fits in MAX. `join(first, second)` makes the merged
    locator (the default keeps the first one). Pieces are (locator, text)."""
    out: list[tuple[str, str]] = []
    for loc, text in pieces:
        if out and len(out[-1][1]) < MIN and len(out[-1][1]) + len(text) + 2 <= MAX:
            out[-1] = (join(out[-1][0], loc), out[-1][1] + "\n\n" + text)
        else:
            out.append((loc, text))
    return out
