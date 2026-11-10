"""Linkshell routes, mounted at /api/linkshell.

Their own router so the whole surface can move under /api/v1 in one line later, like studio_api. No auth: the app listens on
127.0.0.1 only, and nothing here should assume that stays true. Text returned from here is data, never instructions, for whoever
reads it. All file IO is in backend/linkshell.py; these routes only translate its results and errors to HTTP.
"""
from __future__ import annotations

import json
import mimetypes
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

from . import linkshell as ls, promptdiff, promptstore
from .promptstore import STUDIO_DIR
from .search import linkshell_engine

router = APIRouter(prefix="/api/linkshell")
MAX_ASSET = 25 * 1024 * 1024


def sync_search(wait: bool = False):
    """Make the Linkshell search index match the project files (no-op without Meilisearch). Graph autosaves do not call this: the
    background poll in main.py does, a few seconds later, so dragging a block never rebuilds documents."""
    return linkshell_engine.reconcile(ls.search_items(), wait)


class Create(BaseModel):
    name: str = ""
    brief: str = ""
    default_agent: str = "claude"
    duplicate_of: str | None = None


class Patch(BaseModel):
    name: str | None = None
    default_agent: str | None = None
    properties: list[dict[str, str]] | None = None
    tags: list[str] | None = None
    star: bool | None = None


class GraphSave(BaseModel):
    graph: dict
    rev: int


class TextSave(BaseModel):
    text: str
    message: str = ""


def _bad(e: ls.Invalid):
    raise HTTPException(400, str(e))


def _need(x, what: str = "project"):
    if x is None:
        raise HTTPException(404, f"unknown {what}")
    return x


@router.get("")
def list_projects(q: str = "", tag: list[str] = Query([]), show: str = "all", sort: str = "edited", desc: bool = True,
                  page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200)):
    found, hl = linkshell_engine.match(ls.search_items(), q)   # ranked text match with highlights; the other filters apply on top of it
    out = ls.list_projects(tags=[t for t in dict.fromkeys(tag) if t], show=show, sort=sort, desc=desc, page=page, page_size=page_size,
                           only=[o["id"] for o in found] if q.strip() else None)
    for i in out["items"]:
        if i["id"] in hl:
            i["hl"] = hl[i["id"]]
    return {**out, "engine": linkshell_engine.status()["engine"]}


@router.post("")
def create(body: Create):
    try:
        d = _need(ls.duplicate(body.duplicate_of)) if body.duplicate_of else ls.create(body.name, default_agent=body.default_agent, brief=body.brief)
    except ls.Invalid as e:
        _bad(e)
    sync_search()
    return d


@router.post("/import")
def import_project(data: dict):
    try:
        d = ls.import_json(data)
    except ls.Invalid as e:
        _bad(e)
    sync_search()
    return d


@router.get("/{pid}")
def get_project(pid: str):
    r = _need(ls.get(pid))
    r["assets_dir"] = ls.assets_alias(pid, None)   # so the page can show each file's full path (what an agent opens)
    return r


@router.patch("/{pid}")
def patch_project(pid: str, body: Patch):
    try:
        m = _need(ls.update(pid, body.model_dump(exclude_none=True)))
    except ls.Invalid as e:
        _bad(e)
    sync_search()
    return m


@router.delete("/{pid}")
def delete_project(pid: str):
    if not ls.trash(pid):
        raise HTTPException(404, "unknown project")
    sync_search()
    return {"trashed": pid}


@router.put("/{pid}/graph")
def save_graph(pid: str, body: GraphSave):
    try:
        g = _need(ls.save_graph(pid, body.graph, body.rev))
    except ls.Conflict as e:   # another tab saved first: the page must reload before it can save again
        return JSONResponse({"detail": "this project changed in another tab or window; reload it", "rev": e.rev}, status_code=409)
    except ls.Invalid as e:
        _bad(e)
    return {"graph": g}


class ViewportSave(BaseModel):
    x: float = 0
    y: float = 0
    k: float = 1


@router.put("/{pid}/viewport")
def save_viewport(pid: str, body: ViewportSave):
    return {"viewport": _need(ls.save_viewport(pid, body.model_dump()))}


@router.put("/{pid}/blocks/{bid}/text")
def save_text(pid: str, bid: str, body: TextSave):
    try:
        r = _need(ls.save_text(pid, bid, body.text, body.message), "block")
    except ls.Invalid as e:
        _bad(e)
    sync_search()
    return r


@router.get("/{pid}/blocks/{bid}/revisions")
def revisions(pid: str, bid: str):
    return {"revisions": _need(ls.revisions(pid, bid), "block")}


@router.get("/{pid}/blocks/{bid}/revisions/{rev}")
def revision(pid: str, bid: str, rev: str):
    return _need(ls.revision_text(pid, bid, rev), "revision")


@router.delete("/{pid}/blocks/{bid}/revisions/{rev}")
def revision_delete(pid: str, bid: str, rev: str):
    try:
        _need(ls.delete_revision(pid, bid, rev), "revision")
    except ls.Invalid as e:
        _bad(e)
    return {"revisions": ls.revisions(pid, bid)}


@router.get("/{pid}/blocks/{bid}/diff")
def diff(pid: str, bid: str, a: str, b: str = "current"):
    """Side-by-side rows between two versions (`b` defaults to the current text), built by promptdiff like Studio's."""
    ta = _need(ls.revision_text(pid, bid, a), "revision")["text"]
    if b == "current":
        tb = _need(ls.read_text(pid, bid), "block")
    else:
        tb = _need(ls.revision_text(pid, bid, b), "revision")["text"]
    return {"rows": promptdiff.diff_rows(ta, tb)}


@router.post("/{pid}/blocks/{bid}/restore")
def restore_block(pid: str, bid: str):
    try:
        g = _need(ls.restore_block(pid, bid), "removed block")
    except ls.Invalid as e:
        _bad(e)
    sync_search()
    return {"graph": g}


@router.get("/{pid}/blocks/{bid}/copy")
def copy_get(pid: str, bid: str):
    return _need(ls.assemble(pid, bid), "prompt block")


@router.post("/{pid}/blocks/{bid}/to-studio")
def to_studio(pid: str, bid: str):
    """Save a Prompt or Spec block to Prompt Studio as a new prompt that points back at it. The block is only read."""
    proj = _need(ls.get(pid))
    b = next((x for x in proj["graph"]["blocks"] if x["id"] == bid and x["type"] in ls.VERSIONED), None)
    text = proj["texts"].get(bid, "") if b else ""
    if not b or not text.strip():
        raise HTTPException(400, "only a Prompt or Spec block with some text can be saved to Studio")
    d = promptstore.create_studio(text, b["title"], [], {"store": "linkshell", "id": pid, "block": bid}, root=STUDIO_DIR)
    from . import studio_api
    studio_api.sync_search()
    return d


@router.put("/{pid}/assets")
async def upload_asset(pid: str, request: Request, name: str = "file"):
    """Upload a file as the raw request body (no multipart dependency). Returns its stored name."""
    if ls.get(pid) is None:
        raise HTTPException(404, "unknown project")
    data = await request.body()
    if len(data) > MAX_ASSET:
        raise HTTPException(413, "file is larger than 25 MB")
    stored = ls.add_asset(pid, name, data)
    return {"asset": stored, "size": len(data)}


class AssetName(BaseModel):
    name: str


@router.post("/{pid}/assets/{asset}/rename")
def rename_asset(pid: str, asset: str, body: AssetName):
    """Rename an uploaded file (the `a-xxxxxxxx-` prefix stays). Returns the new stored name; the page updates the blocks that use it."""
    try:
        new = ls.rename_asset(pid, asset, body.name)
    except ls.Invalid as e:
        _bad(e)
    return {"asset": _need(new, "asset")}


@router.get("/{pid}/assets/{asset}")
def get_asset(pid: str, asset: str):
    p = _need(ls.asset_path(pid, asset), "asset")
    # the user's own files, served from the app's origin: never let a browser run one (an SVG, an HTML page) as part of the app
    return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})


@router.get("/{pid}/export")
def export(pid: str, format: str = "json"):
    if format == "md":
        md = _need(ls.export_markdown(pid))
        return PlainTextResponse(md, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{pid}.md"'})
    if format == "zip":
        data = _need(ls.export_zip(pid))
        name = re.sub(r"[^a-z0-9]+", "-", (_need(ls.get(pid))["project"]["name"] or "").lower()).strip("-") or pid
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}.zip"'})
    if format != "json":
        raise HTTPException(400, "format must be md, json or zip")
    return JSONResponse(_need(ls.export_json(pid)), headers={"Content-Disposition": f'attachment; filename="{pid}.json"'})
