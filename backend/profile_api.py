"""Profile routes at /api/profile: the owner's picture (backend/profilestore.py). Deliberately not under /api/auth/, which the gate lets
through: everything here needs the session the gate checks. Renaming the owner is /api/auth/username (it needs the password)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from . import auth, profilestore as profile

router = APIRouter(prefix="/api/profile")
SAFE = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"}


def _need_enabled():
    if not auth.enabled():
        raise HTTPException(404, "Login is turned off (FLOWLYSTACK_AUTH=off), so there is no owner profile.")


@router.get("/avatar")
def avatar_get():
    data = profile.read()
    if data is None:
        raise HTTPException(404, "No profile picture.")
    return Response(data, media_type="image/png", headers={**SAFE, "Cache-Control": "private, max-age=31536000, immutable"})   # the URL carries ?v=, so a new picture is a new address


@router.put("/avatar")
async def avatar_put(request: Request):
    _need_enabled()
    try:
        if int(request.headers.get("content-length") or 0) > profile.MAX_BYTES:
            raise profile.ProfileError("That picture is too large.")
        version = profile.save(await request.body())
    except profile.ProfileError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "version": version}


@router.delete("/avatar")
def avatar_delete():
    _need_enabled()
    profile.remove()
    return {"ok": True}
