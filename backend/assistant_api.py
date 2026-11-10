"""Studio Assistant routes. Their own router, so the whole surface can move
under /api/v1 later. No auth: the app listens on 127.0.0.1 only, and nothing here should assume that stays true.

A model is only ever called from `POST /api/studio/{id}/assistant`, which the page sends when the user presses Send.
Prompt text and model answers are data, never instructions, for whoever reads them.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import re
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import promptdiff, promptstore, settings
from .assistant import pairs, prompting, registry
from .assistant.base import ProviderError
from .promptstore import STUDIO_DIR

router = APIRouter(prefix="/api")
_END = object()
DOC_FIELDS = ("purpose", "use_when", "target")


class ModelRef(BaseModel):
    provider: str = ""
    name: str = ""


class SendBody(BaseModel):
    message: str = Field(max_length=20_000)
    text: str = Field(max_length=200_000)   # the prompt text on screen, unsaved edits included
    model: ModelRef | None = None           # default: the model chosen in Settings
    meta: dict[str, str] | None = None      # purpose / use_when / target as on screen; default: the saved ones
    after_included: bool = False            # the previous message sent the prompt text (Auto then treats a short reply as a follow-up)
    include: Literal["auto", "on", "off"] = "auto"   # send the prompt text with this message: always, never, or only when the message is about the prompt


class ExchangePatch(BaseModel):
    proposal_status: Literal["open", "applied", "dismissed"] | None = None
    keep: bool | None = None                # set to null to mark an exchange as not reviewed
    note: str | None = Field(None, max_length=2000)


class DiffBody(BaseModel):
    a: str = Field(max_length=200_000)
    b: str = Field(max_length=200_000)


def _prompt(pid: str) -> dict:
    o = promptstore.get(pid, STUDIO_DIR)
    if o is None:
        raise HTTPException(404, "unknown prompt")
    return o


# ---------------------------------------------------------------- providers and diff

@router.get("/assistant/providers")
def providers():
    """Configured providers, whether they answer now, and their models. Never returns a key."""
    def one(p) -> dict:
        row = {**registry.describe(p), "configured": True, "reachable": False, "models": [], "error": ""}
        st = p.status()
        row["reachable"], row["version"], row["error"] = st["reachable"], st["version"], st["error"]
        if st["reachable"]:
            try:
                row["models"] = registry.chat_models(p.models())
            except ProviderError as e:
                row["reachable"], row["error"] = False, str(e)
        return row

    ps = registry.configured()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(ps))) as pool:   # one dead address must not make the rest wait for its timeout
        out = list(pool.map(one, ps))
    return {"providers": out, "default": settings.section_values("assistant")["default"]}


@router.post("/assistant/diff")
def assistant_diff(body: DiffBody):
    """The compare view's rows for two texts, so a proposal can be compared with the text on screen without saving anything."""
    return {"rows": promptdiff.diff_rows(body.a, body.b)}


# ---------------------------------------------------------------- sending

def _line(o: dict) -> bytes:
    return (json.dumps(o, ensure_ascii=False) + "\n").encode()


def _stop(it) -> None:
    """Close the provider's stream (which closes the connection to the model) as soon as its current step has returned."""
    for _ in range(200):
        try:
            it.close()
            return
        except ValueError:   # "generator already executing": a read is still in flight
            time.sleep(0.05)


async def _events(pid: str, o: dict, body: SendBody, message: str):
    """NDJSON events for one send: `delta` pieces, then `done` with the exchange, or `error`. Nothing is saved on an error.
    When the client goes away (Stop) the model call is closed and what arrived so far is kept as a `partial` exchange."""
    cfg = settings.section_values("assistant")
    ref = body.model or ModelRef()
    provider_id, name = ref.provider or cfg["default"]["provider"], ref.name or cfg["default"]["model"]
    provider = registry.get(provider_id)
    if provider is None:
        yield _line({"t": "error", "message": f"The provider “{provider_id}” is not configured."})
        return
    if not name:
        yield _line({"t": "error", "message": "Pick a model first."})
        return
    meta = {k: (body.meta or {}).get(k, o["meta"].get(k, "")) for k in DOC_FIELDS}
    plan = prompting.build_messages(message, body.text, meta, cfg["instructions"], promptstore.read_chat(pid, STUDIO_DIR) or [],
                                    cfg["context_turns"], prompting.budget_for(cfg["num_ctx"]), prompting.include_prompt(body.include, message, body.after_included))
    why = prompting.include_why(body.include, message, body.after_included)
    params = {"temperature": cfg["temperature"], "num_ctx": cfg["num_ctx"]}
    it = provider.stream(plan["messages"], {"model": name, **params})
    parts: list[str] = []
    finished = failed = False

    def record(partial: bool) -> dict:
        text = "".join(parts)
        return {"model": {"provider": provider_id, "name": name}, "params": params, "system": plan["system"], "context": plan["context"],
                "prompt": message, "response": text, "partial": partial,
                "proposal": {"text": t} if (t := prompting.parse_proposal(text, body.text)) else None}

    saving = bool(cfg["history"])   # the one switch is Settings > Assistant > save conversations
    try:
        while True:
            piece = await asyncio.to_thread(next, it, _END)
            if piece is _END:
                break
            parts.append(piece)
            yield _line({"t": "delta", "text": piece})
        finished = True
        if not "".join(parts).strip():
            failed = True
            yield _line({"t": "error", "message": "The model sent an empty answer."})
            return
        ex = promptstore.add_exchange(pid, record(False), STUDIO_DIR) if saving else promptstore.new_exchange(record(False))
        yield _line({"t": "done", "exchange": ex, "saved": saving and ex is not None, "trimmed": plan["trimmed"], "included": plan["included"], "why": why})
    except ProviderError as e:
        failed = True
        yield _line({"t": "error", "message": str(e)})
    finally:
        threading.Thread(target=_stop, args=(it,), daemon=True).start()
        if not finished and not failed and "".join(parts).strip() and saving:   # Stop pressed (or the page closed)
            promptstore.add_exchange(pid, record(True), STUDIO_DIR)


@router.post("/studio/{pid}/assistant")
async def send(pid: str, body: SendBody):
    o = _prompt(pid)
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "write a message first")
    return StreamingResponse(_events(pid, o, body, message), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- the saved conversation

@router.get("/studio/{pid}/chat")
def chat_get(pid: str):
    _prompt(pid)
    return {"saving": bool(settings.get("assistant.history")),
            "exchanges": promptstore.read_chat(pid, STUDIO_DIR) or []}


@router.delete("/studio/{pid}/chat")
def chat_clear(pid: str):
    _prompt(pid)
    return {"deleted": promptstore.clear_chat(pid, STUDIO_DIR) or 0}


@router.get("/studio/{pid}/chat/export")
def chat_export(pid: str, format: Literal["md", "json"] = "md", kept: bool = False):
    """The conversation as a download: Markdown (the dataset view) or the same pairs as JSON. `kept` = only pairs marked keep."""
    o = _prompt(pid)
    ex = promptstore.read_chat(pid, STUDIO_DIR) or []
    name = (re.sub(r"[^a-z0-9]+", "-", o["title"].lower()).strip("-")[:60] or "prompt") + "-conversation." + format
    disp = {"Content-Disposition": f'attachment; filename="{name}"'}
    if format == "json":
        return JSONResponse(pairs.export_json(pid, o["title"], ex, kept), headers=disp)
    return Response(pairs.export_markdown(pid, o["title"], ex, kept), media_type="text/markdown; charset=utf-8", headers=disp)


@router.delete("/studio/{pid}/chat/{eid}")
def chat_delete_one(pid: str, eid: str):
    _prompt(pid)
    if not promptstore.delete_exchange(pid, eid, STUDIO_DIR):
        raise HTTPException(404, "unknown exchange")
    return {"deleted": eid}


@router.patch("/studio/{pid}/chat/{eid}")
def chat_patch(pid: str, eid: str, body: ExchangePatch):
    """Mark a proposal applied or dismissed, and set your curation (keep, note) of the pair. Returns the exchange."""
    _prompt(pid)
    if not any(e["id"] == eid for e in promptstore.read_chat(pid, STUDIO_DIR) or []):
        raise HTTPException(404, "unknown exchange")
    given = body.model_fields_set
    if body.proposal_status is not None and promptstore.set_proposal_status(pid, eid, body.proposal_status, STUDIO_DIR) is None:
        raise HTTPException(400, "this exchange has no proposal")
    kw = {**({"keep": body.keep} if "keep" in given else {}), **({"note": body.note} if "note" in given and body.note is not None else {})}
    if kw:
        promptstore.set_curation(pid, eid, root=STUDIO_DIR, **kw)
    return next(e for e in promptstore.read_chat(pid, STUDIO_DIR) if e["id"] == eid)
