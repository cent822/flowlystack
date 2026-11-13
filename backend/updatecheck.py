"""The update notice: is there a newer FlowlyStack release? (stdlib-only)

The SERVER asks GitHub (never the browser), at most once a day, and keeps the answer in `<settings dir>/update.json`:
`{checked_at, failed_at, latest, url, dismissed}`. The request is a plain GET: no cookie, no id, nothing about the user or the
data, and a generic User-Agent without the version. Offline or any error: the old answer stays and nothing is shown; the next try
waits an hour. Switch off with Settings > Updates or FLOWLYSTACK_UPDATE_CHECK=off: then no request is ever made.
The app only TELLS the user. It never downloads or installs anything.

`FLOWLYSTACK_UPDATE_URL` points the check at another address (tests use a fake local server).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import appinfo, settings
from .config import SETTINGS_DIR

URL = "https://api.github.com/repos/cent822/flowlystack/releases/latest"
PAGE = "https://github.com/cent822/flowlystack/releases/latest"
TTL = 24 * 3600        # ask GitHub at most once a day
RETRY = 3600           # after a failure, wait an hour
TIMEOUT = 4
_LOCK = threading.Lock()
_busy = False
_VER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _file() -> Path:
    return SETTINGS_DIR / "update.json"


def enabled() -> bool:
    return bool(settings.get("updates.check"))


def parse(v) -> tuple | None:
    """`"v0.1.10"` -> (0, 1, 10); anything that is not a plain x.y.z (a pre-release like 1.0.0-rc1 included) -> None."""
    m = _VER.match(v.strip()) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(latest, current) -> bool:
    a, b = parse(latest), parse(current)
    return bool(a and b and a > b)


def _read() -> dict:
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    try:
        _file().parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_file().parent, prefix=".update-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, _file())
    except OSError:
        pass   # a read-only data folder only means the answer is not remembered


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # an answer that moves somewhere else is not an answer
        return None


def _fetch() -> dict | None:
    """One GET. Returns {latest, url} for a real release (not a draft, not a pre-release) or None."""
    req = urllib.request.Request(os.environ.get("FLOWLYSTACK_UPDATE_URL") or URL, headers={"User-Agent": "FlowlyStack", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read(200_000).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name")
    if not parse(tag):
        return None
    url = data.get("html_url")
    return {"latest": tag.strip().lstrip("vV"), "url": url if isinstance(url, str) and url.startswith("https://github.com/cent822/") else PAGE}


def refresh() -> None:
    """Ask GitHub now and store the answer (the background thread calls this; tests call it directly)."""
    global _busy
    try:
        got = _fetch()
        with _LOCK:
            d = _read()
            if got:
                if d.get("latest") != got["latest"]:
                    d["dismissed"] = ""
                d.update(got, checked_at=time.time(), failed_at=0)
            else:
                d["failed_at"] = time.time()
            _write(d)
    finally:
        _busy = False


def _stale(d: dict, now: float) -> bool:
    if d.get("failed_at") and now - d["failed_at"] < RETRY:
        return False
    return now - (d.get("checked_at") or 0) >= TTL


def status(background: bool = True) -> dict:
    """What the page needs, from the stored answer at once; a stale answer starts one refresh in the background."""
    global _busy
    current = appinfo.version()
    docker = bool(os.environ.get("FLOWLYSTACK_IN_DOCKER"))
    if not enabled():
        return {"enabled": False, "current": current, "latest": "", "newer": False, "url": PAGE, "in_docker": docker, "dismissed": False}
    d = _read()
    if _stale(d, time.time()) and not _busy:
        _busy = True
        if background:
            threading.Thread(target=refresh, daemon=True).start()
        else:
            refresh()
            d = _read()
    latest = d.get("latest") or ""
    return {"enabled": True, "current": current, "latest": latest, "newer": is_newer(latest, current), "url": d.get("url") or PAGE,
            "in_docker": docker, "dismissed": bool(latest) and d.get("dismissed") == latest}


def dismiss(version: str) -> None:
    """Remember that the toast for this version was closed (the badge stays until the user updates)."""
    with _LOCK:
        d = _read()
        if version and version == d.get("latest"):
            d["dismissed"] = version
            _write(d)
