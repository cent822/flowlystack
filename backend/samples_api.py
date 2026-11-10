"""Sample content routes, mounted at /api/samples. Behind the normal login gate like every /api route.

Nothing here runs by itself: samples are added only by POST /add, which the web page sends when the user presses the button after the dialog
has listed what will be created. No model is called and nothing leaves the computer.
"""
from __future__ import annotations

from fastapi import APIRouter

from . import linkshell_api, samples, studio_api
from .rag import service

router = APIRouter(prefix="/api/samples")


def _changed() -> None:
    """The same follow-ups the Studio, Linkshell and Collections routes run after a write: search indexes and the document indexer."""
    studio_api.sync_search()
    linkshell_api.sync_search()
    service.kick()


@router.get("")
def get_status():
    return samples.status()


@router.post("/add")
def add():
    r = samples.add()
    _changed()
    return r


@router.post("/remove")
def remove():
    r = samples.remove()
    _changed()
    return r


@router.post("/dismiss")
def dismiss():
    return samples.dismiss()
