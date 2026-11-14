"""About routes, mounted at /api/about: the version and the release notes (backend/appinfo.py). Gated by the login like every
other /api route; nothing here touches user data or the network (the dialog's "seen" version is one small file)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from . import appinfo, whatsnew

router = APIRouter(prefix="/api/about")


@router.get("")
def about():
    return {"name": appinfo.NAME, "version": appinfo.version()}


@router.get("/changelog")
def about_changelog():
    return {"version": appinfo.version(), "releases": appinfo.changelog()}


class Seen(BaseModel):
    version: str


@router.get("/whatsnew")
def about_whatsnew():
    """The release notes the user has not been shown yet (empty when switched off, on a fresh install or when nothing is new)."""
    return whatsnew.pending()


@router.post("/whatsnew/seen")
def about_whatsnew_seen(body: Seen):
    whatsnew.mark(body.version)
    return {"ok": True}
