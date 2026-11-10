"""Lattice, shared references (Batch 2 of the explicit lines). Standard library only, no model.

Finds the things a prompt or document names literally: a web link, a file path or file name, a ticket id (`ABC-123`). Two items that name the same thing
are connected through one `reference` node (see kgraph_build.py). Matching is by pattern, so it can be wrong about what a string is; it is never wrong
about what the text says: the string is there. `extract` returns {key: (display, subtype)} with `key` = "link:...", "file:..." or "ticket:...".
`file_names` lists the bare file names a text mentions (used to see which prompts name a document of a collection).
"""
from __future__ import annotations

import re

MAX_DISPLAY = 120
# file extensions that make a bare word ("home.js") count as a file name; a path with a folder in it may have any extension
EXT = ("py js mjs cjs ts tsx jsx css scss html htm md mdx json jsonl yaml yml toml ini cfg conf env sh zsh bash sql rs java kt swift cpp hpp rb php lua ipynb "
       "txt csv tsv log pdf docx xlsx pptx png jpg jpeg svg gif lock xml plist").split()
# names that look like a file but are a product ("Node.js")
NOT_FILES = frozenset("node.js vue.js next.js react.js three.js d3.js express.js nuxt.js angular.js backbone.js ember.js chart.js p5.js alpine.js".split())
# prefixes of "XXX-123" that are not tickets
NOT_TICKETS = frozenset("UTF ISO SHA GPT AES MD CVE RFC PEP USB IPV TLS HTTP WIN IE".split())

_URL = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.I)
_DIR_PATH = re.compile(r"(?<![\w.@+/~-])(?:~/|\./|\.\./|/)?(?:[\w.@+-]+/)+[\w.@+-]*\.[A-Za-z][A-Za-z0-9]{0,7}\b")
_BARE = re.compile(r"(?<![\w.@+~-])(?<![\w@+-]/)(?:\./)?[\w@+-][\w.@+-]*\.(?:" + "|".join(EXT) + r")\b", re.I)
_TICKET = re.compile(r"(?<![\w-])([A-Z][A-Z0-9]{1,9})-(\d{1,6})(?![\w-])")
_NAME = re.compile(r"[\w@+-][\w.@+-]*\.[A-Za-z0-9]{2,8}")


def _clip(s: str) -> str:
    return s if len(s) <= MAX_DISPLAY else s[:MAX_DISPLAY - 1] + "…"


def _link(raw: str):
    u = raw.rstrip(".,;:!?*_'\"")
    u = u.split("#", 1)[0]
    m = re.match(r"https?://([^/?]+)([^?]*)(\?.*)?$", u, re.I)
    if not m:
        return None
    host, path, query = m.group(1).lower(), m.group(2).rstrip("/"), m.group(3) or ""
    if "." not in host:
        return None
    return "link:" + host + path + query, _clip(host + path + query)


def extract(text: str) -> dict:
    """{key: (display, subtype)} for every link, file and ticket the text names (each once, the first spelling is the display)."""
    out: dict = {}
    if not text:
        return out
    for m in _URL.finditer(text):
        r = _link(m.group(0))
        if r:
            out.setdefault(r[0], (r[1], "link"))
    rest = _URL.sub(" ", text)
    for m in _DIR_PATH.finditer(rest):
        p = m.group(0)
        key = p[2:] if p.startswith("./") else p
        if key.count("/") >= 1 and not key.endswith("/"):
            out.setdefault("file:" + key.casefold(), (_clip(key), "file"))
    for m in _BARE.finditer(rest):
        p = m.group(0)
        p = p[2:] if p.startswith("./") else p
        if p.casefold() in NOT_FILES:
            continue
        out.setdefault("file:" + p.casefold(), (_clip(p), "file"))
    for m in _TICKET.finditer(rest):
        if m.group(1) not in NOT_TICKETS:
            out.setdefault("ticket:" + m.group(0), (m.group(0), "ticket"))
    return out


def file_names(text: str) -> set:
    """The bare file names (case folded) a text mentions, also the last part of a path: `Q3.pdf`, `notes.txt`."""
    names = set()
    for m in _NAME.finditer(_URL.sub(" ", text or "")):
        names.add(m.group(0).casefold())
    return names
