#!/usr/bin/env python3
"""Checks for the login routes and the gate (/api/auth, backend/auth_api.py). Plain asserts, standard library only.

Needs up to three THROWAWAY servers (the two-step flow runs on the trusted-proxy one, so give it BASE_TRUSTED), each with its own empty settings folder (the check signs up an owner there), never your real one:

    A=$(mktemp -d); B=$(mktemp -d); C=$(mktemp -d); P=$(mktemp -d)
    env FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 FLOWLYSTACK_SETTINGS_DIR=$A PORT=8799 ./run.sh &                              # auth on (required)
    env FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 FLOWLYSTACK_SETTINGS_DIR=$B PORT=8798 FLOWLYSTACK_TRUST_PROXY=1 ./run.sh &    # behind a trusted proxy (optional)
    env FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 FLOWLYSTACK_SETTINGS_DIR=$C PORT=8797 FLOWLYSTACK_AUTH=off ./run.sh &         # gate off (optional)
    FLOWLYSTACK_SETTINGS_DIR=$A BASE=http://127.0.0.1:8799 BASE_TRUSTED=http://127.0.0.1:8798 BASE_OFF=http://127.0.0.1:8797 \\
      FLOWLYSTACK_TRUSTED_DIR=$B python3 scripts/check_auth_api.py
"""
import base64
import hashlib
import hmac
import http.client
import json
import re
import os
import socket
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
DIR = Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"])
assert not (DIR / "auth.json").exists(), "the settings folder must start empty (no account yet)"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(method, path, body=None, expect=200, cookie=None, headers=None, base=None):
    h = {"Content-Type": "application/json", **(headers or {})}
    if cookie:
        h["Cookie"] = cookie
    req = urllib.request.Request((base or BASE) + path, method=method, headers=h,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        r = OPENER.open(req, timeout=30)
        code, text, hdr = r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        code, text, hdr = e.code, e.read(), e.headers
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {text[:200]!r}"
    try:
        data = json.loads(text) if text else None
    except ValueError:
        data = None
    return data, hdr


def set_cookie(hdr):
    raw = hdr.get("Set-Cookie") or ""
    return raw.split(";")[0], raw


def step(msg):
    print("ok  ", msg)


# --- signed out: everything is closed, only the login page and its files are open
d, _ = call("GET", "/api/auth/state")
assert d == {"enabled": True, "needs_setup": True, "signed_in": False, "username": ""}, d
for p in ("/api/overview", "/api/settings", "/api/studio", "/api/linkshell/projects", "/api/stream", "/api/sources"):
    call("GET", p, expect=401)
call("PUT", "/api/settings/assistant", {"temperature": 0.9}, expect=401)
_, h = call("GET", "/", expect=302)
assert h["Location"] == "/login", h["Location"]
_, h = call("GET", "/index.html", expect=302)
assert h["Location"].startswith("/login?next="), h["Location"]
_, h = call("GET", "/js/main.js", expect=302)
call("GET", "/login", expect=200)
call("GET", "/css/tokens.css", expect=200)
step("signed out: /api and the live stream answer 401, pages redirect to /login, the login page and its css are open")

# --- sign-up
call("POST", "/api/auth/signup", {"username": "alice", "password": "correct horse"}, expect=403,
     headers={"X-Forwarded-For": "203.0.113.9"})
assert not (DIR / "auth.json").exists()
step("sign-up through a proxy (any forwarded header) is refused: create the account on the server itself")
d, _ = call("POST", "/api/auth/signup", {"username": "alice", "password": "short"}, expect=400)
assert "at least 8" in d["detail"]
call("POST", "/api/auth/signup", {"username": "alice"}, expect=400)
d, h = call("POST", "/api/auth/signup", {"username": "alice", "password": "correct horse"})
cookie, raw = set_cookie(h)
assert d == {"ok": True, "username": "alice"} and re.match(r"flowlystack_session_[0-9a-f]{8}=", cookie) and len(cookie) > 40, raw
CNAME = cookie.split("=")[0]   # this install's cookie name
low = raw.lower()
assert "httponly" in low and "samesite=lax" in low and "path=/" in low and "secure" not in low and "max-age=2592000" in low, raw
call("POST", "/api/auth/signup", {"username": "other", "password": "another pass1"}, expect=403, cookie=cookie)
call("POST", "/api/auth/signup", {"username": "other", "password": "another pass1"}, expect=403)
step("sign-up creates the owner and sets an HttpOnly, SameSite=Lax cookie (no Secure over plain http); a second sign-up is 403")

# --- signed in
d, _ = call("GET", "/api/auth/state", cookie=cookie)
assert d["signed_in"] and d["username"] == "alice" and not d["needs_setup"]
call("GET", "/api/settings", cookie=cookie)
call("GET", "/api/overview", cookie=cookie)
call("GET", "/", cookie=cookie)
call("GET", "/api/settings", cookie=CNAME + "=forged", expect=401)
call("GET", "/api/settings", cookie="flowlystack_session=" + cookie.split("=", 1)[1], expect=401)   # the old fixed name is not read any more
step("a cookie of another install (or the old fixed name) is not a session")
u = urlparse(BASE)
c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
c.request("GET", "/api/stream", headers={"Cookie": cookie})
r = c.getresponse()
assert r.status == 200 and "text/event-stream" in r.getheader("Content-Type"), r.status
assert b"retry:" in r.read1(64)
c.close()
step("signed in: the app and the live stream work; a forged cookie is 401")

# --- CSRF: a write that names another site as its origin is refused
call("PUT", "/api/settings/assistant", {"temperature": 0.5}, expect=403, cookie=cookie, headers={"Origin": "https://evil.example"})
call("PUT", "/api/settings/assistant", {"temperature": 0.5}, expect=403, cookie=cookie, headers={"Origin": "null"})
call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"}, expect=403, headers={"Origin": "https://evil.example"})
call("PUT", "/api/settings/assistant", {"temperature": 0.5}, cookie=cookie, headers={"Origin": f"http://{u.netloc}"})
call("PUT", "/api/settings/assistant", {"temperature": 0.6}, cookie=cookie)
call("GET", "/api/settings", cookie=cookie, headers={"Origin": "https://evil.example"})
step("a cross-site Origin on a write is 403 (also 'null' and on login); same origin or no Origin works; reads are not affected")

# --- log out
c2 = set_cookie(call("POST", "/api/auth/login", {"username": "ALICE", "password": "correct horse"})[1])[0]
assert c2 != cookie
d, h = call("POST", "/api/auth/logout", cookie=c2)
assert CNAME + "=" in h["Set-Cookie"] and "max-age=0" in h["Set-Cookie"].lower()
call("GET", "/api/settings", cookie=c2, expect=401)
call("GET", "/api/settings", cookie=cookie)
step("logout ends that session only and clears the cookie")

# --- change password
c3 = set_cookie(call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"})[1])[0]
call("POST", "/api/auth/password", {"old": "wrong", "new": "brand new pass"}, expect=401)
call("POST", "/api/auth/password", {"old": "wrong", "new": "brand new pass"}, expect=403, cookie=c3)
call("POST", "/api/auth/password", {"old": "correct horse", "new": "x"}, expect=400, cookie=c3)
call("POST", "/api/auth/password", {"old": "correct horse", "new": "brand new pass"}, cookie=c3)
call("GET", "/api/settings", cookie=c3)
call("GET", "/api/settings", cookie=cookie, expect=401)
call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"}, expect=401)
call("POST", "/api/auth/login", {"username": "alice", "password": "brand new pass"})
step("change password: wrong old 403, not signed in 401, this session stays, the others are signed out")

# --- lockout (last: it locks this machine's address on the server for a minute)
for _ in range(5):
    call("POST", "/api/auth/login", {"username": "alice", "password": "nope nope nope"}, expect=401)
d, h = call("POST", "/api/auth/login", {"username": "alice", "password": "brand new pass"}, expect=429)
assert 1 <= int(h["Retry-After"]) <= 61
step("5 wrong passwords lock the client: 429 with Retry-After, even for the right password")

assert "auth.json" in {p.name for p in DIR.iterdir()} and (DIR / "auth.json").stat().st_mode & 0o077 == 0
assert "brand new pass" not in (DIR / "auth.json").read_text()

# --- behind a trusted proxy
TB = os.environ.get("BASE_TRUSTED")
if TB:
    TD = Path(os.environ["FLOWLYSTACK_TRUSTED_DIR"])
    xf = {"X-Forwarded-For": "198.51.100.7", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "app.example.org"}
    call("POST", "/api/auth/signup", {"username": "alice", "password": "correct horse"}, expect=403, headers=xf, base=TB)
    d, h = call("POST", "/api/auth/signup", {"username": "alice", "password": "correct horse"}, base=TB)
    assert "secure" not in h["Set-Cookie"].lower()      # signed up locally over http: no Secure
    d, h = call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"}, headers=xf, base=TB)
    tc, raw = set_cookie(h)
    assert "secure" in raw.lower(), raw                 # X-Forwarded-Proto https is believed
    call("PUT", "/api/settings/assistant", {"temperature": 0.5}, cookie=tc, headers={**xf, "Origin": "https://app.example.org"}, base=TB)
    call("PUT", "/api/settings/assistant", {"temperature": 0.5}, expect=403, cookie=tc, headers={**xf, "Origin": "https://evil.example"}, base=TB)
    for _ in range(5):
        call("POST", "/api/auth/login", {"username": "alice", "password": "bad bad bad"}, expect=401, headers={"X-Forwarded-For": "10.0.0.1, 192.0.2.50"}, base=TB)
    call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"}, expect=429, headers={"X-Forwarded-For": "10.9.9.9, 192.0.2.50"}, base=TB)
    call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"}, headers={"X-Forwarded-For": "10.0.0.1, 192.0.2.51"}, base=TB)
    step("trusted proxy: forwarded https gives a Secure cookie, forwarded host is the Origin match, the lockout is per client (right-most XFF entry)")
    # and without trust the same headers are ignored (server A)
    d, h = call("POST", "/api/auth/login", {"username": "alice", "password": "brand new pass"}, expect=429)  # still the locked local client
    step("untrusted server: forwarded headers do not change the client address (still locked)")

# --- two-step routes without a session (server A: nothing here counts as a failure)
for method, path in (("GET", "/api/auth/twostep"), ("POST", "/api/auth/twostep/start"), ("POST", "/api/auth/twostep/confirm"),
                     ("POST", "/api/auth/twostep/disable"), ("POST", "/api/auth/twostep/backup")):
    call(method, path, {} if method == "POST" else None, expect=401)
d, _ = call("GET", "/api/auth/state")
assert "twostep" not in d, d      # a visitor must not learn whether two-step is on
step("two-step routes need a session (401); the state answer does not reveal two-step to a visitor")


def hotp(secret, counter):
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 15
    return str((struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def code_at(secret, offset_steps=0):    # computed here, independently of the server's code, from the real clock
    return hotp(secret, int(time.time() // 30) + offset_steps)


# --- two-step flow, on the trusted-proxy server (each step uses its own client address, so the lockout does not mix them up)
if TB:
    xf = lambda n: {"X-Forwarded-For": f"203.0.113.{n}"}   # noqa: E731
    PWD = "correct horse"
    first = set_cookie(call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(1), base=TB)[1])[0]
    other = set_cookie(call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(2), base=TB)[1])[0]
    call("GET", "/api/auth/twostep", expect=401, base=TB)
    call("POST", "/api/auth/login/code", {"ticket": "nope", "code": "123456"}, expect=401, headers=xf(0), base=TB)
    d, _ = call("GET", "/api/auth/twostep", cookie=first, base=TB)
    assert d == {"enabled": False, "backup_left": 0}, d
    d, _ = call("GET", "/api/auth/state", cookie=first, base=TB)
    assert d["twostep"] is False
    call("POST", "/api/auth/twostep/start", {"password": "wrong"}, expect=403, cookie=first, headers=xf(3), base=TB)
    st, _ = call("POST", "/api/auth/twostep/start", {"password": PWD}, cookie=first, headers=xf(3), base=TB)
    secret = base64.b32decode(st["secret"] + "=" * (-len(st["secret"]) % 8))
    assert len(secret) == 20 and st["uri"].startswith("otpauth://totp/FlowlyStack:alice?secret=" + st["secret"]) and "issuer=FlowlyStack" in st["uri"], st
    assert "twostep" not in json.loads((TD / "auth.json").read_text())["owner"], "on before the code was confirmed"
    call("POST", "/api/auth/twostep/confirm", {"code": "abcdef"}, expect=401, cookie=first, headers=xf(4), base=TB)
    c0 = code_at(secret)
    d, _ = call("POST", "/api/auth/twostep/confirm", {"code": c0}, cookie=first, headers=xf(4), base=TB)
    codes = d["backup_codes"]
    assert len(codes) == 8 and len(set(codes)) == 8, codes
    call("GET", "/api/settings", cookie=first, base=TB)
    call("GET", "/api/settings", cookie=other, expect=401, base=TB)
    d, _ = call("GET", "/api/auth/twostep", cookie=first, base=TB)
    assert d == {"enabled": True, "backup_left": 8}, d
    d, _ = call("GET", "/api/auth/state", cookie=first, base=TB)
    assert d["twostep"] is True
    raw = (TD / "auth.json").read_text()
    assert not any(c in raw for c in codes) and st["secret"] in raw
    call("POST", "/api/auth/twostep/start", {"password": PWD}, expect=409, cookie=first, headers=xf(5), base=TB)
    step("two-step setup over the API: password, setup key and uri, wrong code refused, backup codes once, other browsers signed out")

    # --- login with two-step: password, then the code
    d, h = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(6), base=TB)
    assert d["twostep"] is True and len(d["ticket"]) > 20 and "ok" not in d and not h.get("Set-Cookie"), (d, h.get("Set-Cookie"))
    ticket = d["ticket"]
    call("GET", "/api/settings", expect=401, base=TB)
    call("POST", "/api/auth/login/code", {"ticket": ticket, "code": "abcdef"}, expect=401, headers=xf(6), base=TB)
    call("POST", "/api/auth/login/code", {"ticket": ticket, "code": c0}, expect=401, headers=xf(6), base=TB)   # the step setup used
    d, h = call("POST", "/api/auth/login/code", {"ticket": ticket, "code": code_at(secret, 1)}, headers=xf(6), base=TB)
    cookie2, raw = set_cookie(h)
    assert d["ok"] and d["username"] == "alice" and "httponly" in raw.lower() and "samesite=lax" in raw.lower(), (d, raw)
    call("GET", "/api/settings", cookie=cookie2, base=TB)
    call("POST", "/api/auth/login/code", {"ticket": ticket, "code": code_at(secret, 1)}, expect=401, headers=xf(7), base=TB)   # ticket used up
    step("login: the password gives only a ticket (no cookie, still 401), a good code gives the session, a ticket works once")

    # --- backup codes
    d, _ = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(8), base=TB)
    d, h = call("POST", "/api/auth/login/code", {"ticket": d["ticket"], "code": codes[0]}, headers=xf(8), base=TB)
    cookie3 = set_cookie(h)[0]
    d, _ = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(9), base=TB)
    call("POST", "/api/auth/login/code", {"ticket": d["ticket"], "code": codes[0]}, expect=401, headers=xf(9), base=TB)   # used
    d, _ = call("GET", "/api/auth/twostep", cookie=cookie3, base=TB)
    assert d["backup_left"] == 7, d
    step("a backup code logs in once")

    # --- new backup codes, then turn off
    call("POST", "/api/auth/twostep/backup", {"password": "wrong", "code": codes[1]}, expect=403, cookie=cookie3, headers=xf(10), base=TB)
    call("POST", "/api/auth/twostep/backup", {"password": PWD, "code": "abcdef"}, expect=401, cookie=cookie3, headers=xf(11), base=TB)
    d, _ = call("POST", "/api/auth/twostep/backup", {"password": PWD, "code": codes[1]}, cookie=cookie3, headers=xf(12), base=TB)
    new = d["backup_codes"]
    assert len(new) == 8 and not set(new) & set(codes)
    call("GET", "/api/settings", cookie=cookie3, base=TB)
    call("GET", "/api/settings", cookie=cookie2, expect=401, base=TB)
    d, _ = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(13), base=TB)
    call("POST", "/api/auth/login/code", {"ticket": d["ticket"], "code": codes[2]}, expect=401, headers=xf(13), base=TB)   # an old code is dead
    call("POST", "/api/auth/twostep/disable", {"password": "wrong", "code": new[0]}, expect=403, cookie=cookie3, headers=xf(14), base=TB)
    call("POST", "/api/auth/twostep/disable", {"password": PWD, "code": new[0]}, cookie=cookie3, headers=xf(15), base=TB)
    assert "twostep" not in json.loads((TD / "auth.json").read_text())["owner"]
    d, _ = call("GET", "/api/auth/twostep", cookie=cookie3, base=TB)
    assert d == {"enabled": False, "backup_left": 0}
    d, h = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(16), base=TB)
    tname = set_cookie(h)[0].split("=")[0]
    assert d["ok"] and re.fullmatch(r"flowlystack_session_[0-9a-f]{8}", tname), d
    assert tname != CNAME, "two installs (two data folders) use two cookie names, so they cannot log each other out"
    call("POST", "/api/auth/twostep/disable", {"password": PWD, "code": "123456"}, expect=409, cookie=cookie3, headers=xf(17), base=TB)
    step("new backup codes replace the old; turn off needs the password and a code; login is plain again")

    # --- the lockout covers wrong codes
    st, _ = call("POST", "/api/auth/twostep/start", {"password": PWD}, cookie=cookie3, headers=xf(18), base=TB)
    secret = base64.b32decode(st["secret"] + "=" * (-len(st["secret"]) % 8))
    call("POST", "/api/auth/twostep/confirm", {"code": code_at(secret)}, cookie=cookie3, headers=xf(18), base=TB)
    good, _ = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(19), base=TB)   # a valid ticket for later
    for _i in range(5):
        d2, _ = call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, headers=xf(20), base=TB)
        call("POST", "/api/auth/login/code", {"ticket": d2["ticket"], "code": "abcdef"}, expect=401, headers=xf(20), base=TB)
    call("POST", "/api/auth/login", {"username": "alice", "password": PWD}, expect=429, headers=xf(20), base=TB)
    call("POST", "/api/auth/login/code", {"ticket": good["ticket"], "code": code_at(secret, 1)}, expect=429, headers=xf(20), base=TB)
    step("five wrong codes from one client lock it (429), even with a good code")

# --- gate off
OB = os.environ.get("BASE_OFF")
if OB:
    d, _ = call("GET", "/api/auth/state", base=OB)
    assert d == {"enabled": False, "needs_setup": False, "signed_in": True, "username": ""}, d
    call("GET", "/api/settings", base=OB)
    call("GET", "/", base=OB)
    call("POST", "/api/auth/login", {"username": "a", "password": "b"}, expect=404, base=OB)
    call("POST", "/api/auth/signup", {"username": "abc", "password": "longenough"}, expect=404, base=OB)
    call("GET", "/api/auth/twostep", expect=404, base=OB)
    call("POST", "/api/auth/login/code", {"ticket": "x", "code": "123456"}, expect=404, base=OB)
    step("FLOWLYSTACK_AUTH=off: no gate, state says disabled, login and sign-up are 404")

print("\nall auth API checks passed")
