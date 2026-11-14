"""Auth routes at /api/auth and the gate that protects everything else. The logic lives in auth.py.

The gate is one middleware (`gate`): without a live session every /api call (the live stream too) answers 401 and every
page redirects to /login; static files the login page needs stay public. A write (POST, PUT, PATCH, DELETE) whose Origin
header names another site is refused (403), which with SameSite=Lax cookies is the CSRF protection; a call without an
Origin header (curl, scripts) is not a browser cross-site attack and is let through to the session check.

Proxy headers (X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host) are believed only when FLOWLYSTACK_TRUST_PROXY=1,
otherwise a client could fake its address or HTTPS. Sign-up is refused when the request carries any proxy header, trusted
or not, so nobody can claim a freshly exposed server: create the account on the server itself.
"""
from __future__ import annotations

import os
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import auth, profilestore

router = APIRouter(prefix="/api/auth")
PUBLIC_PREFIXES = ("/css/", "/fonts/")                      # what the login page is drawn with
PUBLIC_FILES = {"/login", "/login.html", "/js/login.js", "/js/theme.js", "/favicon.ico"}
PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host", "x-forwarded-proto")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def trust_proxy() -> bool:
    return os.environ.get("FLOWLYSTACK_TRUST_PROXY", "").strip().lower() in ("1", "true", "yes", "on")


def via_proxy(request: Request) -> bool:
    return any(h in request.headers for h in PROXY_HEADERS)


def client_of(request: Request) -> str:
    """The address used for the login lockout. The right-most X-Forwarded-For entry is the one our own proxy added."""
    if trust_proxy():
        xff = request.headers.get("x-forwarded-for", "")
        if xff.strip():
            return xff.split(",")[-1].strip()[:64]
    return request.client.host if request.client else ""


def host_of(request: Request) -> str:
    if trust_proxy() and request.headers.get("x-forwarded-host"):
        return request.headers["x-forwarded-host"].split(",")[0].strip()
    return request.headers.get("host", "")


def is_https(request: Request) -> bool:
    if trust_proxy() and request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https":
        return True
    return request.url.scheme == "https"


def cross_site(request: Request) -> bool:
    origin = request.headers.get("origin")
    if origin is None:
        return False
    try:
        return urlparse(origin).netloc.lower() != host_of(request).lower() or origin == "null"
    except ValueError:
        return True


def _public(path: str) -> bool:
    return path in PUBLIC_FILES or path.startswith(PUBLIC_PREFIXES) or path.startswith("/api/auth/")


async def gate(request: Request, call_next):
    if not auth.enabled():
        return await call_next(request)
    path = request.url.path
    if request.method in UNSAFE and cross_site(request):
        return JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
    if path == "/mcp":   # agents carry an MCP token, not a cookie: mcp_api checks the switch, the Origin and the token itself (never a session)
        return await call_next(request)
    if _public(path) or auth.session_user(request.cookies.get(auth.cookie_name())):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Sign in required."}, status_code=401)
    nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse("/login" + (f"?next={quote(nxt, safe='')}" if nxt != "/" else ""), status_code=302)


def _fail(e: auth.AuthError):
    headers = {"Retry-After": str(e.retry)} if e.retry else None
    raise HTTPException(e.status, str(e), headers=headers)


def _need_enabled():
    if not auth.enabled():
        raise HTTPException(404, "Login is turned off (FLOWLYSTACK_AUTH=off).")


def _set_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(auth.cookie_name(), token, httponly=True,   # no max_age: a session cookie, gone when the browser quits (the server still ends an idle session after SESSION_DAYS)
                        samesite="lax",
                        secure=is_https(request), path="/")


@router.get("/state")
def state(request: Request):
    if not auth.enabled():
        return {"enabled": False, "needs_setup": False, "signed_in": True, "username": ""}
    user = auth.session_user(request.cookies.get(auth.cookie_name()))
    out = {"enabled": True, **auth.state(), "signed_in": bool(user), "username": user or ""}
    if user:
        out["twostep"] = auth.twostep_status()["enabled"]   # only for the signed-in owner: a visitor must not learn whether it is on
        out["avatar"] = profilestore.version()              # the picture's version for ?v= (None: show the initial)
    return out


@router.post("/signup")
def signup(request: Request, response: Response, body: dict = Body(...)):
    _need_enabled()
    if auth.state()["needs_setup"] and via_proxy(request):
        raise HTTPException(403, "Create the account first on the server itself (open the app at http://127.0.0.1 and its port there), then log in from anywhere.")
    try:
        token = auth.signup(body.get("username"), body.get("password"))
    except auth.AuthError as e:
        _fail(e)
    profilestore.remove()   # sign-up only works when there was no owner: a new owner never inherits an old picture ("delete data/auth.json to start over")
    _set_cookie(request, response, token)
    return {"ok": True, "username": auth.session_user(token)}


@router.post("/login")
def login(request: Request, response: Response, body: dict = Body(...)):
    _need_enabled()
    try:
        token = auth.login(body.get("username"), body.get("password"), client_of(request))
    except auth.AuthError as e:
        _fail(e)
    if isinstance(token, auth.TwoStep):   # the password was right and two-step is on: no cookie yet, only a ticket for /login/code
        return {"twostep": True, "ticket": str(token)}
    _set_cookie(request, response, token)
    return {"ok": True, "username": auth.session_user(token)}


@router.post("/login/code")
def login_code(request: Request, response: Response, body: dict = Body(...)):
    """Second step of a log-in with two-step on: the ticket from /login plus an authenticator code or a backup code."""
    _need_enabled()
    try:
        token = auth.login_code(body.get("ticket"), body.get("code"), client_of(request))
    except auth.AuthError as e:
        _fail(e)
    _set_cookie(request, response, token)
    return {"ok": True, "username": auth.session_user(token)}


@router.post("/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.cookie_name()))
    response.delete_cookie(auth.cookie_name(), path="/")
    return {"ok": True}


@router.post("/password")
def password(request: Request, body: dict = Body(...)):
    _need_enabled()
    try:
        auth.change_password(request.cookies.get(auth.cookie_name()), body.get("old"), body.get("new"))
    except auth.AuthError as e:
        _fail(e)
    return {"ok": True}


@router.post("/username")
def username(request: Request, body: dict = Body(...)):
    """Rename the owner (the login name). Needs a session and the current password; this session and the others stay signed in."""
    token = _owner_token(request)
    try:
        return {"ok": True, "username": auth.change_username(token, body.get("password"), body.get("new"), client_of(request))}
    except auth.AuthError as e:
        _fail(e)


# ---------- two-step login: these routes need a session (the gate lets /api/auth/* through, so each checks) ----------

def _owner_token(request: Request) -> str:
    _need_enabled()
    token = request.cookies.get(auth.cookie_name())
    if not auth.session_user(token):
        raise HTTPException(401, "Sign in required.")
    return token


@router.get("/twostep")
def twostep_state(request: Request):
    _owner_token(request)
    return auth.twostep_status()


@router.post("/twostep/start")
def twostep_start(request: Request, body: dict = Body(...)):
    """Step 1 of setup: the password again; answers the setup key and the otpauth address for the QR code (once)."""
    token = _owner_token(request)
    try:
        return auth.twostep_start(token, body.get("password"), client_of(request))
    except auth.AuthError as e:
        _fail(e)


@router.post("/twostep/confirm")
def twostep_confirm(request: Request, body: dict = Body(...)):
    """Step 2: the first code from the app. Turns two-step on; the backup codes are in this answer and never sent again."""
    token = _owner_token(request)
    try:
        return {"backup_codes": auth.twostep_confirm(token, body.get("code"), client_of(request))}
    except auth.AuthError as e:
        _fail(e)


@router.post("/twostep/disable")
def twostep_disable(request: Request, body: dict = Body(...)):
    token = _owner_token(request)
    try:
        auth.twostep_disable(token, body.get("password"), body.get("code"), client_of(request))
    except auth.AuthError as e:
        _fail(e)
    return {"ok": True}


@router.post("/twostep/backup")
def twostep_backup(request: Request, body: dict = Body(...)):
    token = _owner_token(request)
    try:
        return {"backup_codes": auth.twostep_new_backup(token, body.get("password"), body.get("code"), client_of(request))}
    except auth.AuthError as e:
        _fail(e)


# ---------- MCP tokens: for agents, accepted only on /mcp. The gate lets /api/auth/* through, so each route checks the session ----------

def _token_owner(request: Request) -> str | None:
    """The session token when the login is on (a session is then required); None when the login is off (the gate is off too)."""
    return _owner_token(request) if auth.enabled() else None


@router.get("/mcp-tokens")
def mcp_tokens(request: Request):
    _token_owner(request)
    return {"tokens": auth.list_mcp_tokens()}


@router.post("/mcp-tokens")
def mcp_token_create(request: Request, body: dict = Body(default={})):
    """Make a token with one click: the name is optional (Token 1, Token 2 ...) and the scope defaults to read. The token is in this answer once and never again."""
    _token_owner(request)
    try:
        made = auth.create_mcp_token((body or {}).get("name"), (body or {}).get("scope") or "read")
    except auth.AuthError as e:
        _fail(e)
    return JSONResponse(made, headers={"Cache-Control": "no-store"})


@router.post("/mcp-tokens/{tid}/regen")
def mcp_token_regen(tid: str, request: Request):
    """A new secret for the same token (same name and scope). The old one stops working at once; the new one is in this answer once."""
    _token_owner(request)
    made = auth.regenerate_mcp_token(tid)
    if made is None:
        raise HTTPException(404, "unknown token")
    return JSONResponse(made, headers={"Cache-Control": "no-store"})


@router.patch("/mcp-tokens/{tid}")
def mcp_token_update(tid: str, request: Request, body: dict = Body(...)):
    """Rename a token and/or change its scope (read or write). The secret never changes here (that is Regen)."""
    _token_owner(request)
    if "name" not in body and "scope" not in body:
        raise HTTPException(400, "send a name or a scope")
    out = None
    try:
        if "name" in body:
            out = auth.rename_mcp_token(tid, body.get("name"))
        if "scope" in body and (out is not None or "name" not in body):
            out = auth.set_mcp_token_scope(tid, body.get("scope"))
    except auth.AuthError as e:
        _fail(e)
    if out is None:
        raise HTTPException(404, "unknown token")
    return out


@router.delete("/mcp-tokens/{tid}")
def mcp_token_revoke(tid: str, request: Request):
    _token_owner(request)
    if not auth.revoke_mcp_token(tid):
        raise HTTPException(404, "unknown token")
    return {"revoked": tid}
