"""The "What's new" dialog after an update: which releases the user has not been shown yet.

The server remembers the last version it showed (`<data dir>/whatsnew.json`, one small file next to update.json), so the dialog appears once per
version for the whole install, not once per browser. Nothing here touches the network: the notes come from the bundled CHANGELOG.md.
A fresh install records the current version at sign-up and shows nothing (a new user does not need release notes on day one); an install with
no record yet (it was updated from a version that did not have this dialog) is shown the current release."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from . import appinfo, settings
from .config import SETTINGS_DIR
from .updatecheck import is_newer, parse

MAX = 3   # a user who skipped several versions sees at most the newest three
_LOCK = threading.Lock()


def _file() -> Path:
    return SETTINGS_DIR / "whatsnew.json"


def enabled() -> bool:
    return bool(settings.get("updates.whatsnew"))


def _seen() -> str:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        v = d.get("seen") if isinstance(d, dict) else ""
        return v if isinstance(v, str) else ""
    except (OSError, ValueError):
        return ""


def _write(version: str) -> None:
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_file().parent, prefix=".whatsnew-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"seen": version}, f)
        os.replace(tmp, _file())
    except OSError:
        pass   # a read-only data folder only means the dialog may show again


def pending() -> dict:
    """`{enabled, version, releases}`: the releases newer than the last one shown and not newer than the running version, newest first."""
    current = appinfo.version()
    if not enabled() or not parse(current):
        return {"enabled": enabled(), "version": current, "releases": []}
    seen = _seen()
    rels = [r for r in appinfo.changelog() if parse(r["version"]) and not is_newer(r["version"], current)]
    if seen:
        rels = [r for r in rels if is_newer(r["version"], seen)]
    else:
        rels = rels[:1]   # no record: the user came from a version without this dialog; the release they just got is enough
    return {"enabled": True, "version": current, "releases": rels[:MAX]}


def mark(version: str | None = None) -> None:
    """Remember that the notes up to this version were shown (the running version when none is given). Never moves backwards."""
    v = (version or appinfo.version()).strip()
    if not parse(v) or is_newer(v, appinfo.version()):   # a version this app does not have yet is never recorded
        return
    with _LOCK:
        old = _seen()
        if not old or is_newer(v, old):
            _write(v)
