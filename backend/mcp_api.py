"""The MCP endpoint, POST /mcp. The protocol is `backend/mcp/`; this file is only the HTTP edge.

Order of checks, each before the next so nothing leaks: the switch (Settings > MCP, off = 404), the Origin (a page in a browser must not talk to
a local server), the bearer token (always required, even with the login turned off), then the message. A session cookie is never accepted here
and a token is never accepted anywhere else (`auth_api.gate` lets `/mcp` through to this file and checks nothing more).
"""
from __future__ import annotations

import asyncio
import json
import sys

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from . import auth, auth_api, settings
from .config import ROOT
from .mcp import activity, server

router = APIRouter()
MAX_BODY = 1_000_000
NO_STORE = {"Cache-Control": "no-store"}


def _rpc_error(status: int, code: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}}, status_code=status, headers={**NO_STORE, **(headers or {})})


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h[:7].lower() == "bearer " else None


@router.post("/mcp")
async def mcp_post(request: Request):
    if not settings.get("mcp.enabled"):
        return JSONResponse({"detail": "MCP is turned off."}, status_code=404, headers=NO_STORE)
    if auth_api.cross_site(request):
        return _rpc_error(403, server.E_REQUEST, "Cross-site request refused.")
    try:
        ctx = auth.check_mcp_token(_bearer(request), auth_api.client_of(request))
    except auth.AuthError as e:   # too many wrong tokens from this address
        return _rpc_error(e.status, server.E_REQUEST, str(e), {"Retry-After": str(e.retry)})
    if ctx is None:
        return _rpc_error(401, server.E_REQUEST, "A valid MCP token is required.", {"WWW-Authenticate": 'Bearer realm="FlowlyStack"'})
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _rpc_error(413, server.E_REQUEST, "The message is too large.")
    try:
        msg = json.loads(raw)
    except ValueError:
        return _rpc_error(400, server.E_PARSE, "The body is not valid JSON.")
    status, body = await asyncio.to_thread(server.handle, msg, request.headers, ctx)
    if body is None:
        return Response(status_code=status, headers=NO_STORE)
    return JSONResponse(body, status_code=status, headers=NO_STORE)


@router.api_route("/mcp", methods=["GET", "DELETE"])
async def mcp_other():
    """No server-initiated stream and no sessions: the one allowed method is POST."""
    return Response(status_code=405, headers={"Allow": "POST", **NO_STORE})


@router.get("/api/mcp/info")
def mcp_info(request: Request):
    """What Settings > MCP needs to build its copy-ready setup snippets (the session gate protects it like every /api route). The paths are this
    computer's; `local` says whether the browser is on it, because a Claude Desktop on another computer cannot use them."""
    tools = list(server.TOOLS.values())
    return {"enabled": bool(settings.get("mcp.enabled")), "python": sys.executable, "bridge": str(ROOT / "backend" / "mcp_stdio.py"),
            "local": not auth_api.via_proxy(request) and auth_api.client_of(request) in ("127.0.0.1", "::1", "localhost"),
            "tools": {"read": sum(t["scope"] == "read" for t in tools), "write": sum(t["scope"] == "write" for t in tools)},
            "protocol_versions": list(server.SUPPORTED)}


@router.get("/api/mcp/activity")
def mcp_activity(limit: int = 30):
    """What agents created through MCP, newest first (Settings > MCP). No text, only titles; the session gate protects it."""
    return {"items": activity.list_items(max(1, min(limit, 100)))}


@router.delete("/api/mcp/activity")
def mcp_activity_delete_all():
    """Clear the activity list. Only the list: the prompts and projects agents made stay. Returns the removed entries so the page can offer Undo."""
    return {"ok": True, "removed": activity.delete()}


@router.post("/api/mcp/activity/restore")
def mcp_activity_restore(body: dict):
    """Undo of a delete: put the removed entries back."""
    return {"ok": True, "restored": activity.restore(body.get("removed"))}


@router.delete("/api/mcp/activity/{aid}")
def mcp_activity_delete(aid: str):
    try:
        return {"ok": True, "removed": activity.delete(aid)}
    except activity.UndoError as e:
        raise HTTPException(e.status, str(e))


@router.post("/api/mcp/activity/{aid}/undo")
def mcp_undo(aid: str):
    """Reverse one entry: a created item goes to the Trash, a new Studio version is replaced by the previous text (never deletes)."""
    try:
        return {"ok": True, "note": activity.undo(aid)}
    except activity.UndoError as e:
        raise HTTPException(e.status, str(e))
