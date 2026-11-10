#!/usr/bin/env python3
"""Checks the version and release-notes reader (backend/appinfo.py), stdlib only, no server, temp dir.
    python3 scripts/check_about.py
With BASE=http://127.0.0.1:8799 (a TEST server with FLOWLYSTACK_AUTH=off) it also checks /api/about and /api/about/changelog."""
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import appinfo  # noqa: E402

SAMPLE = """# Changelog

## [Unreleased]
### New
- never shown

## [v0.2.0] - 2026-12-01
Second release, a little longer.
### New
- First thing
  that continues on a second line
- Second thing
### Heads up
- Be careful

## [0.1.0] - 2026-11-08
### Fixed
- Old fix
"""

# parsing
r = appinfo.parse_changelog(SAMPLE)
assert [x["version"] for x in r] == ["0.2.0", "0.1.0"], r             # Unreleased skipped, a leading v is dropped
assert r[0]["date"] == "2026-12-01" and r[0]["intro"] == "Second release, a little longer.", r[0]
assert [s["title"] for s in r[0]["sections"]] == ["New", "Heads up"]
assert r[0]["sections"][0]["items"] == ["First thing that continues on a second line", "Second thing"], r[0]["sections"][0]
assert r[1]["sections"][0] == {"title": "Fixed", "items": ["Old fix"]}
assert appinfo.parse_changelog("") == [] and appinfo.parse_changelog("no headings here") == []
assert appinfo.parse_changelog("## [1.0.0]\n### New\n- x")[0]["date"] == ""   # a release without a date is fine

# files: a temp root with and without them
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    assert appinfo.version(root) == "unknown" and appinfo.changelog(root) == []   # missing files never raise
    (root / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.8.7"\n')
    (root / "CHANGELOG.md").write_text(SAMPLE)
    assert appinfo.version(root) == "9.8.7" and len(appinfo.changelog(root)) == 2

# the real files agree with each other
real = appinfo.version()
assert real != "unknown" and real.count(".") == 2, real
notes = appinfo.changelog()
assert notes and notes[0]["version"] == real, f"CHANGELOG.md newest release {notes[0]['version'] if notes else None} must equal pyproject version {real}"
assert all(rel["sections"] and all(s["items"] for s in rel["sections"]) for rel in notes), "every release needs at least one item"

# the API, when a test server is running
base = os.environ.get("BASE")
if base:
    get = lambda p: json.load(urllib.request.urlopen(base + p, timeout=10))
    a = get("/api/about")
    assert a == {"name": "FlowlyStack", "version": real}, a
    c = get("/api/about/changelog")
    assert c["version"] == real and c["releases"][0]["version"] == real, c
    print("api: ok")

print("check_about: ok")
