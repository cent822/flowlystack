"""The app's own version and release notes (stdlib-only).

One version number lives in `pyproject.toml` (`version = "x.y.z"`); the Settings > About page, the account menu, the API
and (later) the Docker image tag and the update check all read it from here. Release notes live in `CHANGELOG.md` at the
repository root in the Keep a Changelog layout and are bundled with the app, so "What's new" works offline:

    ## [0.1.0] - 2026-11-08
    A sentence or two about the release (optional).
    ### New
    - One line per change. A line that continues the one above is indented.

`### New`, `### Improved`, `### Fixed` and `### Heads up` are the usual headings, but any heading is shown as written.
An `## [Unreleased]` block is never shown. Nothing here reads prompts, settings or the network.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "FlowlyStack"
_VERSION_RE = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.M)
_RELEASE_RE = re.compile(r"^##\s+\[([^\]]+)\](?:\s*-\s*(\S+))?\s*$")


def version(root: Path = ROOT) -> str:
    """The version in pyproject.toml, or "unknown" when the file cannot be read."""
    try:
        m = _VERSION_RE.search((root / "pyproject.toml").read_text(encoding="utf-8"))
    except OSError:
        return "unknown"
    return m.group(1) if m else "unknown"


def parse_changelog(text: str) -> list[dict]:
    """Release notes as `[{version, date, intro, sections: [{title, items}]}]`, newest first as written in the file."""
    releases: list[dict] = []
    rel = sec = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _RELEASE_RE.match(line)
        if m:
            name = m.group(1).strip()
            if name.lower() == "unreleased":
                rel = sec = None
                continue
            rel = {"version": name.lstrip("vV"), "date": m.group(2) or "", "intro": "", "sections": []}
            releases.append(rel)
            sec = None
            continue
        if rel is None:
            continue
        if line.startswith("### "):
            sec = {"title": line[4:].strip(), "items": []}
            rel["sections"].append(sec)
        elif line.lstrip().startswith(("- ", "* ")) and not line.startswith(" ") and sec is not None:
            sec["items"].append(line.lstrip()[2:].strip())
        elif line.startswith((" ", "\t")) and line.strip() and sec is not None and sec["items"]:
            sec["items"][-1] += " " + line.strip()
        elif line.strip() and sec is None:
            rel["intro"] = (rel["intro"] + " " + line.strip()).strip()
    return releases


def changelog(root: Path = ROOT) -> list[dict]:
    try:
        return parse_changelog((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    except OSError:
        return []
