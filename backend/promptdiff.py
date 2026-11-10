"""Side-by-side line diff with word-level highlights, as plain data for the compare view."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_TOKEN = re.compile(r"\s+|\w+|[^\w\s]")


def _inline(a: str, b: str) -> tuple[list, list]:
    ta, tb = _TOKEN.findall(a), _TOKEN.findall(b)
    sa, sb = [], []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        ch = 0 if tag == "equal" else 1
        if i2 > i1:
            sa.append(["".join(ta[i1:i2]), ch])
        if j2 > j1:
            sb.append(["".join(tb[j1:j2]), ch])
    return sa, sb


def diff_rows(a: str, b: str, context: int = 3) -> list[dict]:
    """Rows of {t: eq|chg|del|add|gap, a: {n, segs}|None, b: {n, segs}|None}. segs = [[text, changed 0/1]]."""
    al, bl = a.split("\n"), b.split("\n")
    rows: list[dict] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, al, bl, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append({"t": "eq", "a": {"n": i1 + k + 1, "segs": [[al[i1 + k], 0]]},
                             "b": {"n": j1 + k + 1, "segs": [[bl[j1 + k], 0]]}})
            continue
        n = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for k in range(n):
            sa, sb = _inline(al[i1 + k], bl[j1 + k])
            rows.append({"t": "chg", "a": {"n": i1 + k + 1, "segs": sa}, "b": {"n": j1 + k + 1, "segs": sb}})
        for k in range(n, i2 - i1):
            rows.append({"t": "del", "a": {"n": i1 + k + 1, "segs": [[al[i1 + k], 1]]}, "b": None})
        for k in range(n, j2 - j1):
            rows.append({"t": "add", "a": None, "b": {"n": j1 + k + 1, "segs": [[bl[j1 + k], 1]]}})
    return _collapse(rows, context)


def _collapse(rows: list[dict], context: int) -> list[dict]:
    keep = [False] * len(rows)
    for i, r in enumerate(rows):
        if r["t"] != "eq":
            for j in range(max(0, i - context), min(len(rows), i + context + 1)):
                keep[j] = True
    if not any(keep):                       # identical texts: show the first lines only
        return rows[: context * 2] + ([{"t": "gap", "n": len(rows) - context * 2}] if len(rows) > context * 2 else [])
    out, hidden = [], 0
    for r, k in zip(rows, keep):
        if k:
            if hidden:
                out.append({"t": "gap", "n": hidden})
                hidden = 0
            out.append(r)
        else:
            hidden += 1
    if hidden:
        out.append({"t": "gap", "n": hidden})
    return out
