"""The owner account and login sessions. Standard library only; owns all auth state.

One owner, created on the first visit; sign-up is closed after that. State lives in `data/auth.json` (owner-only
permissions, atomic write, gitignored; tests use FLOWLYSTACK_SETTINGS_DIR): the owner's scrypt hash and, per session, only
the SHA-256 of its token. Not SQLite: the database is a cache that may be deleted. A password or token is never logged
or returned except the one new session token a successful sign-up or login hands back (it goes into the cookie).

Reset a forgotten password on the server:  python3 -m backend.auth reset-password
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import quote

from .config import SETTINGS_DIR

SCHEMA = 1
SESSION_DAYS = 30
SESSION_MAX = 50                    # oldest sessions are dropped beyond this
TOUCH_SECONDS = 3600                # last_seen is rewritten at most once an hour (no disk write on every request)
PASSWORD_MIN, PASSWORD_MAX = 8, 256
USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{2,63}$")
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}
FAIL_LIMIT, FAIL_WINDOW, LOCKOUT = 5, 60, 60   # 5 failed logins in a minute lock that client for a minute
TOTP_STEP, TOTP_DIGITS, TOTP_WINDOW = 30, 6, 1   # RFC 6238; a code from one step before or after is accepted (clock drift)
BACKUP_N, BACKUP_LEN = 8, 10
BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no i, l, o, 0, 1: easy to read out and type
PENDING_SECONDS, TICKET_SECONDS, TICKET_TRIES = 600, 300, 5   # setup must finish in 10 minutes; a code step in 5, with 5 tries
MCP_PREFIX, MCP_SCOPES, MCP_TOKEN_MAX, MCP_NAME_MAX = "fls_", ("read", "write"), 20, 60

_lock = threading.RLock()
_cache: dict = {"stamp": None, "data": None}
_fails: dict = defaultdict(deque)   # client -> times of recent failed logins
_locked: dict = {}                  # client -> time the lockout ends


class AuthError(Exception):
    def __init__(self, msg: str, status: int = 400, retry: int = 0):
        super().__init__(msg)
        self.status = status
        self.retry = retry          # seconds, for a 429


def enabled() -> bool:
    return os.environ.get("FLOWLYSTACK_AUTH", "").strip().lower() not in ("off", "0", "false", "no")


# ---------- file ----------

def _path() -> Path:
    return SETTINGS_DIR / "auth.json"


def _load() -> dict:
    p = _path()
    try:
        stamp = p.stat().st_mtime_ns
    except OSError:
        _cache.update(stamp=None, data={"schema_version": SCHEMA, "owner": None, "sessions": {}, "mcp_tokens": {}})
        return _cache["data"]
    if _cache["stamp"] != stamp:
        try:
            d = json.loads(p.read_text())
            if not isinstance(d, dict):
                raise ValueError
        except (OSError, ValueError):
            d = {}
        d.setdefault("schema_version", SCHEMA)
        if not isinstance(d.get("owner"), dict):
            d["owner"] = None
        if not isinstance(d.get("sessions"), dict):
            d["sessions"] = {}
        if not isinstance(d.get("mcp_tokens"), dict):
            d["mcp_tokens"] = {}
        _cache.update(stamp=stamp, data=d)
    return _cache["data"]


def _save(d: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix="auth.json.", suffix=".tmp")   # mkstemp: created owner-only (0600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    _cache["stamp"] = None          # reload next time: the file's own timestamp is the truth


# ---------- passwords ----------

def _hash(password: str, salt: bytes | None = None, params: dict | None = None) -> dict:
    params = params or SCRYPT
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=params["n"], r=params["r"], p=params["p"],
                       maxmem=128 * params["n"] * params["r"] * 2, dklen=32)
    return {"salt": salt.hex(), "hash": h.hex(), **params}


def _verify(password: str, rec: dict) -> bool:
    try:
        want = _hash(password, bytes.fromhex(rec["salt"]), {"n": rec["n"], "r": rec["r"], "p": rec["p"]})["hash"]
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(want, rec.get("hash", ""))


_DUMMY = None


def _dummy() -> dict:               # a wrong username still costs one scrypt, so timing does not reveal it
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = _hash("not-a-real-password")
    return _DUMMY


def _check_username(name) -> str:
    if not isinstance(name, str) or not USERNAME.match(name.strip()):
        raise AuthError("Username: 3 to 64 characters, letters, digits and . _ @ + - only.")
    return name.strip()


def _check_password(pw) -> str:
    if not isinstance(pw, str) or len(pw) < PASSWORD_MIN:
        raise AuthError(f"Password must be at least {PASSWORD_MIN} characters.")
    if len(pw) > PASSWORD_MAX:
        raise AuthError(f"Password must be at most {PASSWORD_MAX} characters.")
    return pw


# ---------- sessions ----------

def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(d: dict) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    d["sessions"][_digest(token)] = {"created": now, "last_seen": now}
    _prune(d)
    return token


def _prune(d: dict) -> None:
    cut = time.time() - SESSION_DAYS * 86400
    s = d["sessions"]
    for k in [k for k, v in s.items() if not isinstance(v, dict) or v.get("last_seen", 0) < cut]:
        del s[k]
    for k in sorted(s, key=lambda k: s[k].get("last_seen", 0))[:max(0, len(s) - SESSION_MAX)]:
        del s[k]


def session_user(token) -> str | None:
    """The owner's username when `token` is a live session, else None. Slides the expiry (written at most hourly)."""
    if not token or not isinstance(token, str):
        return None
    with _lock:
        d = _load()
        s = d["sessions"].get(_digest(token))
        if not s or not d["owner"]:
            return None
        now = time.time()
        if s.get("last_seen", 0) < now - SESSION_DAYS * 86400:
            del d["sessions"][_digest(token)]
            _save(d)
            return None
        if now - s.get("last_seen", 0) > TOUCH_SECONDS:
            s["last_seen"] = int(now)
            _save(d)
        return d["owner"]["username"]


# ---------- the four actions ----------

def state() -> dict:
    with _lock:
        o = _load()["owner"]
    return {"needs_setup": o is None}


def cookie_name() -> str:
    """The session cookie's name, different for every install. Browsers share cookies between the PORTS of one address, so two copies on 127.0.0.1
    (two installs on different ports, for example 8372 and 9000) used to overwrite each other's cookie and log each other out. The suffix comes from the
    moment this owner was created: it never changes (a new password or login name keeps it), differs between installs, and is not a secret.
    Before an owner exists there is no session to look for, so the plain name is used."""
    created = (_load().get("owner") or {}).get("created")
    return "flowlystack_session" + (f"_{hashlib.sha256(f'flowlystack:{created}'.encode()).hexdigest()[:8]}" if created else "")


def signup(username, password) -> str:
    """Create the owner (first visit only) and return its first session token."""
    name, pw = _check_username(username), _check_password(password)
    with _lock:
        d = _load()
        if d["owner"]:
            raise AuthError("Sign-up is closed: an account already exists.", 403)
        d["owner"] = {"username": name, **_hash(pw), "created": int(time.time())}
        d["sessions"] = {}
        return _commit(d, _new_session(d))


def _commit(d: dict, token):
    _save(d)
    return token


def _blocked(client: str) -> None:
    now = time.time()
    until = _locked.get(client, 0)
    if until > now:
        raise AuthError("Too many attempts. Try again in a moment.", 429, int(until - now) + 1)
    _locked.pop(client, None)


def _failed(client: str) -> None:
    now = time.time()
    q = _fails[client]
    q.append(now)
    while q and q[0] < now - FAIL_WINDOW:
        q.popleft()
    if len(q) >= FAIL_LIMIT:
        _locked[client] = now + LOCKOUT
        q.clear()
    if len(_fails) > 2000:          # a flood of addresses must not grow memory forever
        for k in [k for k, v in _fails.items() if not v or v[-1] < now - FAIL_WINDOW]:
            del _fails[k]


def login(username, password, client: str = "") -> str:
    """Check the owner's credentials and return a new session token. Same message for a wrong name or password."""
    with _lock:
        _blocked(client)
        o = _load()["owner"]
    pw = password if isinstance(password, str) and len(password) <= PASSWORD_MAX else ""
    same = isinstance(username, str) and o is not None and username.strip().casefold() == o["username"].casefold()
    ok = _verify(pw, o if same else _dummy()) and same
    with _lock:
        if not ok:
            _failed(client)
            raise AuthError("Wrong username or password.", 401)
        d = _load()
        if (d["owner"].get("twostep") or {}).get("enabled"):   # the password was right: no session yet, only a ticket for the code step
            return TwoStep(_new_ticket(d["owner"]["username"]))   # (the failure count is NOT reset here, or the code could be guessed without limit)
        _fails.pop(client, None)
        return _commit(d, _new_session(d))


def logout(token) -> None:
    if not token or not isinstance(token, str):
        return
    with _lock:
        d = _load()
        if d["sessions"].pop(_digest(token), None) is not None:
            _save(d)


def change_password(token, old, new) -> None:
    """Needs the current password. Every other session is signed out; this one stays."""
    pw = _check_password(new)
    with _lock:
        d = _load()
        me = d["sessions"].get(_digest(token)) if isinstance(token, str) else None
        if not me or not d["owner"]:
            raise AuthError("Not signed in.", 401)
        if not isinstance(old, str) or not _verify(old, d["owner"]):
            raise AuthError("The current password is wrong.", 403)
        d["owner"].update(_hash(pw))
        d["sessions"] = {_digest(token): me}
        _save(d)


def change_username(token, password, new, client: str = "") -> str:
    """Rename the owner (the login name). Needs the current password, which counts toward the lockout when wrong.
    Sessions and MCP tokens stay as they are: they never held the name. Returns the new name."""
    name = _check_username(new)
    with _lock:
        d = _load()
        _me(d, token)
        _need_password(d, password, client)
        d["owner"]["username"] = name
        _save(d)
        return name


def reset_password(new) -> None:
    """Server-side reset (no login needed: whoever can run this owns the machine). Signs every session out and revokes every MCP token."""
    pw = _check_password(new)
    with _lock:
        d = _load()
        if not d["owner"]:
            raise AuthError("There is no account yet. Open the app and create one.", 404)
        d["owner"].update(_hash(pw))
        d["sessions"] = {}
        d["mcp_tokens"] = {}
        _save(d)


# ---------- two-step login: an authenticator-app code (TOTP, RFC 6238) and one-time backup codes ----------

class TwoStep(str):
    """What `login` returns instead of a session token when two-step is on: a short-lived ticket for `login_code`."""


def _now() -> float:
    return time.time()              # one place to ask for the time, so the checks can set the clock


def _hotp(secret: bytes, counter: int, digits: int = TOTP_DIGITS) -> str:   # RFC 4226 dynamic truncation
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(n).zfill(digits)


def totp(secret: bytes, when: float, digits: int = TOTP_DIGITS) -> str:
    return _hotp(secret, int(when // TOTP_STEP), digits)


def _b32(secret: bytes) -> str:
    return base64.b32encode(secret).decode().rstrip("=")


def _unb32(text: str) -> bytes:
    return base64.b32decode(text + "=" * (-len(text) % 8))


def _norm_code(code) -> str:
    return re.sub(r"[\s-]", "", code).lower() if isinstance(code, str) else ""


def _match_step(secret: bytes, code: str, last_step: int) -> int | None:
    """The 30-second step `code` belongs to (the current one or one either side), only if it is newer than the last one used."""
    cur = int(_now() // TOTP_STEP)
    ok = None
    for s in range(cur - TOTP_WINDOW, cur + TOTP_WINDOW + 1):   # no early exit: the time taken does not depend on which step matched
        if hmac.compare_digest(_hotp(secret, s), code) and s > last_step:
            ok = s
    return ok


def _backup_hash(code: str) -> str:
    return hashlib.sha256(_norm_code(code).encode()).hexdigest()


def _new_backup_codes() -> list:
    return [(lambda c: f"{c[:5]}-{c[5:]}")("".join(secrets.choice(BACKUP_ALPHABET) for _ in range(BACKUP_LEN))) for _ in range(BACKUP_N)]


def _second_factor(d: dict, code) -> bool:
    """True when `code` is a good authenticator code or an unused backup code; the code is then used up (replay-proof)."""
    ts = d["owner"].get("twostep") or {}
    c = _norm_code(code)
    if len(c) == TOTP_DIGITS and c.isdigit():
        s = _match_step(_unb32(ts["secret"]), c, ts.get("last_step", 0))
        if s is None:
            return False
        ts["last_step"] = s
        return True
    if len(c) == BACKUP_LEN:
        h, hit = _backup_hash(c), None
        for x in ts.get("backup", []):
            if hmac.compare_digest(x, h):
                hit = x
        if hit is None:
            return False
        ts["backup"].remove(hit)
        return True
    return False


def _me(d: dict, token) -> dict:
    s = d["sessions"].get(_digest(token)) if isinstance(token, str) else None
    if not s or not d["owner"]:
        raise AuthError("Not signed in.", 401)
    return s


def _keep_only(d: dict, token: str) -> None:   # every other browser is signed out (it only passed the password)
    d["sessions"] = {_digest(token): d["sessions"][_digest(token)]}


def _need_password(d: dict, password, client: str) -> None:
    _blocked(client)
    if not isinstance(password, str) or len(password) > PASSWORD_MAX or not _verify(password, d["owner"]):
        _failed(client)
        raise AuthError("The password is wrong.", 403)


def _need_code(d: dict, code, client: str) -> None:
    if not _second_factor(d, code):
        _failed(client)
        raise AuthError("Wrong code. Check that the clock on your phone is right.", 401)


def twostep_status() -> dict:
    with _lock:
        ts = (_load()["owner"] or {}).get("twostep") or {}
    return {"enabled": bool(ts.get("enabled")), "backup_left": len(ts.get("backup", [])) if ts.get("enabled") else 0}


def twostep_start(token, password, client: str = "") -> dict:
    """Step 1 of setup: needs the session and the password. Makes a pending secret (not active yet) and returns it once for the QR code."""
    with _lock:
        d = _load()
        _me(d, token)
        if (d["owner"].get("twostep") or {}).get("enabled"):
            raise AuthError("Two-step login is already on.", 409)
        _need_password(d, password, client)
        secret = secrets.token_bytes(20)
        d["owner"]["twostep_pending"] = {"secret": _b32(secret), "created": int(_now())}
        _save(d)
        name = d["owner"]["username"]
        return {"secret": _b32(secret), "uri": f"otpauth://totp/FlowlyStack:{quote(name, safe='')}?secret={_b32(secret)}&issuer=FlowlyStack"}


def twostep_confirm(token, code, client: str = "") -> list:
    """Step 2: the first code from the app proves the scan worked. Turns two-step on and returns the backup codes (the only time)."""
    with _lock:
        d = _load()
        _me(d, token)
        _blocked(client)
        p = d["owner"].get("twostep_pending")
        if not p or _now() - p.get("created", 0) > PENDING_SECONDS:
            d["owner"].pop("twostep_pending", None)
            _save(d)
            raise AuthError("Setup took too long. Start again.", 410)
        c = _norm_code(code)
        s = _match_step(_unb32(p["secret"]), c, 0) if len(c) == TOTP_DIGITS and c.isdigit() else None
        if s is None:
            _failed(client)
            raise AuthError("Wrong code. Check that the clock on your phone is right.", 401)
        codes = _new_backup_codes()
        d["owner"]["twostep"] = {"secret": p["secret"], "enabled": True, "last_step": s, "backup": [_backup_hash(x) for x in codes]}
        d["owner"].pop("twostep_pending", None)
        _keep_only(d, token)
        _save(d)
        return codes


def twostep_disable(token, password, code, client: str = "") -> None:
    with _lock:
        d = _load()
        _me(d, token)
        if not (d["owner"].get("twostep") or {}).get("enabled"):
            raise AuthError("Two-step login is not on.", 409)
        _need_password(d, password, client)
        _blocked(client)
        _need_code(d, code, client)
        d["owner"].pop("twostep", None)
        d["owner"].pop("twostep_pending", None)
        _keep_only(d, token)
        _save(d)


def twostep_new_backup(token, password, code, client: str = "") -> list:
    with _lock:
        d = _load()
        _me(d, token)
        if not (d["owner"].get("twostep") or {}).get("enabled"):
            raise AuthError("Two-step login is not on.", 409)
        _need_password(d, password, client)
        _blocked(client)
        _need_code(d, code, client)
        codes = _new_backup_codes()
        d["owner"]["twostep"]["backup"] = [_backup_hash(x) for x in codes]
        _keep_only(d, token)
        _save(d)
        return codes


_tickets: dict = {}                 # sha256(ticket) -> {"user", "exp", "tries"}; memory only, so a restart drops them


def _new_ticket(username: str) -> str:
    now = time.time()
    for k in [k for k, v in _tickets.items() if v["exp"] < now]:
        del _tickets[k]
    t = secrets.token_urlsafe(24)
    _tickets[_digest(t)] = {"user": username, "exp": now + TICKET_SECONDS, "tries": 0}
    return t


def login_code(ticket, code, client: str = "") -> str:
    """The second step of a log-in: the ticket from `login` plus an authenticator code or a backup code gives the session token."""
    with _lock:
        _blocked(client)
        k = _digest(ticket) if isinstance(ticket, str) else ""
        t = _tickets.get(k)
        if not t or t["exp"] < time.time():
            _tickets.pop(k, None)
            raise AuthError("That log-in expired. Enter your password again.", 401)
        d = _load()
        if not d["owner"] or d["owner"]["username"] != t["user"] or not (d["owner"].get("twostep") or {}).get("enabled"):
            _tickets.pop(k, None)
            raise AuthError("That log-in expired. Enter your password again.", 401)
        if not _second_factor(d, code):
            t["tries"] += 1
            if t["tries"] >= TICKET_TRIES:
                del _tickets[k]
            _failed(client)
            raise AuthError("Wrong code. Check that the clock on your phone is right.", 401)
        del _tickets[k]
        _fails.pop(client, None)
        return _commit(d, _new_session(d))   # _commit saves, which also stores the used step or backup code


def reset_twostep() -> bool:
    """Server-side: turn two-step off and sign every session out. True when it was on."""
    with _lock:
        d = _load()
        if not d["owner"]:
            raise AuthError("There is no account yet. Open the app and create one.", 404)
        was = bool((d["owner"].get("twostep") or {}).get("enabled"))
        d["owner"].pop("twostep", None)
        d["owner"].pop("twostep_pending", None)
        d["sessions"] = {}
        _save(d)
        _tickets.clear()
        return was


# ---------- MCP tokens: long-lived bearer tokens for agents, accepted only on /mcp. One click makes one (no password step: the session is the permission) ----------

def _token_name(name) -> str:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= MCP_NAME_MAX:
        raise AuthError(f"A token name is 1 to {MCP_NAME_MAX} characters.")
    return " ".join(name.split())


def _auto_name(d: dict) -> str:
    """Token 1, Token 2 ...: the smallest number not already used as a name."""
    used = {t.get("name") for t in d["mcp_tokens"].values() if isinstance(t, dict)}
    n = 1
    while f"Token {n}" in used:
        n += 1
    return f"Token {n}"


def _new_secret() -> str:
    return MCP_PREFIX + secrets.token_urlsafe(32)


def create_mcp_token(name=None, scope="read") -> dict:
    """Make a token (a name is optional: without one it is called Token 1, Token 2 ...). The token itself is in the answer once and is never
    stored (only its SHA-256). The caller decides who may ask: the route needs a signed-in session when the login is on."""
    if scope not in MCP_SCOPES:
        raise AuthError("Scope must be read or write.")
    with _lock:
        d = _load()
        name = _auto_name(d) if name is None or (isinstance(name, str) and not name.strip()) else _token_name(name)
        if len(d["mcp_tokens"]) >= MCP_TOKEN_MAX:
            raise AuthError(f"Up to {MCP_TOKEN_MAX} tokens. Revoke one you no longer use.", 409)
        token = _new_secret()
        taken = {t["id"] for t in d["mcp_tokens"].values()}
        tid = "t-" + secrets.token_hex(4)
        while tid in taken:
            tid = "t-" + secrets.token_hex(4)
        d["mcp_tokens"][_digest(token)] = {"id": tid, "name": name, "scope": scope, "created": int(time.time()), "last_used": 0, "tail": token[-4:]}
        _save(d)
        return {"token": token, **_public_token(d["mcp_tokens"][_digest(token)])}


def regenerate_mcp_token(tid) -> dict | None:
    """A fresh secret for an existing token: same id, name, scope and place in the list; the old secret stops working at once. None for an unknown id."""
    with _lock:
        d = _load()
        old = next((k for k, t in d["mcp_tokens"].items() if isinstance(t, dict) and t.get("id") == tid), None)
        if old is None:
            return None
        token = _new_secret()
        rec = {**d["mcp_tokens"][old], "created": int(time.time()), "last_used": 0, "tail": token[-4:]}
        d["mcp_tokens"] = {(_digest(token) if k == old else k): (rec if k == old else v) for k, v in d["mcp_tokens"].items()}
        _save(d)
        return {"token": token, **_public_token(rec)}


def rename_mcp_token(tid, name) -> dict | None:
    name = _token_name(name)
    with _lock:
        d = _load()
        t = next((t for t in d["mcp_tokens"].values() if isinstance(t, dict) and t.get("id") == tid), None)
        if t is None:
            return None
        t["name"] = name
        _save(d)
        return _public_token(t)


def set_mcp_token_scope(tid, scope) -> dict | None:
    """Let a token write (or make it read-only again). The secret and the name stay; None for an unknown id."""
    if scope not in MCP_SCOPES:
        raise AuthError("Scope must be read or write.")
    with _lock:
        d = _load()
        t = next((t for t in d["mcp_tokens"].values() if isinstance(t, dict) and t.get("id") == tid), None)
        if t is None:
            return None
        t["scope"] = scope
        _save(d)
        return _public_token(t)


def _public_token(t: dict) -> dict:
    return {"id": t["id"], "name": t["name"], "scope": t["scope"], "created": t["created"], "last_used": t.get("last_used", 0), "tail": t.get("tail", "")}


def list_mcp_tokens() -> list:
    with _lock:   # creation order: the file keeps insertion order (sorting by the one-second `created` would shuffle tokens made together)
        return [_public_token(t) for t in _load()["mcp_tokens"].values() if isinstance(t, dict)]


def revoke_mcp_token(tid) -> bool:
    with _lock:
        d = _load()
        hit = next((k for k, t in d["mcp_tokens"].items() if isinstance(t, dict) and t.get("id") == tid), None)
        if hit is None:
            return False
        del d["mcp_tokens"][hit]
        _save(d)
        return True


def check_mcp_token(token, client: str = "") -> dict | None:
    """The token's {id, name, scope} when it is a live token, else None. A wrong token counts toward the same per-client lockout as a wrong
    password (a locked-out client gets a 429 AuthError). No token at all is not a failure. last_used is written at most hourly."""
    if token is None or token == "":
        return None
    with _lock:
        _blocked(client)
        d = _load()
        dig = _digest(token) if isinstance(token, str) and token.startswith(MCP_PREFIX) and len(token) <= 200 else ""
        hit = None
        for k, t in d["mcp_tokens"].items():   # a full pass with a constant-time compare, whichever one matches
            if dig and hmac.compare_digest(k, dig) and isinstance(t, dict):
                hit = t
        if hit is None:
            _failed(client)
            return None
        now = int(time.time())
        if now - hit.get("last_used", 0) > TOUCH_SECONDS:
            hit["last_used"] = now
            _save(d)
        return {"id": hit["id"], "name": hit["name"], "scope": hit["scope"]}


def _main(argv: list) -> int:
    if argv[:1] == ["reset-2fa"]:
        try:
            print("Two-step login is now off. Every session is signed out." if reset_twostep() else "Two-step login was already off. Every session is signed out.")
        except AuthError as e:
            print(e)
            return 1
        return 0
    if argv[:1] != ["reset-password"]:
        print("usage: python3 -m backend.auth reset-password | reset-2fa")
        return 2
    try:
        if not _load()["owner"]:
            print("There is no account yet. Open the app and create one.")
            return 1
        a, b = getpass.getpass("New password: "), getpass.getpass("Repeat it: ")
        if a != b:
            print("The two passwords differ. Nothing changed.")
            return 1
        reset_password(a)
    except AuthError as e:
        print(e)
        return 1
    print("Password changed. Every session is signed out and every MCP token is revoked.")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
