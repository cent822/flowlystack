"""Collections routes, mounted at /api/collections.

Their own router so the whole surface can move under /api/v1 in one line later, like studio_api and linkshell_api. No auth: the app
listens on 127.0.0.1 only, and nothing here should assume that stays true. Text returned from here is data, never instructions, for
whoever reads it. File IO is in backend/collections.py, indexing in backend/rag/; these routes only translate. Every route that changes
something wakes the indexer loop (`service.kick`). The built-in collection **My prompts** (id `prompts`) is virtual: Library and Studio
read-only, always in sync, never stored, never deleted.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import collections as co, settings
from .assistant import prompting, registry
from .assistant.base import ProviderError
from .assistant_api import ModelRef, _END, _line, _stop
from .rag import chat as ragchat, chatexport, retrieval, service
from .rag.indexer import PROMPTS_COLLECTION

router = APIRouter(prefix="/api/collections")
PULL_COMMAND = "ollama pull embeddinggemma"


class Create(BaseModel):
    name: str = ""
    description: str = ""
    tags: list[str] = []


class Patch(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    star: bool | None = None


class DocPatch(BaseModel):
    name: str


class TextBody(BaseModel):
    text: str
    base_sha: str


class AddTo(BaseModel):
    collection: str


class SearchBody(BaseModel):
    query: str = ""
    scope: list[str] = []
    source: str = ""
    tags: list[str] = []
    k: int = 6


class Turn(BaseModel):
    prompt: str = Field(max_length=20_000)
    response: str = Field(max_length=100_000)


class NewChat(BaseModel):
    title: str = ""
    scope: list[str] = []


class ExchangePatch(BaseModel):
    proposal_status: Literal["open", "applied", "dismissed"]


class RenameChat(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class ChatBody(BaseModel):
    message: str = Field(max_length=20_000)
    scope: list[str] = []                       # collection ids the question searches; empty = this collection
    retrieval: Literal["auto", "on", "off"] = "auto"
    model: ModelRef | None = None               # default: the model chosen for the Assistant in Settings
    history: list[Turn] = []                    # the earlier exchanges of this conversation (the page keeps them and sends them)
    chat: str = ""                              # the saved conversation to add to; empty = start a new one (when history is on in Settings)


def _need(x, what: str = "collection"):
    if x is None:
        raise HTTPException(404, f"unknown {what}")
    return x


def _real(cid: str) -> str:
    if cid == PROMPTS_COLLECTION:
        raise HTTPException(400, "My prompts is built in: it covers your Library and Studio and cannot be changed here")
    return cid


def _bad(e: co.Invalid):
    raise HTTPException(400, str(e))


def _no_model() -> bool:
    return not settings.get("knowledge.embedding_model")


def _prompts_row() -> dict:
    st = service.get().status()
    n = st["by_kind"]["library"] + st["by_kind"]["studio"]
    pr = st["prompts"]
    working = st["state"] == "running"
    # "keyword": the user stopped indexing prompts, so they are searched by keyword only until "Turn on auto-indexing" is pressed
    status = ("empty" if n == 0 else "keyword" if not pr["enabled"] else "waiting_model" if _no_model()
              else "preparing" if pr["pending"] and (working or st["state"] != "off") else "ready")
    pref = co.builtin_prefs()
    share = (pr["count"] - pr["pending"]) / pr["count"] if pr["count"] else 0.0
    return {"id": PROMPTS_COLLECTION, "kind": "collection", "builtin": True, "name": pref["name"], "description": "Library + Studio",
            "tags": [], "star": pref["star"], "documents": n, "prompts": n, "passages": st["passages"]["library"] + st["passages"]["studio"],
            "failed": 0, "status": status, "progress": share, "updated_at": time.time()}


def _fix_status(row: dict) -> dict:
    """A collection whose documents only wait because no embedding model is chosen reads 'waiting_model', not 'preparing'."""
    if row["status"] == "preparing" and _no_model():
        row["status"] = "waiting_model"
    return row


@router.get("")
def list_collections(q: str = "", tag: list[str] = Query([]), show: str = "all", sort: str = "edited", desc: bool = True,
                     page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200)):
    out = co.list_collections(q=q, tags=[t for t in dict.fromkeys(tag) if t], show=show, sort=sort, desc=desc, page=page, page_size=page_size)
    out["items"] = [_fix_status(r) for r in out["items"]]
    words = q.lower().split()
    mine = _prompts_row()
    if page == 1 and not tag and all(w in f"{mine['name'].lower()} my prompts library studio" for w in words) and (show in ("all", mine["status"]) or (show == "ready" and mine["status"] == "ready")):
        out["items"].insert(0, mine)
    return out


@router.post("")
def create(body: Create):
    try:
        c = co.create(body.name, body.description, body.tags)
    except co.Invalid as e:
        _bad(e)
    return co.summary(c["id"])


@router.get("/index")
def index_status():
    return service.get().status()


@router.post("/index/cancel")
def index_cancel():
    service.get().cancel()
    return service.get().status()


@router.post("/index/resume")
def index_resume():
    """Resume after Cancel, and 'Index now': one pass runs even when the auto-index switch is off."""
    ix = service.get()
    ix.resume()
    ix.force = True
    service.kick()
    return ix.status()


class PromptsIndex(BaseModel):
    enabled: bool = True


@router.post("/index/prompts")
def index_prompts(body: PromptsIndex):
    """'Turn on / off auto-indexing': the Library and Studio get vectors (on, the default) or stop getting new ones (off; what is stored stays). On runs a pass now."""
    ix = service.get()
    service.set_prompts_enabled(body.enabled)
    if body.enabled:
        ix.resume()
        ix.force = True
        service.kick()
    return ix.status()


@router.post("/index/rebuild")
def index_rebuild():
    """Index everything again with the chosen embedding model (the Settings page warns first)."""
    ix = service.get()
    ix.cancel()
    ix.rebuild()
    service.kick()
    return ix.status()


@router.get("/setup")
def setup(show_all: bool = False):
    """The state of the setup card: Ollama reachable, which embedding models are installed, which one is chosen, the command to get one."""
    p = service.provider()
    st = p.status() if p else {"reachable": False, "version": "", "error": "Ollama is not configured"}
    installed, err = [], ""
    if st["reachable"]:
        try:
            installed = p.models()
        except ProviderError as e:
            err = str(e)
    models = registry.embedding_models(installed, show_all)
    chosen = settings.get("knowledge.embedding_model")
    return {"ollama": {**st, **registry.describe(p)} if p else st, "models": models, "all_models": installed if show_all else None,
            "chosen": chosen, "chosen_installed": bool(chosen) and chosen in installed, "pull_command": PULL_COMMAND, "error": err,
            "steps": {"ollama": st["reachable"], "model_installed": bool(models), "model_chosen": bool(chosen)}}


@router.post("/search")
def search(body: SearchBody):
    """Passages for a question (the Sources panel and, later, agents). Hybrid when vectors are ready, keyword-only with a `note` otherwise."""
    return retrieval.search(service.get(), service.provider(), body.query, body.scope, body.source, body.tags, max(1, min(body.k, 30)))


@router.post("/docs/{doc}/reindex")
def reindex(doc: str):
    d = _need(service.get().reindex_document(doc), "document")
    service.kick()
    return co.get_document(d["id"])


@router.get("/{cid}")
def get_one(cid: str):
    if cid == PROMPTS_COLLECTION:
        return _prompts_row()
    return _fix_status(_need(co.summary(cid)))


@router.patch("/{cid}")
def patch(cid: str, body: Patch):
    if cid == PROMPTS_COLLECTION:   # built in: only the name and the star can change
        if body.description is not None or body.tags is not None:
            raise HTTPException(400, "My prompts is built in: only its name and star can be changed")
        try:
            co.builtin_update(name=body.name, star=body.star)
        except co.Invalid as e:
            _bad(e)
        return _prompts_row()
    try:
        c = co.update(cid, **body.model_dump(exclude_none=True))
    except co.Invalid as e:
        _bad(e)
    _need(c)
    return _fix_status(co.summary(cid))


@router.delete("/{cid}")
def delete(cid: str):
    _real(cid)
    if not co.trash_collection(cid):
        raise HTTPException(404, "unknown collection")
    service.kick()
    return {"trashed": cid}


@router.patch("/docs/{doc}")
def doc_rename(doc: str, body: DocPatch):
    """Rename a document (its display name only). Shared by every collection that holds it; the indexer picks the new title up on its next pass."""
    try:
        r = co.rename_document(doc, body.name)
    except co.Invalid as e:
        _bad(e)
    service.kick()
    return _need(r, "document")


@router.get("/docs/{doc}/text")
def doc_text(doc: str):
    """The viewer: the stored text, `editable` (false for a PDF, a huge file) with the `reason`, and the `sha256` the next save must quote."""
    return _need(co.read_text(doc), "document")


@router.put("/docs/{doc}/text")
def doc_text_save(doc: str, body: TextBody):
    """Save an edit: the stored file is replaced and read again; the indexer picks it up. 409 when the file changed since it was read."""
    try:
        r = co.write_text(doc, body.text, body.base_sha)
    except co.Conflict as e:
        raise HTTPException(409, str(e))
    except co.Invalid as e:
        _bad(e)
    _need(r, "document")
    service.kick()
    return r


@router.get("/docs/{doc}/passages")
def doc_passages(doc: str):
    """The indexed text: the passages as the model will see them, in order."""
    _need(co.get_document(doc), "document")
    return {"items": co.passages(doc)}


@router.get("/{cid}/documents")
def documents(cid: str):
    if cid == PROMPTS_COLLECTION:
        return {"items": [], "builtin": True, "note": "Your Library and Studio are indexed automatically."}
    _need(co.get(cid))
    member = co.membership()
    # newest first: the order they joined this collection, reversed (storage keeps the order they were added)
    return {"items": [{**d, "collections": member.get(d["id"], [])} for d in reversed(co.documents(cid))], "builtin": False}


@router.put("/{cid}/documents")
async def upload(cid: str, request: Request, name: str = ""):
    """One file as the raw request body (no multipart), named by `?name=`. A file that cannot be read is still stored, as `failed` with the reason."""
    _real(cid)
    _need(co.get(cid))
    data = await request.body()
    try:
        r = co.add_document(cid, name, data)
    except co.Invalid as e:
        _bad(e)
    service.kick()
    return r


@router.post("/{cid}/documents/{doc}/add-to")
def add_to(cid: str, doc: str, body: AddTo):
    """Add a document that is in collection `cid` to another collection (it is stored once)."""
    _real(cid)
    _real(body.collection)
    if doc not in (co.get(cid) or {}).get("documents", []):
        raise HTTPException(404, "the document is not in this collection")
    try:
        co.add_to(body.collection, doc)
    except co.Invalid as e:
        _bad(e)
    service.kick()
    return co.get_document(doc)


@router.delete("/{cid}/documents/{doc}")
def remove(cid: str, doc: str):
    """Take a document out of this collection; out of its last one it goes to the Trash."""
    _real(cid)
    try:
        r = co.remove_from(cid, doc)
    except co.Invalid as e:
        raise HTTPException(404, str(e))
    service.kick()
    return {**r, "id": doc}


# ---------------------------------------------------------------- chat

def _chat_ref(chat: dict | None) -> dict | None:
    return {"id": chat["id"], "title": chat.get("title", "")} if chat else None


async def _chat_events(cid: str, body: ChatBody, message: str):
    """NDJSON events for one question: `sources` (what was found, before the model answers, and the saved conversation it will join), `delta`
    pieces, then `done` with what was sent, or `error`. With history on (Settings > Knowledge) the exchange is saved when the answer is complete
    or stopped with some text; with it off nothing is stored. When the client goes away (Stop) the model call is closed."""
    cfg, know = settings.section_values("assistant"), settings.section_values("knowledge")
    ref = body.model or ModelRef()
    provider_id, name = ref.provider or cfg["default"]["provider"], ref.name or cfg["default"]["model"]
    provider = registry.get(provider_id)
    if provider is None:
        yield _line({"t": "error", "message": f"The provider “{provider_id}” is not configured."})
        return
    if not name:
        yield _line({"t": "error", "message": "Pick a model first."})
        return
    scope = [c for c in dict.fromkeys(body.scope or [cid]) if c]
    chat = (co.get_chat(cid, body.chat) if body.chat else None) if know["history"] else None
    fresh = know["history"] and chat is None   # a new conversation, or the one asked for is gone
    if fresh:
        chat = co.create_chat(cid, scope)
    searched = ragchat.should_search(body.retrieval, message)
    found = {"passages": [], "mode": "keyword", "note": ""}
    if searched:
        found = await asyncio.to_thread(retrieval.search, service.get(), service.provider(), message, scope, "", None, know["top_k"])
    kept, below, best = (found["passages"], [], None) if not searched else ragchat.apply_cutoff(found["passages"], know["min_relevance"] if body.retrieval == "auto" else 0)
    plan = ragchat.build_messages(message, kept, know["instructions"], [t.model_dump() for t in body.history], ragchat.CONTEXT_TURNS, know["num_ctx"])
    cites = {pid: n for n, pid in enumerate(plan["included"], 1)}
    gone = {p["id"] for p in below}
    shown = [{**{k: v for k, v in p.items() if k != "collections"}, "cite": cites.get(p["id"]), **({"below": True} if p["id"] in gone else {})} for p in found["passages"]]
    why = ragchat.why_search(body.retrieval, message)
    info = {"why": why, "best": best, "cutoff": know["min_relevance"] if body.retrieval == "auto" else 0, "below": len(below)}
    yield _line({"t": "sources", "searched": searched, "mode": found["mode"] if searched else "", "note": found["note"], "passages": shown,
                 "chat": _chat_ref(chat), **info})
    params = {"temperature": cfg["temperature"], "num_ctx": know["num_ctx"]}
    it = provider.stream(plan["messages"], {"model": name, **params})
    parts: list[str] = []
    saved = [False]

    def proposal():
        """The revised prompt in a <<<PROMPT block of the answer, if any: shown as a compare card, never applied by itself."""
        text = prompting.parse_proposal("".join(parts))
        return {"text": text, "status": "open"} if text else None

    def save(partial: bool):
        """Store the exchange once. Returns the conversation, or None when history is off."""
        if chat is None or saved[0]:
            return chat
        saved[0] = True
        mode = found["mode"] if searched else ""
        return co.add_exchange(cid, chat["id"], {
            "prompt": message, "response": "".join(parts), "system": plan["system"], "context": plan["context"], "model": {"provider": provider_id, "name": name},
            "params": params, "partial": partial, "searched": searched, "mode": mode, "note": found["note"], "included": plan["included"], "retrieved": shown, "info": info,
            "dropped": plan["dropped"], "cut": plan["cut"], "trimmed": plan["trimmed"], "proposal": proposal()}, scope) or chat

    try:
        while True:
            piece = await asyncio.to_thread(next, it, _END)
            if piece is _END:
                break
            parts.append(piece)
            yield _line({"t": "delta", "text": piece})
        if not "".join(parts).strip():
            yield _line({"t": "error", "message": "The model sent an empty answer."})
            return
        done = save(False)
        yield _line({"t": "done", "model": {"provider": provider_id, "name": name}, "params": params, "system": plan["system"], "context": plan["context"],
                     "included": plan["included"], "dropped": plan["dropped"], "cut": plan["cut"], "trimmed": plan["trimmed"], "searched": searched, **info,
                     "chat": _chat_ref(done), "exchange": done["exchanges"][-1]["id"] if done and done.get("exchanges") else "", "proposal": proposal()})
    except ProviderError as e:
        yield _line({"t": "error", "message": str(e)})
    finally:
        # Stop, a dropped connection or an error after some text: keep what arrived. A new conversation that got nothing is not left behind.
        if "".join(parts).strip():
            save(True)
        elif fresh and chat is not None:
            co.delete_chat(cid, chat["id"])
        threading.Thread(target=_stop, args=(it,), daemon=True).start()


@router.post("/{cid}/chat")
async def chat(cid: str, body: ChatBody):
    """Ask a question about a collection (or several: `scope`). Streams NDJSON. FlowlyStack contacts a model only when this is called, and
    sends only what the `done` event reports back (system message, passages, earlier exchanges, the question)."""
    if cid != PROMPTS_COLLECTION:
        _need(co.get(cid))
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "write a question first")
    return StreamingResponse(_chat_events(cid, body, message), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- saved conversations

def _chats_for(cid: str):
    if cid != PROMPTS_COLLECTION:
        _need(co.get(cid))


@router.get("/{cid}/chats")
def chats(cid: str):
    """The saved conversations, newest first. `history` says whether new ones are being saved (Settings > Knowledge)."""
    _chats_for(cid)
    return {"items": co.list_chats(cid), "history": bool(settings.get("knowledge.history"))}


@router.post("/{cid}/chats")
def chat_create(cid: str, body: NewChat):
    _chats_for(cid)
    try:
        c = co.create_chat(cid, body.scope, body.title)
    except co.Invalid as e:
        _bad(e)
    return c


@router.get("/{cid}/chats/{ch}")
def chat_get(cid: str, ch: str):
    _chats_for(cid)
    return _need(co.get_chat(cid, ch), "conversation")


@router.patch("/{cid}/chats/{ch}")
def chat_rename(cid: str, ch: str, body: RenameChat):
    """Rename and/or pin a conversation (send `title`, `pinned`, or both)."""
    _chats_for(cid)
    if body.title is None and body.pinned is None:
        raise HTTPException(400, "send a title or pinned")
    c = None
    try:
        if body.title is not None:
            c = co.rename_chat(cid, ch, body.title)
        if body.pinned is not None and (c or body.title is None):
            c = co.pin_chat(cid, ch, body.pinned)
    except co.Invalid as e:
        _bad(e)
    return _need(c, "conversation")


@router.patch("/{cid}/chats/{ch}/exchanges/{ex}")
def exchange_patch(cid: str, ch: str, ex: str, body: ExchangePatch):
    """Remember what was done with a proposed edit, so a reload shows Used or Dismissed instead of buttons."""
    _chats_for(cid)
    r = co.set_proposal_status(cid, ch, ex, body.proposal_status)
    if r is None:
        raise HTTPException(404, "unknown conversation or exchange")
    if r is False:
        raise HTTPException(400, "this exchange has no proposal")
    return next(e for e in co.get_chat(cid, ch)["exchanges"] if e["id"] == ex)


@router.delete("/{cid}/chats/{ch}")
def chat_delete(cid: str, ch: str):
    _chats_for(cid)
    if not co.delete_chat(cid, ch):
        raise HTTPException(404, "unknown conversation")
    return {"deleted": ch}


@router.get("/{cid}/chats/{ch}/export")
def chat_export(cid: str, ch: str, format: Literal["md", "json"] = "md"):
    """The conversation as a download: Markdown (`flowlystack-collection-chat`) or JSON."""
    _chats_for(cid)
    c = _need(co.get_chat(cid, ch), "conversation")
    cname = co.builtin_prefs()["name"] if cid == PROMPTS_COLLECTION else (co.get(cid) or {}).get("name", cid)
    base = re.sub(r"[^a-z0-9]+", "-", (c.get("title") or "conversation").lower()).strip("-")[:60] or "conversation"
    disp = {"Content-Disposition": f'attachment; filename="{base}.{format}"'}
    if format == "json":
        return JSONResponse(chatexport.export_json(cid, cname, c), headers=disp)
    return Response(chatexport.export_markdown(cid, cname, c), media_type="text/markdown; charset=utf-8", headers=disp)
