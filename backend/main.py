import asyncio
import json
import os
import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel

from . import about_api, assistant_api, auth_api, collections as co, collections_api, gallery_api, kgraph_api, linkshell, linkshell_api, mcp_api, profile_api, promptstore, promptsync, queries, samples_api, settings_api, sources, studio_api
from .config import CONFIG, FRONTEND_DIR, PROJECTS_DIR, PROMPTS_DIR, ROOT
from .db import connect
from .ingest import scan
from .promptstore import STUDIO_DIR
from .rag import service as rag_service
from .search import engine, linkshell_engine, studio_engine

app = FastAPI(title="flowlystack")
app.include_router(auth_api.router)   # Login: /api/auth (the gate below protects everything else)
app.include_router(studio_api.router)   # Prompt Studio: /api/studio (before the static mount at the end)
app.include_router(linkshell_api.router)   # Linkshell: /api/linkshell
app.include_router(profile_api.router)   # Owner profile picture: /api/profile (gated; the rename is /api/auth/username)
app.include_router(about_api.router)   # Version and release notes: /api/about
app.include_router(samples_api.router)   # First-run sample content: /api/samples (added only by a button press)
app.include_router(settings_api.router)   # Settings page: /api/settings
app.include_router(collections_api.router)   # Collections: /api/collections
app.include_router(gallery_api.router)   # Gallery: /api/gallery
app.include_router(kgraph_api.router)   # Lattice (knowledge graph): /api/kgraph
app.include_router(assistant_api.router)   # Studio Assistant: /api/assistant and /api/studio/{id}/assistant, /chat
app.include_router(mcp_api.router)   # MCP: POST /mcp (token, not session; off until Settings > MCP is switched on)
con = connect()
lock = threading.Lock()          # one sqlite connection shared by the poller and request threads
version = {"n": 0}               # bumps whenever new transcript lines land; SSE clients watch it


def q(fn, *a):
    with lock:
        return fn(con, *a)


def sync_search(wait: bool = False):
    """Make the search indexes match the prompt files, Library and Studio (no-op without Meilisearch)."""
    studio_api.sync_search(wait)
    linkshell_api.sync_search(wait)
    return engine.reconcile(promptstore.load_all(), wait)


def empty_expired_trash():
    """Delete trashed prompts past their retention (trash.days in the config; 0 turns this off), Library and Studio."""
    days = CONFIG["trash"]["days"]
    return (promptstore.purge_expired(days) + promptstore.purge_expired(days, STUDIO_DIR) + linkshell.purge_expired(days) + linkshell.purge_removed(days) + co.purge_expired(days))


@app.on_event("startup")
async def start():
    await asyncio.to_thread(rag_service.trim_vectors)   # an index from before the version cleanup can be GBs of old versions (a no-op when there is none)
    with lock:
        scan(con)

    async def poll():
        n = 0
        while True:
            await asyncio.sleep(CONFIG["poll_seconds"])
            with lock:
                if scan(con):
                    version["n"] += 1
            n += 1
            if n % 5 == 0:   # the hook writes prompt files on its own; pick them up for the search index
                await asyncio.to_thread(sync_search)
            if n % 1800 == 0:   # about hourly
                await asyncio.to_thread(empty_expired_trash)
    asyncio.create_task(poll())

    async def poll_source(mod):   # other agents ingest in their own task, so they can never stall the Claude poll
        while True:
            if await asyncio.to_thread(mod.scan):
                version["n"] += 1
            await asyncio.sleep(getattr(mod, "INTERVAL", CONFIG["poll_seconds"]))
    async def sync_prompts(agent):   # opt-in per agent (the Capture setup card); each agent has its own task and error state
        while True:
            if promptsync.is_enabled(agent):
                await asyncio.to_thread(promptsync.run, agent)
            await asyncio.sleep(promptsync.AGENTS[agent]["interval"])
    for agent in promptsync.AGENTS:
        if promptsync.available(agent):
            asyncio.create_task(sync_prompts(agent))
    for sid in sources.enabled():
        mod = sources.adapter(sid) if sid != sources.DEFAULT and sources.detected(sid) else None
        if mod:
            asyncio.create_task(poll_source(mod))
    asyncio.create_task(asyncio.to_thread(empty_expired_trash))
    asyncio.create_task(asyncio.to_thread(sync_search, True))

    async def index_loop():   # Collections: keeps the keyword index and the vectors in step; wakes at once when a route changes something
        ix = rag_service.get()
        await asyncio.to_thread(ix.recover)
        rag_service.kick()
        while True:
            await asyncio.to_thread(rag_service.kicked.wait, 5)
            rag_service.kicked.clear()
            try:
                force, ix.force = ix.force, False
                if force or await asyncio.to_thread(ix.due):
                    await asyncio.to_thread(ix.run_once, force)
            except Exception as e:   # never let a bad pass end the loop; the status shows the error on the next look
                print(f"flowlystack: collections indexing failed: {e}")
    asyncio.create_task(index_loop())


def via(source: str, name: str, *a):
    """Another agent's answer for a Dashboard route. Claude never comes through here."""
    if source not in sources.SOURCES:
        raise HTTPException(404, f"unknown source: {source}")
    mod = sources.adapter(source)
    if mod is None:
        return sources.na(f"The {sources.SOURCES[source]['label']} adapter is not built yet.")
    try:
        return getattr(mod, name)(*a)
    except Exception as e:   # a broken adapter must never take the Claude dashboard down
        return sources.na(f"{sources.SOURCES[source]['label']} could not be read: {e}")


@app.get("/api/sources")
def source_list(): return sources.listing()
@app.get("/api/overview")
def overview(source: str = sources.DEFAULT): return q(queries.overview) if source == sources.DEFAULT else via(source, "overview")
@app.get("/api/limits")
def limits(source: str = sources.DEFAULT): return q(queries.limits) if source == sources.DEFAULT else via(source, "limits")
@app.get("/api/sessions")
def sessions(limit: int = Query(40, le=200), source: str = sources.DEFAULT):
    return q(queries.sessions, limit) if source == sources.DEFAULT else via(source, "sessions", limit)
@app.get("/api/daily")
def daily(days: int = Query(120, le=730), source: str = sources.DEFAULT):
    return q(queries.daily, days) if source == sources.DEFAULT else via(source, "daily", days)
@app.get("/api/heatmap")
def heatmap(source: str = sources.DEFAULT): return q(queries.heatmap) if source == sources.DEFAULT else via(source, "heatmap")
@app.get("/api/projects")
def projects(source: str = sources.DEFAULT): return q(queries.projects) if source == sources.DEFAULT else via(source, "projects")
@app.get("/api/tools")
def tools(source: str = sources.DEFAULT): return q(queries.tools) if source == sources.DEFAULT else via(source, "tools")
@app.get("/api/live")
def live(source: str = sources.DEFAULT): return queries.live_sessions() if source == sources.DEFAULT else via(source, "live")


class MetaPatch(BaseModel):
    tags: list[str] | None = None
    note: str | None = None
    title: str | None = None
    starred: bool | None = None


class TextSave(BaseModel):
    text: str
    message: str = ""


@app.get("/api/prompts")
def prompts(q: str = "", tag: list[str] = Query([]), project: str = "", starred: bool = False, edited: bool = False, agent: str = "",
            sort: str = "updated", desc: bool = True, page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=200)):
    items = promptstore.load_all()
    found, hl = engine.match(items, q)   # text match (ranked) with highlights; the other filters apply on top of it
    tags = [t for t in dict.fromkeys(tag) if t]   # repeated ?tag=a&tag=b, all must match
    base = promptstore.search(found, "", None, project, starred, edited, agent)
    hits = promptstore.sort_items(promptstore.search(base, "", tags), sort, desc)
    pages = max(1, -(-len(hits) // page_size))
    page = min(page, pages)
    rows = hits[(page - 1) * page_size: page * page_size]
    return {"total": len(items), "matched": len(hits), "page": page, "pages": pages, "page_size": page_size,
            "engine": engine.status()["engine"],
            **{**promptstore.summarize(items), "tags": promptstore.tag_counts(items, promptstore.search(base, "", tags))},
            "items": [{**promptstore.summary_row(o), **({"hl": hl[o["id"]]} if o["id"] in hl else {})} for o in rows]}


@app.get("/api/search/status")
def search_status():
    """The Library's status as before, plus `indexes` with one status per feature."""
    return {**engine.status(), "indexes": {"prompts": engine.status(), "studio": studio_engine.status(), "linkshell": linkshell_engine.status(),
                                            "collections": rag_service.get().keyword.status()}}


@app.post("/api/search/rebuild")
def search_rebuild(index: str = "prompts"):
    """Rebuild one index from the files: `prompts` (default, the Library), `studio`, `linkshell`, or `all` (Library result plus one key per other index)."""
    if index not in ("prompts", "studio", "linkshell", "collections", "all"):
        raise HTTPException(400, "index must be prompts, studio, linkshell, collections or all")
    out = {}
    for name, eng, items in (("prompts", engine, lambda: promptstore.load_all()),
                             ("studio", studio_engine, lambda: promptstore.load_all(STUDIO_DIR)),
                             ("linkshell", linkshell_engine, linkshell.search_items)):
        if index in (name, "all"):
            r = eng.rebuild(items())
            if r is None and eng.name != "substring":
                raise HTTPException(503, "search service is not reachable")
            out[name] = r or {"indexed": 0, "removed": 0}
    if index in ("collections", "all"):   # the passage index is rebuilt by the indexer, which sends everything again on its next pass
        ix = rag_service.get()
        if ix.keyword.configured and not ix.rebuild_keyword():
            raise HTTPException(503, "search service is not reachable")
        rag_service.kick()
        out["collections"] = {"queued": True, "configured": ix.keyword.configured}
    return out["prompts"] if index == "prompts" else out[index] if index != "all" else {**out["prompts"], "studio": out["studio"], "linkshell": out["linkshell"], "collections": out["collections"]}


def _hook_command(script: str) -> str:
    """The command a hook runs. From source: python3 plus the script's path. In Docker the script lives in the container, so the host
    hook runs it there through the entrypoint, which drops to PUID:PGID, so the files it writes belong to the same user as the app's (a plain
    docker exec runs as root). The prompt file lands in the mounted prompts folder; output is dropped and the exit code is always 0."""
    if os.environ.get("FLOWLYSTACK_IN_DOCKER"):
        name = os.environ.get("FLOWLYSTACK_CONTAINER") or "flowlystack-app"
        return f"docker exec -i {name} /usr/local/bin/entrypoint.sh python hooks/{script} >/dev/null 2>&1 || true"
    return f"python3 {ROOT / 'hooks' / script}"


@app.get("/api/prompts/setup")
def prompts_setup():
    cmd = _hook_command("capture_prompt.py")
    snippet = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": cmd}]}]}}
    codex_cmd = _hook_command("capture_codex_prompt.py")   # Codex hooks.json has the same shape as Claude's
    codex_snippet = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": codex_cmd}]}]}}
    folder = "./prompts (next to your docker-compose.yml)" if os.environ.get("FLOWLYSTACK_IN_DOCKER") else str(PROMPTS_DIR)
    return {"dir": folder, "command": cmd, "snippet": snippet, "in_docker": bool(os.environ.get("FLOWLYSTACK_IN_DOCKER")),
            "settings_file": "~/.claude/settings.json", "saved": len(promptstore.load_all()),
            "codex": {"command": codex_cmd, "snippet": codex_snippet, "settings_file": "~/.codex/hooks.json"}}


class SyncPatch(BaseModel):
    enabled: bool


@app.get("/api/prompts/sync")
def prompts_sync_status(): return promptsync.status()


def _sync_agent(agent: str) -> str:
    if agent not in promptsync.AGENTS:
        raise HTTPException(404, "unknown agent")
    if not promptsync.available(agent):
        raise HTTPException(409, f"{promptsync.AGENTS[agent]['label']} is not available on this machine")
    return agent


@app.put("/api/prompts/sync/{agent}")
def prompts_sync_set(agent: str, patch: SyncPatch):
    """The Live sync switch for Codex or Open WebUI: on = keep importing new prompts in the background."""
    return promptsync.set_enabled(_sync_agent(agent), patch.enabled)


@app.post("/api/prompts/sync/{agent}/import")
def prompts_sync_import(agent: str):
    """The Import button: import what is new right now (repeatable; anything already imported is skipped)."""
    r = promptsync.run_once(_sync_agent(agent))
    sync_search()
    return r


@app.post("/api/prompts/import")
def prompts_import():
    r = promptstore.import_transcripts(PROJECTS_DIR)
    sync_search()
    return r


@app.get("/api/prompts/{pid}")
def prompt_detail(pid: str):
    d = promptstore.detail(pid)
    if d is None:
        raise HTTPException(404, "unknown prompt")
    return d


@app.patch("/api/prompts/{pid}")
def prompt_meta(pid: str, patch: MetaPatch):
    meta = promptstore.update_meta(pid, patch.model_dump(exclude_none=True))
    if meta is None:
        raise HTTPException(404, "unknown prompt")
    sync_search()
    return meta


@app.put("/api/prompts/{pid}/text")
def prompt_text(pid: str, body: TextSave):
    d = promptstore.save_text(pid, body.text, body.message)
    if d is None:
        raise HTTPException(404, "unknown prompt")
    sync_search()
    return d


@app.get("/api/prompts/{pid}/revisions/{rev}")
def prompt_revision(pid: str, rev: str):
    r = promptstore.revision_text(pid, rev)
    if r is None:
        raise HTTPException(404, "unknown revision")
    return r


@app.delete("/api/prompts/{pid}/revisions/{rev}")
def prompt_revision_delete(pid: str, rev: str):
    d = promptstore.delete_revision(pid, rev)
    if d is None:
        raise HTTPException(404, "unknown revision")
    if d is False:
        raise HTTPException(400, "the current version cannot be deleted")
    return d


@app.get("/api/prompts/{pid}/diff")
def prompt_diff(pid: str, a: str, b: str = "current"):
    d = promptstore.diff(pid, a, b)
    if d is None:
        raise HTTPException(404, "unknown revision")
    return d


@app.delete("/api/prompts/{pid}")
def prompt_delete(pid: str):
    if not promptstore.trash(pid):
        raise HTTPException(404, "unknown prompt")
    sync_search()
    return {"trashed": pid}


# One Trash for all three stores. Ids cannot collide: Studio ids start with `ps-`, Linkshell ids with `ls-`, Library ids with a date.

def _co_row(r: dict, days: int) -> dict:
    """A trashed collection or document shaped like a prompt row; `kind` says which, so the Trash page can label it."""
    preview = f"{r['documents']} document{'' if r['documents'] == 1 else 's'}" if r["kind"] == "collection" else f"{r['size']:,} bytes"
    return {"id": r["id"], "title": r["name"], "preview": preview, "project": "", "ts": r["deleted_at"], "deleted_at": r["deleted_at"], "edited": False,
            "tags": r["tags"], "store": "collections", "kind": r["kind"], "purge_at": r["deleted_at"] + days * 86400 if days else None}


def _store(pid: str) -> tuple[str, object]:
    """Which store a trashed id belongs to, and that store's root (None = the store's default root)."""
    return (("studio", STUDIO_DIR) if pid.startswith("ps-") else ("linkshell", None) if pid.startswith("ls-")
            else ("collections", None) if pid.startswith(("col-", "kd-")) else ("library", None))


def _ls_row(r: dict, days: int) -> dict:
    """A trashed Linkshell project shaped like a prompt row, so the Trash page lists it unchanged."""
    return {"id": r["id"], "title": r["name"], "preview": f"{r['blocks']} block{'' if r['blocks'] == 1 else 's'}", "project": "", "ts": r["deleted_at"],
            "deleted_at": r["deleted_at"], "edited": False, "tags": r["tags"], "store": "linkshell", "purge_at": r["deleted_at"] + days * 86400 if days else None}


@app.get("/api/trash")
def trash_list():
    days = CONFIG["trash"]["days"]
    items = [{**promptstore.trash_row(o, days), "store": store}
             for store, root in (("library", None), ("studio", STUDIO_DIR)) for o in promptstore.load_trash(root)]
    items += [_ls_row(r, days) for r in linkshell.load_trash()]
    items += [_co_row(r, days) for r in co.load_trash()]
    items.sort(key=lambda r: r["deleted_at"], reverse=True)
    return {"count": len(items), "days": days, "items": items}


@app.get("/api/trash/count")
def trash_count(): return {"count": len(promptstore.load_trash()) + len(promptstore.load_trash(STUDIO_DIR)) + len(linkshell.load_trash()) + len(co.load_trash())}


@app.get("/api/trash/{pid}")
def trash_detail(pid: str):
    store, root = _store(pid)
    if store == "linkshell":
        r = next((x for x in linkshell.load_trash() if x["id"] == pid), None)
        if r is None:
            raise HTTPException(404, "not in the trash")
        return {**_ls_row(r, CONFIG["trash"]["days"]), "text": f"Linkshell project “{r['name']}”, {r['blocks']} block(s). Restore it to open it again."}
    if store == "collections":
        r = next((x for x in co.load_trash() if x["id"] == pid), None)
        if r is None:
            raise HTTPException(404, "not in the trash")
        what = f"Collection “{r['name']}”, {r['documents']} document(s)." if r["kind"] == "collection" else f"Document “{r['name']}”."
        return {**_co_row(r, CONFIG["trash"]["days"]), "text": what + " Restore it to use it again."}
    o = promptstore.trash_get(pid, root)
    if o is None:
        raise HTTPException(404, "not in the trash")
    return {**promptstore.trash_row(o, CONFIG["trash"]["days"]), "store": store, "text": o["text"]}


@app.post("/api/trash/{pid}/restore")
def trash_restore(pid: str):
    if pid.startswith("ls-"):
        if not linkshell.restore(pid):
            raise HTTPException(404, "not in the trash")
        linkshell_api.sync_search()
        return {"restored": pid}
    if pid.startswith(("col-", "kd-")):
        if not any(x["id"] == pid for x in co.load_trash()):
            raise HTTPException(404, "not in the trash")
        if not co.restore(pid):
            raise HTTPException(409, "a collection with this id already exists" if pid.startswith("col-") else "none of its collections exists any more; restore a collection first")
        rag_service.kick()
        return {"restored": pid}
    r = promptstore.restore(pid, _store(pid)[1])
    if r is None:
        raise HTTPException(404, "not in the trash")
    if r is False:
        raise HTTPException(409, "a prompt with this id already exists")
    sync_search()
    return {"restored": pid}


@app.delete("/api/trash/{pid}")
def trash_purge(pid: str):
    if not (linkshell.purge(pid) if pid.startswith("ls-") else co.purge(pid) if pid.startswith(("col-", "kd-")) else promptstore.purge(pid, _store(pid)[1])):
        raise HTTPException(404, "not in the trash")
    return {"deleted": pid}


@app.delete("/api/trash")
def trash_empty(): return {"deleted": promptstore.empty_trash() + promptstore.empty_trash(STUDIO_DIR) + linkshell.empty_trash() + co.empty_trash()}


@app.get("/api/stream")
async def stream():
    """Server-Sent Events: emits `update` when data changes, `tick` every few seconds for live status."""
    async def gen():
        seen, beat = version["n"], 0
        yield "retry: 3000\n\n"
        while True:
            await asyncio.sleep(1)
            beat += 1
            if version["n"] != seen:
                seen = version["n"]
                yield "event: update\ndata: {}\n\n"
            elif beat % 5 == 0:
                yield "event: tick\ndata: {}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.middleware("http")
async def revalidate_frontend(request, call_next):
    # Frontend files change while developing; make browsers revalidate (ETag) instead of reusing a stale copy.
    resp = await call_next(request)
    if not request.url.path.startswith("/api/") and request.url.path != "/mcp":   # (/mcp sets its own no-store)
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.middleware("http")(auth_api.gate)   # no session: /api answers 401, pages redirect to /login (FLOWLYSTACK_AUTH=off turns it off)


@app.get("/login")
def login_page(): return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/")
def index(): return FileResponse(FRONTEND_DIR / "index.html")
app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="static")
