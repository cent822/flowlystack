#!/usr/bin/env python3
"""Checks for backend/auth.py (the owner account and sessions). Plain asserts, standard library only.

    python3 scripts/check_auth.py

Everything runs in a temp folder; your real data/auth.json is never touched.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-auth-check-"))
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP)   # config reads this at import
os.environ.pop("FLOWLYSTACK_AUTH", None)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import auth   # noqa: E402

FILE = TMP / "auth.json"


def step(msg: str) -> None:
    print("ok  ", msg)


def refuses(fn, needle: str, status: int):
    try:
        fn()
    except auth.AuthError as e:
        assert needle.lower() in str(e).lower() and e.status == status, (str(e), e.status)
        return e
    raise AssertionError(f"expected an AuthError containing {needle!r}")


try:
    # --- before any account
    assert auth.state() == {"needs_setup": True}
    assert auth.session_user("nope") is None and auth.session_user(None) is None
    step("fresh install needs setup, no session is valid")

    # --- sign-up validation
    refuses(lambda: auth.signup("ab", "longenough1"), "username", 400)
    refuses(lambda: auth.signup("has space", "longenough1"), "username", 400)
    refuses(lambda: auth.signup("alice", "short"), "at least 8", 400)
    refuses(lambda: auth.signup("alice", "x" * 300), "at most", 400)
    refuses(lambda: auth.signup(None, "longenough1"), "username", 400)
    assert not FILE.exists()
    step("bad username or password is refused and nothing is written")

    # --- sign-up, then closed
    t1 = auth.signup(" alice ", "correct horse")
    assert auth.state() == {"needs_setup": False}
    assert auth.session_user(t1) == "alice"
    refuses(lambda: auth.signup("other", "another pass1"), "closed", 403)
    assert auth.session_user(t1) == "alice"
    step("sign-up creates the owner and signs in; a second sign-up is closed (403)")

    # --- file contents
    raw = FILE.read_text()
    assert "correct horse" not in raw and t1 not in raw, "password or token stored in clear"
    d = json.loads(raw)
    assert d["schema_version"] == 1 and d["owner"]["username"] == "alice"
    assert d["owner"]["n"] == 2 ** 15 and len(d["owner"]["salt"]) == 32 and len(d["owner"]["hash"]) == 64
    assert list(d["sessions"]) == [auth._digest(t1)]
    assert stat.S_IMODE(FILE.stat().st_mode) == 0o600, oct(stat.S_IMODE(FILE.stat().st_mode))
    step("file holds only a scrypt hash and the token's SHA-256, mode 0600")

    # --- login
    t2 = auth.login("ALICE", "correct horse", "c1")   # username is not case sensitive
    assert t2 != t1 and auth.session_user(t2) == "alice"
    e1 = refuses(lambda: auth.login("alice", "wrong password", "c1"), "wrong username or password", 401)
    e2 = refuses(lambda: auth.login("nobody", "correct horse", "c1"), "wrong username or password", 401)
    assert str(e1) == str(e2)
    refuses(lambda: auth.login("alice", None, "c1"), "wrong username or password", 401)
    refuses(lambda: auth.login(None, "correct horse", "c1"), "wrong username or password", 401)
    step("login works (any case), a wrong name and a wrong password give the same 401")

    # --- lockout
    for _ in range(5):
        refuses(lambda: auth.login("alice", "nope nope nope", "c2"), "wrong", 401)
    e = refuses(lambda: auth.login("alice", "correct horse", "c2"), "too many", 429)
    assert 1 <= e.retry <= auth.LOCKOUT + 1
    assert auth.login("alice", "correct horse", "c3")   # another client is not locked
    auth._locked["c2"] = time.time() - 1             # lockout over
    assert auth.login("alice", "correct horse", "c2")
    step("5 failures lock that client (429 with seconds left), others and later tries work")

    # --- logout
    auth.logout(t2)
    assert auth.session_user(t2) is None and auth.session_user(t1) == "alice"
    auth.logout("not a token")
    auth.logout(None)
    step("logout removes just that session")

    # --- expiry and sliding
    d = json.loads(FILE.read_text())
    k = auth._digest(t1)
    d["sessions"][k]["last_seen"] = int(time.time()) - (auth.SESSION_DAYS * 86400 + 5)
    FILE.write_text(json.dumps(d))
    assert auth.session_user(t1) is None, "an expired session was accepted"
    assert k not in json.loads(FILE.read_text())["sessions"]
    t3 = auth.login("alice", "correct horse", "c9")
    d = json.loads(FILE.read_text())
    d["sessions"][auth._digest(t3)]["last_seen"] = int(time.time()) - auth.TOUCH_SECONDS - 10
    FILE.write_text(json.dumps(d))
    assert auth.session_user(t3) == "alice"
    assert json.loads(FILE.read_text())["sessions"][auth._digest(t3)]["last_seen"] >= int(time.time()) - 5
    step("a session expires after 30 idle days and slides forward when used")

    # --- many sessions are capped
    for i in range(auth.SESSION_MAX + 5):
        auth.login("alice", "correct horse", f"cap{i}")
    assert len(json.loads(FILE.read_text())["sessions"]) <= auth.SESSION_MAX
    step("sessions are capped at 50")

    # --- change password
    cur = auth.login("alice", "correct horse", "cp")
    other = auth.login("alice", "correct horse", "cp2")
    refuses(lambda: auth.change_password(cur, "wrong one", "brand new pass"), "current password", 403)
    refuses(lambda: auth.change_password("bad token", "correct horse", "brand new pass"), "not signed in", 401)
    refuses(lambda: auth.change_password(cur, "correct horse", "short"), "at least 8", 400)
    auth.change_password(cur, "correct horse", "brand new pass")
    assert auth.session_user(cur) == "alice" and auth.session_user(other) is None
    refuses(lambda: auth.login("alice", "correct horse", "cp3"), "wrong", 401)
    assert auth.login("alice", "brand new pass", "cp3")
    step("change password needs the old one, keeps this session, signs the others out")

    # --- reset password (server command)
    live = auth.login("alice", "brand new pass", "r1")
    auth.reset_password("reset by server")
    assert auth.session_user(live) is None and auth.session_user(cur) is None
    assert auth.login("alice", "reset by server", "r2")
    refuses(lambda: auth.reset_password("tiny"), "at least 8", 400)
    step("reset-password changes the password and signs every session out")

    # --- command line: no account -> clear message, never a traceback
    emp = Path(tempfile.mkdtemp(prefix="flowlystack-auth-empty-"))
    r = subprocess.run([sys.executable, "-m", "backend.auth", "reset-password"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "FLOWLYSTACK_SETTINGS_DIR": str(emp)}, stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and "no account yet" in r.stdout and "Traceback" not in r.stderr, (r.stdout, r.stderr)
    r = subprocess.run([sys.executable, "-m", "backend.auth"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stdout
    shutil.rmtree(emp, ignore_errors=True)
    step("python3 -m backend.auth: usage and the no-account message")

    # ================= two-step login =================
    PW = "reset by server"
    ts = lambda: json.loads(FILE.read_text())["owner"].get("twostep")   # noqa: E731

    # --- RFC 6238 test vectors (SHA-1, secret "12345678901234567890"), 8 digits as published and the 6-digit tail
    key = b"12345678901234567890"
    for when, eight in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                        (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")):
        assert auth.totp(key, when, 8) == eight, (when, auth.totp(key, when, 8))
        assert auth.totp(key, when) == eight[-6:]
    assert auth._unb32(auth._b32(key)) == key
    step("TOTP matches the RFC 6238 test vectors (8 and 6 digits), base32 round trip")

    T = 1_800_000_000
    clock = {"t": T}
    auth._now = lambda: clock["t"]
    tok = auth.login("alice", PW, "t0")
    assert isinstance(tok, str) and not isinstance(tok, auth.TwoStep)
    assert auth.twostep_status() == {"enabled": False, "backup_left": 0}
    other = auth.login("alice", PW, "t0")
    step("with two-step off, login still returns a plain session token")

    # --- setup
    refuses(lambda: auth.twostep_start("bad token", PW), "not signed in", 401)
    refuses(lambda: auth.twostep_start(tok, "wrong password"), "password is wrong", 403)
    refuses(lambda: auth.twostep_confirm(tok, "123456"), "took too long", 410)   # nothing pending
    st = auth.twostep_start(tok, PW)
    secret = auth._unb32(st["secret"])
    assert len(secret) == 20 and st["uri"] == f"otpauth://totp/FlowlyStack:alice?secret={st['secret']}&issuer=FlowlyStack", st
    d = json.loads(FILE.read_text())["owner"]
    assert d["twostep_pending"]["secret"] == st["secret"] and "twostep" not in d
    assert auth.twostep_status()["enabled"] is False
    refuses(lambda: auth.twostep_confirm(tok, "000000" if auth.totp(secret, T) != "000000" else "111111", "s1"), "wrong code", 401)
    refuses(lambda: auth.twostep_confirm(tok, "abcdef", "s1"), "wrong code", 401)
    codes = auth.twostep_confirm(tok, auth.totp(secret, T))
    assert len(codes) == 8 and len(set(codes)) == 8 and all(re.fullmatch(r"[a-hjkmnp-z2-9]{5}-[a-hjkmnp-z2-9]{5}", c) for c in codes), codes
    assert auth.twostep_status() == {"enabled": True, "backup_left": 8}
    assert auth.session_user(tok) == "alice" and auth.session_user(other) is None
    raw = FILE.read_text()
    assert not any(c in raw or c.replace("-", "") in raw for c in codes), "a backup code is stored in clear"
    t = ts()
    assert t["enabled"] and t["secret"] == st["secret"] and len(t["backup"]) == 8 and all(len(h) == 64 for h in t["backup"])
    assert "twostep_pending" not in json.loads(raw)["owner"] and stat.S_IMODE(FILE.stat().st_mode) == 0o600
    assert "secret" not in json.dumps(auth.twostep_status())
    refuses(lambda: auth.twostep_start(tok, PW), "already on", 409)
    step("setup: password asked, code proves the scan, 8 hashed backup codes returned once, other sessions signed out, secret never shown again")

    # --- pending setup expires
    auth.twostep_disable(tok, PW, auth.totp(secret, T + 30))   # clock still T: this code is one step ahead (drift window)
    clock["t"] = T + 100
    st2 = auth.twostep_start(tok, PW)
    clock["t"] = T + 100 + auth.PENDING_SECONDS + 1
    refuses(lambda: auth.twostep_confirm(tok, auth.totp(auth._unb32(st2["secret"]), clock["t"])), "took too long", 410)
    assert "twostep_pending" not in json.loads(FILE.read_text())["owner"]
    step("a pending setup older than 10 minutes is refused and removed (and disable works with password and code)")

    # --- turn it on again for the login tests
    clock["t"] = T + 1000
    st = auth.twostep_start(tok, PW)
    secret = auth._unb32(st["secret"])
    codes = auth.twostep_confirm(tok, auth.totp(secret, clock["t"]))
    base = len(json.loads(FILE.read_text())["sessions"])

    # --- login: no session until the code
    tk = auth.login("alice", PW, "l1")
    assert isinstance(tk, auth.TwoStep) and auth.session_user(tk) is None
    assert len(json.loads(FILE.read_text())["sessions"]) == base, "a session was made before the code"
    refuses(lambda: auth.login_code(tk, "000000" if auth.totp(secret, clock["t"] + 30) != "000000" else "111111", "l1"), "wrong code", 401)
    refuses(lambda: auth.login_code("not a ticket", "123456", "l1"), "expired", 401)
    refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"]), "l1"), "wrong code", 401)   # the step setup used: replay
    clock["t"] += 30
    s1 = auth.login_code(tk, auth.totp(secret, clock["t"]), "l1")
    assert auth.session_user(s1) == "alice" and not isinstance(s1, auth.TwoStep)
    refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"]), "l1"), "expired", 401)   # a ticket is used up
    step("login with two-step: a ticket first, no session until a good code; a used step and a used ticket are refused")

    # --- replay and clock drift
    tk = auth.login("alice", PW, "l2")
    refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"]), "l2"), "wrong code", 401)   # same step as the last login
    clock["t"] += 60                                                                                  # now two steps later
    assert auth.session_user(auth.login_code(tk, auth.totp(secret, clock["t"] - 30), "l2")) == "alice"   # one step behind is accepted
    clock["t"] += 300
    for name, off in (("l3", -60), ("l4", 60)):                                                         # two steps off either way: refused
        tk = auth.login("alice", PW, name)
        refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"] + off), name), "wrong code", 401)
    tk = auth.login("alice", PW, "l5")
    assert auth.session_user(auth.login_code(tk, auth.totp(secret, clock["t"] + 30), "l5")) == "alice"   # one step ahead is accepted
    step("a code works once; one 30-second step either side is accepted, two are refused")

    # --- ticket tries and expiry
    tk = auth.login("alice", PW, "m0")
    for i in range(auth.TICKET_TRIES):
        refuses(lambda: auth.login_code(tk, "123456" if auth.totp(secret, clock["t"] + 30) != "123456" else "654321", f"m{i + 1}"), "wrong code", 401)
    refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"] + 30), "m9"), "expired", 401)   # the ticket is gone after 5 tries
    tk = auth.login("alice", PW, "m10")
    auth._tickets[auth._digest(tk)]["exp"] = time.time() - 1
    refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"] + 30), "m10"), "expired", 401)
    step("a ticket allows 5 tries and 5 minutes")

    # --- backup codes: single use, forgiving format
    tk = auth.login("alice", PW, "b1")
    assert auth.session_user(auth.login_code(tk, codes[0], "b1")) == "alice"
    tk = auth.login("alice", PW, "b2")
    refuses(lambda: auth.login_code(tk, codes[0], "b2"), "wrong code", 401)                            # used
    assert auth.session_user(auth.login_code(tk, "  " + codes[1].replace("-", "").upper() + " ", "b2")) == "alice"
    assert auth.twostep_status() == {"enabled": True, "backup_left": 6}
    assert len(ts()["backup"]) == 6
    step("backup codes work once, in any case and with or without the dash")

    # --- wrong codes feed the lockout
    tk = auth.login("alice", PW, "lk")
    for _ in range(auth.TICKET_TRIES):
        refuses(lambda: auth.login_code(tk, "123456" if auth.totp(secret, clock["t"] + 30) != "123456" else "654321", "lk"), "wrong code", 401)
    tk = auth.login("alice", PW, "lk2")
    e = refuses(lambda: auth.login_code(tk, auth.totp(secret, clock["t"] + 30), "lk"), "too many", 429)
    step("5 wrong codes lock the client (429), as wrong passwords do")

    # --- regenerate and turn off need the password and a code
    clock["t"] += 90
    cur = auth.login_code(auth.login("alice", PW, "r0"), auth.totp(secret, clock["t"]), "r0")
    clock["t"] += 30
    refuses(lambda: auth.twostep_new_backup(cur, "wrong", auth.totp(secret, clock["t"]), "r1"), "password is wrong", 403)
    refuses(lambda: auth.twostep_new_backup(cur, PW, "000000" if auth.totp(secret, clock["t"]) != "000000" else "111111", "r1"), "wrong code", 401)
    refuses(lambda: auth.twostep_new_backup("bad", PW, "123456", "r1"), "not signed in", 401)
    new = auth.twostep_new_backup(cur, PW, auth.totp(secret, clock["t"]), "r2")
    assert len(new) == 8 and not set(new) & set(codes) and auth.twostep_status()["backup_left"] == 8
    assert auth.session_user(cur) == "alice" and len(json.loads(FILE.read_text())["sessions"]) == 1
    tk = auth.login("alice", PW, "r3")
    refuses(lambda: auth.login_code(tk, codes[2], "r3"), "wrong code", 401)                            # an old backup code is dead
    assert auth.session_user(auth.login_code(tk, new[0], "r3")) == "alice"
    step("new backup codes need the password and a code, replace the old ones and sign other sessions out")

    clock["t"] += 30
    cur = auth.login_code(auth.login("alice", PW, "d0"), auth.totp(secret, clock["t"]), "d0")
    refuses(lambda: auth.twostep_disable(cur, "wrong", auth.totp(secret, clock["t"] + 30), "d1"), "password is wrong", 403)
    refuses(lambda: auth.twostep_disable(cur, PW, "123456" if auth.totp(secret, clock["t"] + 30) != "123456" else "654321", "d1"), "wrong code", 401)
    auth.twostep_disable(cur, PW, new[1], "d2")                                                         # a backup code is enough
    assert ts() is None and auth.twostep_status() == {"enabled": False, "backup_left": 0}
    assert isinstance(auth.login("alice", PW, "d3"), str) and not isinstance(auth.login("alice", PW, "d3"), auth.TwoStep)
    refuses(lambda: auth.twostep_disable(cur, PW, "123456", "d4"), "not on", 409)
    step("turn off needs the password and a code (a backup code too); login is plain again")

    # --- reset-2fa: function and command
    tok = auth.login("alice", PW, "z1")
    sec = auth._unb32(auth.twostep_start(tok, PW)["secret"])
    auth.twostep_confirm(tok, auth.totp(sec, clock["t"]))
    assert auth.twostep_status()["enabled"]
    r = subprocess.run([sys.executable, "-m", "backend.auth", "reset-2fa"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "FLOWLYSTACK_SETTINGS_DIR": str(TMP)}, stdin=subprocess.DEVNULL)
    assert r.returncode == 0 and "now off" in r.stdout and "Traceback" not in r.stderr, (r.stdout, r.stderr)
    assert auth.twostep_status()["enabled"] is False and auth.session_user(tok) is None
    r = subprocess.run([sys.executable, "-m", "backend.auth", "reset-2fa"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "FLOWLYSTACK_SETTINGS_DIR": str(TMP)}, stdin=subprocess.DEVNULL)
    assert r.returncode == 0 and "already off" in r.stdout
    assert auth.reset_twostep() is False
    emp2 = Path(tempfile.mkdtemp(prefix="flowlystack-auth-empty-"))
    r = subprocess.run([sys.executable, "-m", "backend.auth", "reset-2fa"], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "FLOWLYSTACK_SETTINGS_DIR": str(emp2)}, stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and "no account yet" in r.stdout and "Traceback" not in r.stderr, (r.stdout, r.stderr)
    shutil.rmtree(emp2, ignore_errors=True)
    step("python3 -m backend.auth reset-2fa turns it off and signs every session out (and says so when it was already off)")

    auth._now = time.time

    # --- MCP tokens
    auth._locked.clear()
    auth._fails.clear()
    ses = auth.login("alice", PW, "mcp0")
    assert auth.list_mcp_tokens() == []
    refuses(lambda: auth.create_mcp_token("x" * 61, "read"), "name", 400)
    refuses(lambda: auth.create_mcp_token(5, "read"), "name", 400)
    refuses(lambda: auth.create_mcp_token("Claude Code", "admin"), "read or write", 400)
    refuses(lambda: auth.create_mcp_token(None, None), "read or write", 400)
    assert auth.list_mcp_tokens() == []
    step("a scope of read or write is required and a given name must be short; a refusal stores nothing")

    a1, a2 = auth.create_mcp_token(None, "read"), auth.create_mcp_token("   ", "read")
    assert (a1["name"], a2["name"]) == ("Token 1", "Token 2") and a1["scope"] == "read"
    auth.revoke_mcp_token(a1["id"])
    a3 = auth.create_mcp_token(None, "read")
    assert a3["name"] == "Token 1", "the smallest number not in use is taken again"
    assert auth.create_mcp_token("Token 2", "read")["name"] == "Token 2" and auth.create_mcp_token(None, "read")["name"] == "Token 3"
    for t in auth.list_mcp_tokens():
        assert auth.revoke_mcp_token(t["id"])
    assert auth.list_mcp_tokens() == []
    step("one call makes a token: without a name it is Token 1, Token 2 ... (the smallest number free), and there is no password step")

    made = auth.create_mcp_token("  Claude   Code ", "read")
    tok_r = made["token"]
    assert tok_r.startswith("fls_") and len(tok_r) > 40 and made["name"] == "Claude Code" and made["scope"] == "read" and made["tail"] == tok_r[-4:]
    raw = FILE.read_text()
    assert tok_r not in raw, "token stored in clear"
    assert auth._digest(tok_r) in json.loads(raw)["mcp_tokens"]
    assert (FILE.stat().st_mode & 0o777) == 0o600
    rows = auth.list_mcp_tokens()
    assert len(rows) == 1 and set(rows[0]) == {"id", "name", "scope", "created", "last_used", "tail"} and rows[0]["id"] == made["id"]
    assert "token" not in rows[0] and tok_r not in json.dumps(rows)
    step("the token is returned once and only its SHA-256 is stored (file stays 0600); the list never shows it")

    assert auth.session_user(tok_r) is None, "an MCP token must not work as a login session"
    got = auth.check_mcp_token(tok_r, "mcp1")
    assert got == {"id": made["id"], "name": "Claude Code", "scope": "read"}, got
    used = auth.list_mcp_tokens()[0]["last_used"]
    assert used > 0
    before = FILE.stat().st_mtime_ns
    assert auth.check_mcp_token(tok_r, "mcp1")["scope"] == "read"
    assert FILE.stat().st_mtime_ns == before and auth.list_mcp_tokens()[0]["last_used"] == used
    step("a good token is recognised with its scope, is not a session, and last_used is written at most hourly (no disk write per call)")

    for _ in range(12):   # no token at all is not a failure: it must never lock a client out
        assert auth.check_mcp_token(None, "mcp2") is None and auth.check_mcp_token("", "mcp2") is None
    assert auth.check_mcp_token(tok_r, "mcp2")["name"] == "Claude Code"
    for bad in ("fls_" + "a" * 43, "not-a-token", "fls_", 12345, "x" * 500):
        assert auth.check_mcp_token(bad, "mcp3") is None or bad == "x" * 500
        auth._locked.pop("mcp3", None)
    auth._fails.clear()
    for i in range(auth.FAIL_LIMIT):
        assert auth.check_mcp_token("fls_" + "b" * 43, "mcp4") is None
    e = refuses(lambda: auth.check_mcp_token(tok_r, "mcp4"), "too many", 429)
    assert e.retry > 0
    assert auth.check_mcp_token(tok_r, "mcp5")["scope"] == "read"
    auth._locked.clear()
    auth._fails.clear()
    step("wrong tokens count toward the login lockout (429 even for the right token from that client); no token never does")

    w = auth.create_mcp_token("Cursor", "write")
    assert auth.check_mcp_token(w["token"], "mcp6") == {"id": w["id"], "name": "Cursor", "scope": "write"}
    assert [t["name"] for t in auth.list_mcp_tokens()] == ["Claude Code", "Cursor"]
    assert w["id"] != made["id"] and w["token"] != tok_r
    step("a second token (write) gets its own id and secret")

    assert auth.revoke_mcp_token(made["id"]) is True
    assert auth.check_mcp_token(tok_r, "mcp7") is None and auth.revoke_mcp_token(made["id"]) is False and auth.revoke_mcp_token("t-nope") is False
    assert [t["name"] for t in auth.list_mcp_tokens()] == ["Cursor"] and auth.check_mcp_token(w["token"], "mcp7")["scope"] == "write"
    auth._locked.clear()
    auth._fails.clear()
    step("revoke removes only that token at once; revoking twice or an unknown id is False")

    g1 = auth.create_mcp_token("Regen test", "read")
    g2 = auth.create_mcp_token("Neighbour", "read")
    assert auth.check_mcp_token(g1["token"], "mcp7b")["name"] == "Regen test" and auth.list_mcp_tokens()[1]["last_used"] > 0
    r = auth.regenerate_mcp_token(g1["id"])
    assert r["token"].startswith("fls_") and r["token"] != g1["token"] and r["id"] == g1["id"] and r["name"] == "Regen test" and r["scope"] == "read" and r["tail"] == r["token"][-4:]
    assert auth.check_mcp_token(g1["token"], "mcp7c") is None, "the old secret stops working at once"
    assert auth.check_mcp_token(r["token"], "mcp7d")["id"] == g1["id"]
    rows = auth.list_mcp_tokens()
    assert [t["name"] for t in rows] == ["Cursor", "Regen test", "Neighbour"], "same place in the list"
    assert rows[1]["last_used"] > 0 and auth.check_mcp_token(g2["token"], "mcp7e")["name"] == "Neighbour"
    raw = FILE.read_text()
    assert g1["token"] not in raw and r["token"] not in raw and auth._digest(g1["token"]) not in raw and auth._digest(r["token"]) in raw
    assert auth.regenerate_mcp_token("t-nope") is None and auth.regenerate_mcp_token(None) is None
    auth._locked.clear()
    auth._fails.clear()
    step("regen gives the same token a new secret (old one dead at once, same id, name, scope and place, never stored in clear)")

    assert auth.rename_mcp_token(g1["id"], "  Cursor   laptop ")["name"] == "Cursor laptop"
    assert [t["name"] for t in auth.list_mcp_tokens()] == ["Cursor", "Cursor laptop", "Neighbour"]
    assert auth.check_mcp_token(r["token"], "mcp7f")["name"] == "Cursor laptop"
    refuses(lambda: auth.rename_mcp_token(g1["id"], ""), "name", 400)
    refuses(lambda: auth.rename_mcp_token(g1["id"], "x" * 61), "name", 400)
    assert auth.rename_mcp_token("t-nope", "x") is None
    sc = auth.set_mcp_token_scope(g1["id"], "write")
    assert sc["scope"] == "write" and sc["name"] == "Cursor laptop" and auth.check_mcp_token(r["token"], "mcp7g")["scope"] == "write", "the secret keeps working with the new scope"
    assert auth.set_mcp_token_scope(g1["id"], "read")["scope"] == "read" and auth.check_mcp_token(r["token"], "mcp7h")["scope"] == "read"
    refuses(lambda: auth.set_mcp_token_scope(g1["id"], "admin"), "read or write", 400)
    refuses(lambda: auth.set_mcp_token_scope(g1["id"], None), "read or write", 400)
    assert auth.set_mcp_token_scope("t-nope", "write") is None
    assert [t["scope"] for t in auth.list_mcp_tokens()][1] == "read"
    assert auth.revoke_mcp_token(g1["id"]) and auth.revoke_mcp_token(g2["id"])
    assert [t["name"] for t in auth.list_mcp_tokens()] == ["Cursor"]
    step("rename and scope changes keep the secret and the id; empty or long names, bad scopes and unknown ids are refused")

    for i in range(auth.MCP_TOKEN_MAX - 1):
        auth.create_mcp_token(f"t{i}", "read")
    refuses(lambda: auth.create_mcp_token("one too many", "read"), "up to 20", 409)
    assert len(auth.list_mcp_tokens()) == auth.MCP_TOKEN_MAX
    step("at most 20 tokens (409), also through the no-login path used when the login is off")

    auth.change_password(ses, PW, "another pass 22")
    assert len(auth.list_mcp_tokens()) == auth.MCP_TOKEN_MAX and auth.check_mcp_token(w["token"], "mcp8")["scope"] == "write"
    auth.reset_password(PW)
    assert auth.list_mcp_tokens() == [] and auth.check_mcp_token(w["token"], "mcp8") is None and auth.session_user(ses) is None
    assert json.loads(FILE.read_text())["mcp_tokens"] == {}
    auth._locked.clear()
    auth._fails.clear()
    step("changing the password keeps tokens; the server reset-password revokes every token (and every session)")

    keep = auth.create_mcp_token("Survivor", "read")["token"]
    assert auth.check_mcp_token(keep, "mcp9")["name"] == "Survivor"

    # --- a damaged file is not fatal and never opens the door
    FILE.write_text("{ not json")
    time.sleep(0.01)
    assert auth.state() == {"needs_setup": True} and auth.session_user(cur) is None
    assert auth.check_mcp_token(keep, "mcp10") is None and auth.list_mcp_tokens() == []
    step("a damaged auth.json reads as 'no account' and no MCP token is valid (the owner can run reset or restore it)")

    # --- off switch
    os.environ["FLOWLYSTACK_AUTH"] = "off"
    assert auth.enabled() is False
    os.environ["FLOWLYSTACK_AUTH"] = "on"
    assert auth.enabled() is True
    os.environ.pop("FLOWLYSTACK_AUTH")
    assert auth.enabled() is True
    step("FLOWLYSTACK_AUTH=off turns the gate off, default is on")

    
    # --- the session cookie's name is per install (browsers share cookies between ports of one address) ---
    import hashlib
    import json as _json
    auth._cache.update({"stamp": None, "data": None})
    for f in TMP.glob("auth.json"): f.unlink()
    auth._cache.update({"stamp": None, "data": None})
    assert auth.cookie_name() == "flowlystack_session", "no owner yet: the plain name"
    auth.signup("carol", "correct horse")
    n1 = auth.cookie_name()
    assert re.fullmatch(r"flowlystack_session_[0-9a-f]{8}", n1), n1
    tok = auth.login("carol", "correct horse")[0] if isinstance(auth.login("carol", "correct horse"), tuple) else auth.login("carol", "correct horse")
    auth.change_username(tok, "correct horse", "carol2")
    auth.change_password(tok, "correct horse", "another horse 2")
    assert auth.cookie_name() == n1, "stays the same after a new login name and a new password"
    # a second install (another data folder, another sign-up time) gets another name
    other = _json.loads((TMP / "auth.json").read_text()); other["owner"]["created"] += 7
    (TMP / "auth.json").write_text(_json.dumps(other)); auth._cache.update({"stamp": None, "data": None})
    assert auth.cookie_name() != n1 and auth.cookie_name().startswith("flowlystack_session_")
    print("ok   cookie name: plain before an owner, per install after, unchanged by a new password or login name, different for another install")
    print("\nall auth checks passed")
finally:
    shutil.rmtree(TMP, ignore_errors=True)
