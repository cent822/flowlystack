#!/usr/bin/env python3
"""Checks the owner profile: the picture store (backend/profilestore.py) and renaming the owner (auth.change_username). Stdlib only, temp dir.
    python3 scripts/check_profile.py
With BASE=http://127.0.0.1:8799 it also runs the API flow against a TEST server that has the login ON (no FLOWLYSTACK_AUTH=off) and its own
empty FLOWLYSTACK_SETTINGS_DIR and FLOWLYSTACK_PROMPTS_DIR: it creates the owner there. Never point BASE at the real server."""
import json
import os
import struct
import sys
import tempfile
import urllib.error
import urllib.request
import zlib
from http.cookiejar import CookieJar
from pathlib import Path

TMP = tempfile.mkdtemp()
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = TMP   # before the backend is imported: config reads it once
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import auth, profilestore  # noqa: E402


def png(w=64, h=64) -> bytes:
    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x20\x80\xa0\xff" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def refuses(data, why):
    try:
        profilestore.check_png(data)
    except profilestore.ProfileError:
        return
    raise AssertionError("accepted: " + why)


# ---- the picture store
good = png()
profilestore.check_png(good)
refuses(b"", "empty")
refuses(None, "None")
refuses(b"GIF89a" + b"\x00" * 100, "not a PNG")
refuses(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "SVG")
refuses(good[:-12], "no closing IEND chunk (truncated)")
refuses(png(16, 16), "too small")
refuses(png(600, 600), "too large in pixels")
refuses(good + b"\x00" * profilestore.MAX_BYTES, "too many bytes")
assert profilestore.read() is None and profilestore.version() is None
v1 = profilestore.save(good)
assert profilestore.read() == good and v1 == profilestore.version()
assert (Path(TMP) / "avatar.png").stat().st_mode & 0o077 == 0, "the file must be owner-only"
v2 = profilestore.save(png(128, 128))
assert v2 != v1 and profilestore.read() != good, "a new picture is a new version"
profilestore.remove()
profilestore.remove()   # removing nothing is fine
assert profilestore.read() is None and profilestore.version() is None
assert not list(Path(TMP).glob("avatar.png.*")), "no temp files left behind"

# ---- renaming the owner
tok = auth.signup("alice", "correct horse battery")
other = auth.login("alice", "correct horse battery", "c1")
assert auth.session_user(tok) == "alice"
for bad in ("", "ab", "a b", "-lead", "x" * 65, None, 5):
    try:
        auth.change_username(tok, "correct horse battery", bad, "c1")
    except auth.AuthError:
        continue
    raise AssertionError(f"accepted name {bad!r}")
try:
    auth.change_username(tok, "wrong password", "bobby", "c2")
    raise AssertionError("renamed with a wrong password")
except auth.AuthError as e:
    assert e.status == 403
for _ in range(5):   # wrong passwords count toward the lockout, like every other password check
    try:
        auth.change_username(tok, "nope nope nope", "bobby", "c3")
    except auth.AuthError:
        pass
try:
    auth.change_username(tok, "correct horse battery", "bobby", "c3")
    raise AssertionError("a locked-out client renamed")
except auth.AuthError as e:
    assert e.status == 429, e.status
try:
    auth.change_username("not-a-session", "correct horse battery", "bobby", "c4")
    raise AssertionError("renamed without a session")
except auth.AuthError as e:
    assert e.status == 401
assert auth.change_username(tok, "correct horse battery", "Bobby.2", "c5") == "Bobby.2"
assert auth.session_user(tok) == "Bobby.2" and auth.session_user(other) == "Bobby.2", "sessions stay signed in under the new name"
auth.login("bobby.2", "correct horse battery", "c6")   # the login name is case-insensitive, as before
try:
    auth.login("alice", "correct horse battery", "c7")
    raise AssertionError("the old name still logs in")
except auth.AuthError:
    pass

# ---- the API, when a login-ON test server is running
base = os.environ.get("BASE")
if base:
    jar = CookieJar()
    me = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(opener, method, path, body=None, headers=None, raw=False):
        data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
        h = {"content-type": "application/json", **(headers or {})} if not isinstance(body, bytes) else (headers or {})
        try:
            r = opener.open(urllib.request.Request(base + path, data=data, method=method, headers=h), timeout=15)
            return r.status, (r.read() if raw else json.loads(r.read() or b"{}")), r.headers
        except urllib.error.HTTPError as e:
            return e.code, {}, e.headers

    st, out, _ = call(me, "POST", "/api/auth/signup", {"username": "carol", "password": "correct horse battery"})
    assert st == 200, (st, out)
    st, s, _ = call(me, "GET", "/api/auth/state")
    assert s["username"] == "carol" and s["avatar"] is None, s
    anon = urllib.request.build_opener()
    assert call(anon, "GET", "/api/profile/avatar")[0] == 401, "the picture needs a session"
    assert call(me, "GET", "/api/profile/avatar")[0] == 404
    for bad in (b"not a png", b"<svg/>", good[:-12]):
        assert call(me, "PUT", "/api/profile/avatar", bad, {"content-type": "image/png"})[0] == 400
    assert call(me, "PUT", "/api/profile/avatar", good, {"content-type": "image/png", "Origin": "https://evil.example"})[0] == 403, "cross-site write"
    st, out, _ = call(me, "PUT", "/api/profile/avatar", good, {"content-type": "image/png"})
    assert st == 200 and out["version"], (st, out)
    st, got, h = call(me, "GET", "/api/profile/avatar", raw=True)
    assert st == 200 and got == good and h["content-type"] == "image/png" and h["x-content-type-options"] == "nosniff", (st, dict(h))
    assert call(me, "GET", "/api/auth/state")[1]["avatar"] == out["version"]
    assert call(me, "POST", "/api/auth/username", {"password": "wrong password", "new": "dave"})[0] == 403
    assert call(anon, "POST", "/api/auth/username", {"password": "correct horse battery", "new": "dave"})[0] == 401
    st, out, _ = call(me, "POST", "/api/auth/username", {"password": "correct horse battery", "new": "dave"})
    assert st == 200 and out["username"] == "dave", (st, out)
    assert call(me, "GET", "/api/auth/state")[1]["username"] == "dave", "the session survives the rename"
    assert call(me, "DELETE", "/api/profile/avatar")[0] == 200
    assert call(me, "GET", "/api/profile/avatar")[0] == 404 and call(me, "GET", "/api/auth/state")[1]["avatar"] is None
    print("api: ok")

print("check_profile: ok")
