"""About routes, mounted at /api/about: the version and the release notes (backend/appinfo.py). Gated by the login like every
other /api route; nothing here touches user data or the network."""
from __future__ import annotations

from fastapi import APIRouter

from . import appinfo

router = APIRouter(prefix="/api/about")


@router.get("")
def about():
    return {"name": appinfo.NAME, "version": appinfo.version()}


@router.get("/changelog")
def about_changelog():
    return {"version": appinfo.version(), "releases": appinfo.changelog()}
