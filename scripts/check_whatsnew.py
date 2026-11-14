#!/usr/bin/env python3
"""Checks the What's new dialog logic (backend/whatsnew.py), stdlib only, no server, temp dir, no network.
    python3 scripts/check_whatsnew.py"""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = TMP   # before the backend is imported: settings and whatsnew.json go here
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import appinfo, settings, whatsnew as wn  # noqa: E402

REL = lambda v: {"version": v, "date": "2026-01-01", "intro": "", "sections": []}  # noqa: E731
appinfo.changelog = lambda root=None: [REL("0.1.6"), REL("0.1.5"), REL("0.1.4"), REL("0.1.3"), REL("0.1.2")]   # newest first, as the file is
RUN = {"v": "0.1.5"}
appinfo.version = lambda root=None: RUN["v"]


def reset(version="0.1.5"):
    RUN["v"] = version
    try:
        wn._file().unlink()
    except OSError:
        pass
    settings.update("updates", {"whatsnew": True})


def vers():
    return [r["version"] for r in wn.pending()["releases"]]


def step(msg):
    print("ok  ", msg)


# no record yet (updated from a version without the dialog): the release just got is shown, never the whole history
reset()
assert vers() == ["0.1.5"], vers()
step("no record: only the running release is shown (0.1.6 is not out in this copy, so it is never shown)")

# shown once: after it is marked nothing is pending, and the next release is new again
wn.mark("0.1.5")
assert vers() == []
RUN["v"] = "0.1.6"
assert vers() == ["0.1.6"]
step("once per version; the next version is new again")

# a skipped version shows each release since, newest first, at most three
reset("0.1.6")
wn.mark("0.1.2")
assert vers() == ["0.1.6", "0.1.5", "0.1.4"], vers()   # 0.1.3 is the fourth: left out
wn.mark("0.1.3")
assert vers() == ["0.1.6", "0.1.5", "0.1.4"]
wn.mark("0.1.5")
assert vers() == ["0.1.6"]
step("a skipped version lists the releases since, newest first, at most three")

# a fresh install: signing up records the running version, so nothing shows
reset()
wn.mark()
assert vers() == []
step("a fresh install (mark at sign-up) shows nothing")

# marks never move backwards or past the running version, and junk is ignored
wn.mark("0.1.2")
assert wn._seen() == "0.1.5"
wn.mark("9.9.9")
wn.mark("latest")
wn.mark("")
assert wn._seen() == "0.1.5"
step("marks never go back, never past the running version, and junk is ignored")

# the switch
reset()
settings.update("updates", {"whatsnew": False})
assert wn.pending() == {"enabled": False, "version": "0.1.5", "releases": []}
settings.update("updates", {"whatsnew": True})
assert settings.LEAVES["updates.whatsnew"][0] is True   # the default is ON
step("switch off shows nothing; the default is on")

# an unreadable version or a broken file never breaks it
reset("unknown")
assert wn.pending()["releases"] == []
reset()
wn._file().write_text("not json")
assert vers() == ["0.1.5"]
step("an unknown version or a broken file only means: no record")

# a read-only data folder never raises
saved = wn._file
wn._file = lambda: Path("/proc/none/whatsnew.json")
try:
    wn.mark("0.1.5")
finally:
    wn._file = saved
step("an unwritable data folder never breaks it")

assert wn._file().parent == Path(TMP)
step("whatsnew.json lives in the settings folder")
print("\ncheck_whatsnew: all passed")
