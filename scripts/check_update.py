#!/usr/bin/env python3
"""Checks the update notice (backend/updatecheck.py), stdlib only, no server, temp dir. GitHub is replaced by a fake local server:
this check never makes a real request.
    python3 scripts/check_update.py"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = TMP   # before the backend is imported: settings and update.json go here
os.environ.pop("FLOWLYSTACK_UPDATE_CHECK", None)
os.environ.pop("FLOWLYSTACK_IN_DOCKER", None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import appinfo, settings, updatecheck as uc  # noqa: E402

CUR = appinfo.version()
REPLY = {"code": 200, "body": {"tag_name": "v99.0.0", "html_url": "https://github.com/cent822/flowlystack/releases/tag/v99.0.0", "draft": False, "prerelease": False}, "delay": 0}
SEEN = []   # (path, headers) of every request the fake got


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        SEEN.append((self.path, dict(self.headers)))
        time.sleep(REPLY["delay"])
        if REPLY["code"] == 302:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()
            return
        body = json.dumps(REPLY["body"]).encode()
        self.send_response(REPLY["code"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["FLOWLYSTACK_UPDATE_URL"] = f"http://127.0.0.1:{srv.server_address[1]}/latest"


def reset(code=200, **body):
    REPLY.update(code=code, delay=0)
    REPLY["body"] = {"tag_name": "v99.0.0", "html_url": "https://github.com/cent822/flowlystack/releases/tag/v99.0.0", "draft": False, "prerelease": False, **body}
    SEEN.clear()
    uc._busy = False
    try:
        uc._file().unlink()
    except OSError:
        pass
    os.environ.pop("FLOWLYSTACK_UPDATE_CHECK", None)
    settings.update("updates", {"check": True})


def step(msg):
    print("ok  ", msg)


# --- the version compare ---
assert uc.parse("v0.1.10") == (0, 1, 10) and uc.parse("0.1.2") == (0, 1, 2)
assert uc.parse("1.0.0-rc1") is None and uc.parse("latest") is None and uc.parse(None) is None and uc.parse("1.2") is None
assert uc.is_newer("0.1.10", "0.1.9") and not uc.is_newer("0.1.9", "0.1.10")   # a real compare, not text
assert not uc.is_newer("0.1.2", "0.1.2") and not uc.is_newer("0.1.1", "0.1.2") and not uc.is_newer("1.0.0-rc1", "0.1.2") and not uc.is_newer("0.2.0", "unknown")
step("version compare: 0.1.10 > 0.1.9, same or older or odd tags are never newer")

# --- a newer release is found, asked for once, and remembered ---
reset()
assert uc.status(background=False)["newer"] is True
st = uc.status(background=False)
assert st == {"enabled": True, "current": CUR, "latest": "99.0.0", "newer": True, "url": "https://github.com/cent822/flowlystack/releases/tag/v99.0.0", "in_docker": False, "dismissed": False}, st
assert len(SEEN) == 1, "the second call must come from the stored answer"
step("newer release: found, stored, one request for two calls")

# --- nothing about the user in the request ---
path, hdr = SEEN[0]
low = {k.lower(): v for k, v in hdr.items()}
assert low.get("user-agent") == "FlowlyStack", low
assert not {"cookie", "authorization", "referer", "x-forwarded-for"} & set(low), low
assert CUR not in json.dumps(hdr) and path == "/latest", (path, hdr)
step("the request is a plain GET: generic User-Agent, no cookie, no id, no version")

# --- a day later it asks again; a failure waits an hour; offline is silent ---
d = json.loads(uc._file().read_text())
d["checked_at"] = time.time() - uc.TTL - 5
uc._file().write_text(json.dumps(d))
REPLY["body"]["tag_name"] = "v99.1.0"
assert uc.status(background=False)["latest"] == "99.1.0" and len(SEEN) == 2
d = json.loads(uc._file().read_text())
d["checked_at"] = time.time() - uc.TTL - 5
uc._file().write_text(json.dumps(d))
REPLY["code"] = 500
before = len(SEEN)
st = uc.status(background=False)
assert len(SEEN) == before + 1 and st["latest"] == "99.1.0" and st["newer"] is True, st   # the old answer stays, nothing is shown as an error
uc.status(background=False)
assert len(SEEN) == before + 1, "after a failure the next try waits (an hour), not every call"
step("stale after a day: asks again; a failure keeps the old answer and backs off")

# --- not offered: draft, pre-release, a tag that is not x.y.z, a redirect, a broken answer ---
for label, kw in (("draft", {"draft": True}), ("pre-release", {"prerelease": True}), ("odd tag", {"tag_name": "nightly"}), ("rc tag", {"tag_name": "v1.0.0-rc1"})):
    reset(**kw)
    st = uc.status(background=False)
    assert st["newer"] is False and st["latest"] == "", (label, st)
reset(code=302)
assert uc.status(background=False)["newer"] is False   # an answer that moves elsewhere is not followed
reset()
REPLY["body"] = ["not", "an", "object"]
assert uc.status(background=False)["newer"] is False
reset(tag_name=f"v{CUR}")
assert uc.status(background=False)["newer"] is False   # the same version: nothing to say
step("draft, pre-release, odd tags, a redirect and a broken answer are never offered; the same version is not news")

# --- a link that does not point at the project is replaced ---
reset(html_url="https://evil.example/phish")
assert uc.status(background=False)["url"] == uc.PAGE
step("the link shown always points at the project's releases")

# --- the toast is shown once per version (dismiss), and a newer one is new again ---
reset()
uc.status(background=False)
uc.dismiss("99.0.0")
assert uc.status(background=False)["dismissed"] is True
uc.dismiss("1.2.3")   # not the latest: ignored
assert uc.status(background=False)["dismissed"] is True
d = json.loads(uc._file().read_text())
d["checked_at"] = time.time() - uc.TTL - 5
uc._file().write_text(json.dumps(d))
REPLY["body"]["tag_name"] = "v99.2.0"
st = uc.status(background=False)
assert st["latest"] == "99.2.0" and st["dismissed"] is False and st["newer"] is True, st
step("dismiss is remembered per version; the next release is shown again")

# --- the switch: off means NO request, from Settings or from the environment (which wins) ---
reset()
settings.update("updates", {"check": False})
st = uc.status(background=False)
assert st["enabled"] is False and st["newer"] is False and not SEEN
settings.update("updates", {"check": True})
os.environ["FLOWLYSTACK_UPDATE_CHECK"] = "off"
st = uc.status(background=False)
assert st["enabled"] is False and not SEEN, "the environment beats the setting"
os.environ.pop("FLOWLYSTACK_UPDATE_CHECK")
settings.update("updates", {"check": False})   # Settings refuses to save a value the environment decides, so set it first
os.environ["FLOWLYSTACK_UPDATE_CHECK"] = "on"
assert uc.status(background=False)["enabled"] is True and len(SEEN) == 1
os.environ["FLOWLYSTACK_UPDATE_CHECK"] = "maybe"   # an unusable value is skipped, never fatal: the stored setting (off) applies
assert uc.status(background=False)["enabled"] is False
os.environ.pop("FLOWLYSTACK_UPDATE_CHECK")
assert settings.resolve("updates.check") == (False, "settings")
settings.update("updates", {"check": True})
assert settings.resolve("updates.check") == (True, "settings") and settings.LEAVES["updates.check"][0] is True   # the default is ON
step("switch off = zero requests; the environment beats Settings; the default is on")

# --- the page never waits for GitHub ---
reset()
REPLY["delay"] = 1.5
t = time.time()
st = uc.status()   # background: answers from the (empty) store at once
assert time.time() - t < 0.5 and st["newer"] is False and st["latest"] == "", st
time.sleep(2.2)
assert uc.status()["newer"] is True   # the refresh finished in the background
step("a slow GitHub never slows the page: the answer comes from the store, the refresh runs in the background")

# --- Docker is reported (the toast shows its two commands) ---
os.environ["FLOWLYSTACK_IN_DOCKER"] = "1"
assert uc.status(background=False)["in_docker"] is True
os.environ.pop("FLOWLYSTACK_IN_DOCKER")
step("in_docker is reported")

# --- a read-only data folder only means nothing is remembered ---
reset()
saved = uc._file
uc._file = lambda: Path("/proc/none/update.json")
try:
    assert uc.status(background=False)["enabled"] is True
finally:
    uc._file = saved
step("an unwritable data folder never breaks the check")

# --- the files stay inside the temp folder, and the user's real data is untouched ---
assert uc._file().parent == Path(TMP)
step("update.json lives in the settings folder")
print("\ncheck_update: all passed")
