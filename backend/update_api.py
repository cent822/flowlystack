"""Update notice routes, mounted at /api/update (backend/updatecheck.py). Gated by the login like every other /api route.
GET answers from the stored result at once and never waits for GitHub; POST /dismiss closes the toast for one version."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from . import updatecheck

router = APIRouter(prefix="/api/update")


class Dismiss(BaseModel):
    version: str


@router.get("")
def update_status():
    return updatecheck.status()


@router.post("/dismiss")
def update_dismiss(body: Dismiss):
    updatecheck.dismiss(body.version.strip())
    return {"ok": True}
