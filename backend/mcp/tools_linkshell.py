"""Linkshell tools (read only): project plans made of linked blocks (Start, Prompt, Spec, Note, Reference)."""
from __future__ import annotations

from .common import LIMIT, TAGS, canon_names, clip, iso, limit_of
from .server import ToolError, tool

PID = {"type": "string", "minLength": 1, "maxLength": 40, "description": "A Linkshell project id (ls-…) from linkshell_list_projects."}
BID = {"type": "string", "minLength": 1, "maxLength": 40, "description": "A block id from linkshell_get_project."}


def _project(pid: str) -> dict:
    from .. import linkshell as ls
    p = ls.get(pid) if isinstance(pid, str) and pid.startswith("ls-") else None
    if not p:
        raise ToolError("No Linkshell project has that id. Use linkshell_list_projects to find ids.")
    return p


@tool("linkshell_list_projects", "List the user's Linkshell projects (plans of linked prompts), newest edited first, with progress and the next step.",
      {"query": {"type": "string", "maxLength": 200, "description": "Words in the name, brief, tags or block titles."}, "tags": TAGS, "limit": LIMIT}, title="List Linkshell projects")
def linkshell_list_projects(args: dict, ctx: dict) -> dict:
    from .. import linkshell as ls
    tags = args.get("tags")
    if tags:   # tags ignore case ("WEB" finds "web"); the app's own filter stays exact
        tags = canon_names(tags, (t for i in ls.list_projects(page_size=10_000)["items"] for t in i["tags"]))
    r = ls.list_projects(q=args.get("query", ""), tags=tags, page_size=limit_of(args))
    return {"total_matches": r["total"], "returned": len(r["items"]),
            "items": [{"id": i["id"], "name": i["name"], "brief": i["brief"], "tags": i["tags"], "default_agent": i["default_agent"], "blocks": i["blocks"],
                       "steps": i["steps"], "done": i["done"], "next": i["next"], "updated": iso(i["updated_at"])} for i in r["items"]]}


@tool("linkshell_get_project",
      "Get the structure of one Linkshell project: its brief, properties, phases (frames), every block (type, title, status, which agent) and the links between them, "
      "and the order to run the prompts in. Block texts are not included; use linkshell_get_block or linkshell_export_plan.", {"id": PID}, required=("id",), title="Get a Linkshell project")
def linkshell_get_project(args: dict, ctx: dict) -> dict:
    from .. import linkshell as ls
    p = _project(args["id"])
    g, proj = p["graph"], p["project"]
    start = next((b for b in g["blocks"] if b["type"] == "start"), None)
    brief, cut = clip(p["texts"].get(start["id"], "") if start else "", 20_000)
    return {"id": proj["id"], "name": proj["name"], "tags": proj.get("tags", []), "default_agent": proj.get("default_agent", "claude"),
            "properties": {q["key"]: q["value"] for q in proj.get("properties", [])}, "brief": brief, "brief_truncated": cut, "stats": ls.stats(g),
            "frames": [{"id": f["id"], "title": f["title"]} for f in g["frames"]],
            "blocks": [{"id": b["id"], "type": b["type"], "title": b["title"], "frame": b["frame"], "status": ls.status_of(g, b), "agent": b["agent"] or proj.get("default_agent", "claude"),
                        "text_chars": len(p["texts"].get(b["id"], "")), "urls": ls.block_urls(b), "files": ls.block_assets(b),
                        **({"file_notes": ls.block_notes(b)} if ls.block_notes(b) else {})} for b in g["blocks"]],
            "links": [{"from": l["from"], "to": l["to"], "kind": l["kind"]} for l in g["links"]],
            "run_order": [b["id"] for b in ls.run_order(g)], "updated": iso(proj.get("updated_at"))}


@tool("linkshell_get_block", "Get one block of a Linkshell project: its text (for Prompt, Spec, Note and Start blocks), status, note and version list.",
      {"project": PID, "block": BID}, required=("project", "block"), title="Get a Linkshell block")
def linkshell_get_block(args: dict, ctx: dict) -> dict:
    from .. import linkshell as ls
    p = _project(args["project"])
    b = next((x for x in p["graph"]["blocks"] if x["id"] == args["block"]), None)
    if not b:
        raise ToolError("That project has no block with that id. Use linkshell_get_project to list blocks.")
    text, cut = clip(p["texts"].get(b["id"], ""))
    vs = ls.revisions(p["project"]["id"], b["id"]) if b["type"] in ls.VERSIONED else []
    return {"project": p["project"]["id"], "id": b["id"], "type": b["type"], "title": b["title"], "status": ls.status_of(p["graph"], b), "note": b.get("note", ""),
            "text": text, "truncated": cut, "urls": ls.block_urls(b), "files": ls.block_assets(b), "file_notes": ls.block_notes(b),
            "versions": [{"id": v["short"], "message": v["message"], "time": iso(v["ts"]), "current": v["current"]} for v in (vs or [])]}


@tool("linkshell_assemble", "Get the exact text the user would paste into an agent for one Prompt block: the prompt, then the Specs linked to it, then its references. "
      "Nothing is filled in or sent anywhere.", {"project": PID, "block": BID}, required=("project", "block"), title="Assemble a Linkshell prompt")
def linkshell_assemble(args: dict, ctx: dict) -> dict:
    from .. import linkshell as ls
    _project(args["project"])
    r = ls.assemble(args["project"], args["block"])
    if not r:
        raise ToolError("That block is not a Prompt block of this project. Only Prompt blocks can be assembled.")
    text, cut = clip(r["text"])
    return {"project": args["project"], "block": args["block"], "text": text, "truncated": cut, "references": r["references"]}


@tool("linkshell_export_plan", "Get a whole Linkshell project as a clean plan an agent can follow: the brief, then each phase with its prompts in run order, "
      "each prompt's full text, the numbers of the prompts it waits for, its Specs and references.", {"project": PID}, required=("project",), title="Export a Linkshell plan")
def linkshell_export_plan(args: dict, ctx: dict) -> dict:
    from .. import linkshell as ls
    _project(args["project"])
    plan = ls.export_plan(args["project"])
    return {"project": args["project"], "plan": plan}
