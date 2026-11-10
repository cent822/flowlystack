"""Library and Studio tools (read only). The Library is the user's captured prompts; Studio is the prompts they write on purpose."""
from __future__ import annotations

import difflib

from .common import EXCERPT, LIMIT, TAGS, canon_tags, clip, excerpt, iso, limit_of
from .server import ToolError, tool

QUERY = {"type": "string", "maxLength": 200, "description": "Words to look for in the title, text, note and tags. Leave out to list the newest."}


def _plain(s: str) -> str:
    from ..search import MARK_OFF, MARK_ON
    return s.replace(MARK_ON, "").replace(MARK_OFF, "")


def _lib_row(o: dict, hl: dict | None) -> dict:
    from .. import promptstore as ps
    snip = _plain(hl["snippet"])[:EXCERPT] if hl and hl.get("snippet") else ps.summary_row(o)["preview"][:EXCERPT]
    m = o["meta"]
    return {"id": o["id"], "title": o["title"], "excerpt": snip, "tags": m["tags"], "starred": m["starred"], "agent": o["agent"],
            "project": o.get("project", ""), "created": iso(o.get("ts")), "updated": iso(o["updated"]), "edited": o["edited"]}


@tool("library_search",
      "Search the user's Prompt Library: the prompts they sent to Claude Code, Codex or Ollama, captured automatically. Typo-tolerant when the search service runs. "
      "Returns short excerpts; use library_get for the full text of one prompt.",
      {"query": QUERY, "tags": TAGS, "agent": {"type": "string", "maxLength": 40, "description": "Only prompts sent to this agent, e.g. claude, codex, ollama."},
       "starred": {"type": "boolean", "description": "Only starred prompts."}, "limit": LIMIT}, title="Search the Library")
def library_search(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    from ..search import engine
    q = args.get("query", "").strip()
    items = ps.load_all()
    found, hl = engine.match(items, q)
    hits = ps.search(found, "", canon_tags(args.get("tags"), items), "", bool(args.get("starred")), False, args.get("agent", ""))
    if not q:
        hits = ps.sort_items(hits, "updated", True)
    rows = [_lib_row(o, hl.get(o["id"])) for o in hits[:limit_of(args)]]
    return {"query": q, "total_matches": len(hits), "returned": len(rows), "items": rows}


@tool("library_get", "Get one Library prompt in full: its text, title, tags, note, which agent it was sent to, and its version list (without version texts).",
      {"id": {"type": "string", "minLength": 1, "maxLength": 120, "description": "A Library prompt id from library_search."}}, required=("id",), title="Get a Library prompt")
def library_get(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    d = ps.detail(args["id"])
    if not d:
        if args["id"].startswith("ps-"):
            raise ToolError("No Library prompt has that id. It looks like a Studio prompt id (ps-…): use studio_get for it.")
        raise ToolError("No Library prompt has that id. Use library_search to find ids.")
    text, cut = clip(d["text"])
    m = d["meta"]
    return {"id": d["id"], "title": d["title"], "text": text, "truncated": cut, "tags": m["tags"], "note": m["note"], "starred": m["starred"],
            "agent": d["agent"], "model": d.get("model", ""), "project": d.get("project", ""), "created": iso(d.get("ts")), "updated": iso(d["updated"]),
            "edited": d["edited"], "versions": [{"id": r["short"], "message": r["message"], "time": iso(r["ts"])} for r in d["revisions"]]}


@tool("library_list_tags", "List the tags used in the Prompt Library with how many prompts carry each, most used first.",
      {"limit": {**LIMIT, "description": "How many tags (default 20, at most 100)."}}, title="List Library tags")
def library_list_tags(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    items = ps.load_all()
    tags = ps.tag_counts(items, items)
    return {"total_tags": len(tags), "tags": tags[:limit_of(args)]}


# ---------- Studio ----------

def _need_studio(pid: str):
    from .. import promptstore as ps
    if not pid.startswith("ps-"):
        raise ToolError("That is not a Studio prompt id (they start with ps-). Use studio_search to find ids.")
    d = ps.detail(pid, ps.STUDIO_DIR)
    if not d:
        raise ToolError("No Studio prompt has that id. Use studio_search to find ids.")
    return d


def _studio_row(o: dict, hl: dict | None) -> dict:
    from .. import promptstore as ps
    m = o["meta"]
    snip = _plain(hl["snippet"])[:EXCERPT] if hl and hl.get("snippet") else ps.studio_row(o)["preview"][:EXCERPT]
    src = o.get("derived_from")
    return {"id": o["id"], "title": o["title"], "excerpt": snip, "status": m["status"], "tags": m["tags"], "purpose": excerpt(m.get("purpose", ""), 160),
            "target": m.get("target", ""), "starred": m["starred"], "derived_from": src, "created": iso(o.get("ts")), "updated": iso(o["updated"])}


@tool("studio_search",
      "Search the user's Prompt Studio: prompts they wrote or refined on purpose (status draft, refined or final). Returns short excerpts; use studio_get for the full text.",
      {"query": QUERY, "tags": TAGS, "status": {"type": "string", "enum": ["draft", "refined", "final"], "description": "Only prompts in this state."}, "limit": LIMIT},
      title="Search Studio")
def studio_search(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    from ..search import studio_engine
    q = args.get("query", "").strip()
    items = ps.load_all(ps.STUDIO_DIR)
    found, hl = studio_engine.match(items, q)
    hits = ps.search(found, "", canon_tags(args.get("tags"), items))
    if args.get("status"):
        hits = [o for o in hits if o["meta"]["status"] == args["status"]]
    if not q:
        hits = ps.sort_items(hits, "updated", True)
    rows = [_studio_row(o, hl.get(o["id"])) for o in hits[:limit_of(args)]]
    return {"query": q, "total_matches": len(hits), "returned": len(rows), "items": rows}


@tool("studio_get", "Get one Studio prompt in full: text, status, purpose, use-when, target, example, properties, where it was derived from, and its version list.",
      {"id": {"type": "string", "minLength": 1, "maxLength": 120, "description": "A Studio prompt id (ps-…) from studio_search."}}, required=("id",), title="Get a Studio prompt")
def studio_get(args: dict, ctx: dict) -> dict:
    d = _need_studio(args["id"])
    m = d["meta"]
    text, cut = clip(d["text"])
    return {"id": d["id"], "title": d["title"], "text": text, "truncated": cut, "status": m["status"], "tags": m["tags"], "note": m["note"], "starred": m["starred"],
            "purpose": m.get("purpose", ""), "use_when": m.get("use_when", ""), "target": m.get("target", ""), "example": m.get("example", ""),
            "properties": m.get("properties", []), "derived_from": d.get("derived_from"), "created": iso(d.get("ts")), "updated": iso(d["updated"]),
            "versions": [{"id": r["short"], "message": r["message"], "time": iso(r["ts"])} for r in d["revisions"]]}


@tool("studio_versions", "List the versions of a Studio prompt, newest first, with the message the author gave each. Use studio_diff to compare two.",
      {"id": {"type": "string", "minLength": 1, "maxLength": 120}}, required=("id",), title="Studio version history")
def studio_versions(args: dict, ctx: dict) -> dict:
    d = _need_studio(args["id"])
    return {"id": d["id"], "title": d["title"], "versions": [{"id": r["short"], "message": r["message"], "time": iso(r["ts"])} for r in d["revisions"]]}


@tool("studio_diff", "Compare two versions of a Studio prompt as a unified diff (lines starting with - were removed, + added). `b` defaults to the current text.",
      {"id": {"type": "string", "minLength": 1, "maxLength": 120}, "a": {"type": "string", "minLength": 1, "maxLength": 80, "description": "An older version id from studio_versions."},
       "b": {"type": "string", "maxLength": 80, "description": "Another version id, or 'current' (the default)."}}, required=("id", "a"), title="Compare Studio versions")
def studio_diff(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    d = _need_studio(args["id"])
    ra = ps.revision_text(d["id"], args["a"], ps.STUDIO_DIR)
    if not ra:
        raise ToolError("No version has that id. Use studio_versions to list them.")
    which = args.get("b") or "current"
    rb = {"short": "current", "text": d["text"], "message": ""} if which == "current" else ps.revision_text(d["id"], which, ps.STUDIO_DIR)
    if not rb:
        raise ToolError("No version has that id for b. Use studio_versions to list them, or 'current'.")
    lines = list(difflib.unified_diff(ra["text"].splitlines(), rb["text"].splitlines(), f"version {ra['short']}", f"version {rb['short']}", lineterm="", n=3))
    text, cut = clip("\n".join(lines), 60_000)
    return {"id": d["id"], "a": {"id": ra["short"], "message": ra["message"]}, "b": {"id": rb["short"], "message": rb.get("message", "")},
            "changed": bool(lines), "diff": text, "truncated": cut}
