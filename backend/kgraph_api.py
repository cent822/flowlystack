"""Routes of the Knowledge / Lattice page: /api/kgraph. The base snapshot is built in the background by
`kgraph_build.KGraph`; `GET` answers at once with the newest one it has and a status (`building`, `ready`, `error`; `stale` while it is rebuilt).
Read-only for the user's prompts, documents and vectors: nothing here writes outside `<data dir>/kgraph/`, and no model is called. Behind the session
gate like every /api route."""
import json
import threading

from fastapi import APIRouter, HTTPException, Request, Response

from . import gallery, kgraph, kgraph_build, kgraph_colours, kgraph_extract, kgraph_kinds, settings
from .config import SETTINGS_DIR
from .promptstore import PROMPTS_DIR, STUDIO_DIR
from .rag import service as rag_service

router = APIRouter(prefix="/api/kgraph")
_lock = threading.Lock()
_k: kgraph_build.KGraph | None = None


def get() -> kgraph_build.KGraph:
    global _k
    with _lock:
        if _k is None:
            _k = kgraph_build.KGraph(
                SETTINGS_DIR, PROMPTS_DIR, STUDIO_DIR, None,
                model=lambda: settings.get("knowledge.embedding_model"),
                ignore=lambda: settings.get("knowledge.gallery_ignore_words"),
                vector_lookup=lambda model, hashes: rag_service.get().copy.get(model, hashes),
                vector_count=lambda m: rag_service.get().copy.count(m) if m else 0)
        return _k


def _send(request: Request, body: dict) -> Response:
    """JSON, gzip-compressed when the browser accepts it (a few hundred KB of repetitive text)."""
    headers = {"Cache-Control": "no-store"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gallery.gz(body), media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(json.dumps(body, separators=(",", ":"), ensure_ascii=False), media_type="application/json", headers=headers)


@router.get("")
def snapshot(request: Request):
    return _send(request, get().get())


@router.post("/rebuild")
def rebuild(request: Request):
    """Build again now (the page's Refresh)."""
    return _send(request, get().rebuild())


# ---------------------------------------------------------------- the entity layer
# User data under PROMPTS_DIR/kgraph/batches, owned by backend/kgraph.py. These routes only list it and let the user hide, undo, delete and restore;
# agents (MCP) and the local-model button add. The list leaves out quotes (they are read per entity, when it is opened).

def _fail(e: kgraph.Invalid):
    raise HTTPException(e.status, str(e))


def _stores() -> kgraph.Stores:
    return kgraph.Stores(PROMPTS_DIR, STUDIO_DIR, None)


@router.get("/entities")
def entities(request: Request):
    """The live entity layer for the picture: entities, their edges (no quotes), and every batch with its state (hidden and undone ones included)."""
    ix = kgraph.entities_index(item_exists=_stores().exists)
    return _send(request, {
        "entities": [{k: e[k] for k in ("id", "name", "kind", "aliases", "note", "batches")} for e in ix["entities"].values()],
        "edges": [{"type": e["type"], "from": e["from"], "to": e["to"], "label": e["label"], "item": e["item"], "batch": e["batch"], "source_gone": e["source_gone"]} for e in ix["edges"]],
        "batches": kgraph.list_batches(), "damaged": kgraph.damaged()})


@router.get("/entity/{eid}")
def entity(eid: str):
    """One entity with its evidence: every edge that touches it, with the quote, the source item and who made it."""
    ix = kgraph.entities_index(include_hidden=True, item_exists=_stores().exists)
    e = ix["entities"].get(eid)
    if not e:
        raise HTTPException(404, "That entity is not in the list any more.")
    batches = {b["id"]: b for b in kgraph.list_batches()}
    rows = []
    for x in ix["edges"]:
        if x["to"] != eid and x["from"] != eid:
            continue
        b = batches.get(x["batch"], {})
        other = ix["entities"].get(x["from"] if x["to"] == eid else x["to"]) if x["type"] == "related" else None
        rows.append({"type": x["type"], "label": x["label"], "item": x["item"], "quote": x["quote"], "source_gone": x["source_gone"], "batch": x["batch"], "by": x["by"], "via": x["via"],
                     "when": b.get("ts", 0), "run_note": b.get("note", ""), "hidden": bool(b.get("hidden")), "direction": ("out" if x["from"] == eid else "in") if x["type"] == "related" else "",
                     "other": {"id": other["id"], "name": other["name"], "kind": other["kind"]} if other else None})
    return {"entity": {k: e[k] for k in ("id", "name", "kind", "aliases", "note", "batches")}, "evidence": rows}


@router.patch("/batches/{bid}")
def batch_hide(bid: str, body: dict):
    try:
        return {"ok": True, "batch": kgraph.hide_batch(bid, bool(body.get("hidden", True)))}
    except kgraph.Invalid as e:
        _fail(e)


@router.post("/batches/{bid}/undo")
def batch_undo(bid: str):
    """Hide the whole run everywhere (nothing is deleted; `reinstate` brings it back)."""
    try:
        return {"ok": True, "batch": kgraph.undo_batch(bid)}
    except kgraph.Invalid as e:
        _fail(e)


@router.post("/batches/{bid}/reinstate")
def batch_reinstate(bid: str):
    try:
        return {"ok": True, "batch": kgraph.reinstate_batch(bid)}
    except kgraph.Invalid as e:
        _fail(e)


@router.post("/batches/restore")
def batch_restore(body: dict):
    """Undo of a delete: put back the raw batch DELETE returned."""
    try:
        return {"ok": True, "batch": kgraph.restore_batch(body.get("removed"))}
    except kgraph.Invalid as e:
        _fail(e)


@router.delete("/batches/{bid}")
def batch_delete(bid: str):
    """Delete the batch for good; the raw batch comes back so the page can offer Undo."""
    try:
        return {"ok": True, "removed": kgraph.delete_batch(bid)}
    except kgraph.Invalid as e:
        _fail(e)


@router.post("/entities/restore")
def entity_restore(body: dict):
    return {"ok": True, "restored": kgraph.restore_entity(body.get("removed"))}


@router.delete("/entities/{eid}")
def entity_delete(eid: str):
    """Delete one entity and its edges everywhere; the removed rows come back so the page can offer Undo."""
    try:
        return {"ok": True, "removed": kgraph.delete_entity(eid)}
    except kgraph.Invalid as e:
        _fail(e)


# ---------------------------------------------------------------- entity kinds
# User data in PROMPTS_DIR/kgraph/kinds.json, owned by backend/kgraph_kinds.py. Only the user changes kinds here; agents never can. Delete is soft and never
# touches a batch file.

def _kinds_fail(e: kgraph_kinds.Invalid):
    raise HTTPException(e.status, str(e))


def _kinds_body() -> dict:
    return {"kinds": kgraph_kinds.load(), "limits": {"total": kgraph_kinds.MAX_KINDS, "label": kgraph_kinds.MAX_LABEL, "hint": kgraph_kinds.MAX_HINT}}


@router.get("/kinds")
def kinds_list():
    return _kinds_body()


@router.post("/kinds")
def kinds_add(body: dict):
    try:
        k = kgraph_kinds.add(body.get("label"), body.get("hint"), body.get("light"), body.get("dark"))
    except kgraph_kinds.Invalid as e:
        _kinds_fail(e)
    return {**_kinds_body(), "kind": k}


@router.post("/kinds/reset")
def kinds_reset():
    kgraph_kinds.reset()
    return _kinds_body()


@router.patch("/kinds/{slug}")
def kinds_edit(slug: str, body: dict):
    try:
        k = kgraph_kinds.update(slug, {f: body[f] for f in ("label", "hint", "light", "dark") if f in body})
    except kgraph_kinds.Invalid as e:
        _kinds_fail(e)
    return {**_kinds_body(), "kind": k}


@router.delete("/kinds/{slug}")
def kinds_delete(slug: str):
    try:
        k = kgraph_kinds.delete(slug)
    except kgraph_kinds.Invalid as e:
        _kinds_fail(e)
    return {**_kinds_body(), "kind": k}


@router.post("/kinds/{slug}/restore")
def kinds_restore(slug: str):
    try:
        k = kgraph_kinds.restore(slug)
    except kgraph_kinds.Invalid as e:
        _kinds_fail(e)
    return {**_kinds_body(), "kind": k}


# ---------------------------------------------------------------- node colours (display data, PROMPTS_DIR/kgraph/colours.json)
# The user's own light and dark colour per item type and per collection, owned by backend/kgraph_colours.py. Overrides only; agents never change them.

def _colours_fail(e: kgraph_colours.Invalid):
    raise HTTPException(e.status, str(e))


@router.get("/colours")
def colours_list():
    return kgraph_colours.load()


@router.post("/colours/reset")
def colours_reset():
    return kgraph_colours.reset()


@router.patch("/colours/types/{name}")
def colours_type(name: str, body: dict):
    try:
        return kgraph_colours.set_type(name, {f: body[f] for f in ("light", "dark") if f in body})
    except kgraph_colours.Invalid as e:
        _colours_fail(e)


@router.delete("/colours/types/{name}")
def colours_type_clear(name: str):
    try:
        return kgraph_colours.clear_type(name)
    except kgraph_colours.Invalid as e:
        _colours_fail(e)


@router.patch("/colours/collections/{cid}")
def colours_col(cid: str, body: dict):
    try:
        return kgraph_colours.set_collection(cid, {f: body[f] for f in ("light", "dark") if f in body})
    except kgraph_colours.Invalid as e:
        _colours_fail(e)


@router.delete("/colours/collections/{cid}")
def colours_col_clear(cid: str):
    return kgraph_colours.clear_collection(cid)


# ---------------------------------------------------------------- Build with a local model
# Text goes to a model only when the user presses Start (POST /extract/start), to the model they picked. /extract/preview calls no model: it is the
# status line the page shows first. The model list and the default come from GET /api/assistant/providers (Ollama first).

def _scope_body(body: dict):
    """(scope, provider, model) from a request body, or an HTTP error."""
    from .assistant import registry
    scope, pid, model = body.get("scope"), str(body.get("provider") or "ollama"), str(body.get("model") or "").strip()
    provider = registry.get(pid)
    if provider is None:
        raise HTTPException(404, f"The provider “{pid}” is not configured.")
    if not model:
        raise HTTPException(400, "Pick a model first.")
    return scope, provider, model


@router.post("/extract/preview")
def extract_preview(body: dict):
    scope, provider, model = _scope_body(body)
    try:
        return kgraph_extract.preview(scope, (PROMPTS_DIR, STUDIO_DIR, None), provider, model, settings.get("assistant.num_ctx"))
    except kgraph.Invalid as e:
        _fail(e)


@router.post("/extract/start")
def extract_start(body: dict):
    """Press Start. `expect` = {items, chars} from the preview the user saw: if the choice changed since (new prompts, another model), nothing is sent."""
    scope, provider, model = _scope_body(body)
    num_ctx = settings.get("assistant.num_ctx")
    try:
        items, _facts = kgraph_extract.select(scope, (PROMPTS_DIR, STUDIO_DIR, None))
        seen = body.get("expect") or {}
        now = kgraph_extract.preview(scope, (PROMPTS_DIR, STUDIO_DIR, None), provider, model, num_ctx)
        if seen.get("items") != now["items"] or seen.get("chars") != now["chars"]:
            raise HTTPException(409, "What would be sent has changed since you looked. Look at the new numbers and press Start again.")
        return kgraph_extract.RUNNER.start(provider, model, items, num_ctx=num_ctx, stores=_stores())
    except kgraph.Invalid as e:
        _fail(e)


@router.get("/extract")
def extract_status():
    return kgraph_extract.RUNNER.status()


@router.post("/extract/stop")
def extract_stop():
    try:
        return kgraph_extract.RUNNER.stop()
    except kgraph.Invalid as e:
        _fail(e)
