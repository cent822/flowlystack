"""Routes of the Knowledge / Gallery page: /api/gallery. The snapshot is built in the background by
`gallery.Gallery`; `GET` answers at once with the newest one it has and a status (`building`, `ready`, `error`; `stale` when it is being rebuilt).
Read-only for the user's prompts and documents: nothing here writes outside `<data dir>/gallery/`, and no model is called. `?source=documents`
(default `prompts`) picks the Documents mode."""
import json
import threading

from fastapi import APIRouter, HTTPException, Request, Response

from . import collections as co
from . import gallery, gallery_docs, settings
from .config import SETTINGS_DIR
from .promptstore import PROMPTS_DIR, STUDIO_DIR
from .rag import service as rag_service

router = APIRouter(prefix="/api/gallery")
_lock = threading.Lock()
_g: gallery.Gallery | None = None
_gd: gallery_docs.DocGallery | None = None


def get() -> gallery.Gallery:
    global _g
    with _lock:
        if _g is None:
            _g = gallery.Gallery(
                SETTINGS_DIR, PROMPTS_DIR, STUDIO_DIR,
                model=lambda: settings.get("knowledge.embedding_model"),
                ignore=lambda: settings.get("knowledge.gallery_ignore_words"),
                vector_lookup=lambda model, hashes: rag_service.get().copy.get(model, hashes),
                vector_count=lambda m: rag_service.get().copy.count(m) if m else 0)
        return _g


def get_docs() -> gallery_docs.DocGallery:
    """The Documents mode's snapshot: read-only over the imported documents, its own cache file."""
    global _gd
    with _lock:
        if _gd is None:
            _gd = gallery_docs.DocGallery(
                SETTINGS_DIR, None,
                model=lambda: settings.get("knowledge.embedding_model"),
                ignore=lambda: settings.get("knowledge.gallery_ignore_words"),
                vector_lookup=lambda model, hashes: rag_service.get().copy.get(model, hashes),
                vector_count=lambda m: rag_service.get().copy.count(m) if m else 0, library_dir=PROMPTS_DIR)
        return _gd


def _which(source: str):
    """`prompts` (the default) or `documents`; anything else is refused rather than quietly answered with the prompts."""
    if source in ("", "prompts"):
        return get()
    if source == "documents":
        return get_docs()
    raise HTTPException(400, "source must be prompts or documents")


def _send(request: Request, body: dict) -> Response:
    """JSON, gzip-compressed when the browser accepts it (the snapshot is a few hundred KB of repetitive text)."""
    headers = {"Cache-Control": "no-store"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gallery.gz(body), media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(json.dumps(body, separators=(",", ":"), ensure_ascii=False), media_type="application/json", headers=headers)


@router.get("")
def snapshot(request: Request, source: str = "", part: str = ""):
    """`?source=documents&part=passages` is the passage map of the Structure slide (built when first asked for); any other `part` is refused."""
    if part:
        if part != "passages" or source != "documents":
            raise HTTPException(400, "part must be passages, and only with source=documents")
        return _send(request, get_docs().passages())
    return _send(request, _which(source).get())


@router.post("/rebuild")
def rebuild(request: Request, map: str = "", source: str = ""):
    """Build again now. `?map=full` also draws the map from scratch (otherwise new prompts or documents are placed beside their neighbours).
    `?source=documents` rebuilds the Documents mode; the default is the prompts, unchanged."""
    return _send(request, _which(source).rebuild(map == "full"))


@router.get("/counts")
def counts():
    """What each mode would show, for the Prompts | Documents switch. Starts no build: `documents` counts the live documents that have text (a stat
    per document), `prompts` is the size of the last prompts snapshot (null until one exists)."""
    snap = get()._snap
    return {"prompts": snap["n"] if snap else None, "documents": sum(1 for d in co.all_documents() if d.get("passages"))}
