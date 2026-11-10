#!/usr/bin/env python3
"""Checks for Lattice's reference finder, backend/kgraph_refs.py (Batch 2 of the explicit lines). Plain asserts, standard library only:

    python3 scripts/check_kgraph_refs.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.kgraph_refs import extract, file_names  # noqa: E402


def step(msg: str) -> None:
    print("ok  ", msg)


def keys(t):
    return set(extract(t))


# links: scheme and host case folded, fragment and trailing punctuation dropped, trailing slash dropped, query kept
assert keys("see https://GitHub.com/foo/bar/issues/12#note.") == {"link:github.com/foo/bar/issues/12"}
assert keys("(https://example.com/a/) and https://example.com/a") == {"link:example.com/a"}, "same link twice is one"
assert keys("https://example.com/s?q=1") == {"link:example.com/s?q=1"}
assert keys("http://localhost:8372/x") == {"link:localhost:8372/x"} or keys("http://localhost:8372/x") == set(), "a host without a dot is not a link"
assert keys("https://localhost/x") == set()
step("links: host lower-cased, fragment, trailing punctuation and slash dropped, the query kept, no dot in the host means no link")

# files: a path with a folder, a bare file name with a known extension
assert keys("Fix backend/main.py please") == {"file:backend/main.py"}
assert keys("./run.sh and run.sh") == {"file:run.sh"}, "a leading ./ is dropped"
assert keys("open /Users/alice/a.b.txt") == {"file:/users/alice/a.b.txt"}
assert keys("home.js and Home.JS") == {"file:home.js"}, "case folded, shown as first written"
assert extract("Home.JS and home.js")["file:home.js"][0] == "Home.JS"
assert keys("we use Node.js and Vue.js") == set(), "products that look like files are skipped"
assert keys("1.5/2.5 and/or e.g. w/ so") == set(), "numbers, and/or and e.g. are not paths"
assert keys("see https://a.com/x.png only") == {"link:a.com/x.png"}, "a file inside a link belongs to the link"
step("files: paths with a folder and bare names with a known extension; ./ dropped; case folded; products and numbers skipped; the inside of a link is not a file")

# tickets
assert keys("fix PROJ-123 and PROJ-123 again, also AB-9") == {"ticket:PROJ-123", "ticket:AB-9"}
assert keys("UTF-8 SHA-256 GPT-4 CVE-2024 ISO-8859") == set(), "known non-ticket prefixes are skipped"
assert keys("abc-123 lower case") == set()
step("tickets: ABC-123 style, each once; UTF-8, SHA-256 and friends are not tickets")

# bare file names for matching documents
assert file_names("see notes.txt and docs/Q3.pdf, e.g. https://a.com/x.png") == {"notes.txt", "q3.pdf"}
assert extract("") == {} and extract(None) == {}
step("file_names gives the bare names (case folded, also the end of a path, never from a link); an empty text gives nothing")

# a long path is clipped in the display only
long = "a/" * 80 + "x.py"
(k, (disp, sub)), = extract(long).items()
assert len(disp) <= 120 and disp.endswith("…") and sub == "file"
step("a very long name is clipped for display")

print("all reference checks passed")
