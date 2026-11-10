"""Write tools. Only a token with the `write` scope sees them. They only ever ADD: a new prompt, a new version, a new
project. Nothing is deleted or overwritten, everything an agent makes carries the tag `via-mcp` and a line in the activity list (Settings > MCP), where
the user can undo it. The descriptions tell the agent to save only after the user has agreed."""
from __future__ import annotations

from . import activity, plan as planmod, sync
from .server import ToolError, tool
from .tools_library import _need_studio

TEXT_IN = 200_000
AGREE = "Only call this after the user has agreed to save it (show them what you are about to save first). "
NOTE = "It was saved as a draft in the user's own Prompt Studio; they review it there, and Settings > MCP lists it with an Undo."


def _by(ctx: dict) -> str:
    return f"via MCP: {ctx.get('name', '')}"


@tool("studio_create",
      "Save a new prompt in the user's Prompt Studio as a draft (status draft, tag via-mcp). " + AGREE + "Use it for a polished or newly written prompt. "
      "If it improves a Library prompt, pass that prompt's id as from_library so Studio links back to the original. It never overwrites anything: it always makes a new prompt.",
      {"text": {"type": "string", "minLength": 1, "maxLength": TEXT_IN, "description": "The full prompt text."},
       "title": {"type": "string", "maxLength": 200, "description": "A short name. Leave out to use the first line."},
       "tags": {"type": "array", "maxItems": 19, "items": {"type": "string", "maxLength": 40}, "description": "Optional tags. via-mcp is added for you."},
       "from_library": {"type": "string", "maxLength": 120, "description": "The Library prompt id this one was derived from (from library_search)."}},
      required=("text",), scope="write", title="Save a Studio prompt")
def studio_create(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    text = args["text"]
    if not text.strip():
        raise ToolError("The prompt text is empty.")
    derived, others = None, []
    lib = args.get("from_library")
    if lib:
        if not ps.get(lib):
            raise ToolError("No Library prompt has that id (from_library). Use library_search to find ids, or leave from_library out.")
        derived = {"store": "library", "id": lib}
        others = [o["id"] for o in ps.load_all(ps.STUDIO_DIR) if (o.get("derived_from") or {}).get("id") == lib]
    tags = list(dict.fromkeys([t.strip() for t in args.get("tags", []) if t.strip()] + [planmod.MARK]))
    d = ps.create_studio(text, args.get("title", "").strip(), tags, derived, root=ps.STUDIO_DIR, message=f"Created ({_by(ctx)})")
    sync.studio_changed()
    a = activity.record(ctx, "studio_create", "studio", d["id"], d["title"])
    out = {"id": d["id"], "title": d["title"], "status": d["meta"]["status"], "tags": d["meta"]["tags"], "derived_from": d.get("derived_from"), "open": "#/studio/" + d["id"],
           "activity_id": a["id"], "message": NOTE}
    if others:
        out["other_copies"] = others
        out["warning"] = "Studio already had a copy of this Library prompt (see other_copies); this made another one."
    return out


@tool("studio_save_version",
      "Add a new version to an existing Studio prompt (the old versions stay in its history). " + AGREE + "Pass the complete new text, not a patch. "
      "If the text is identical to the current one nothing is saved. Read the prompt with studio_get first.",
      {"id": {"type": "string", "minLength": 1, "maxLength": 120, "description": "A Studio prompt id (ps-…)."},
       "text": {"type": "string", "minLength": 1, "maxLength": TEXT_IN, "description": "The complete new text of the prompt."},
       "message": {"type": "string", "maxLength": 150, "description": "A short note on what changed, shown in the version history."}},
      required=("id", "text"), scope="write", title="Save a new Studio version")
def studio_save_version(args: dict, ctx: dict) -> dict:
    from .. import promptstore as ps
    d = _need_studio(args["id"])
    text = args["text"]
    if not text.strip():
        raise ToolError("The new text is empty.")
    if text == d["text"]:
        return {"id": d["id"], "title": d["title"], "changed": False, "message": "The text is identical to the current version, so nothing was saved."}
    prev = d["revisions"][0]["short"] if d["revisions"] else ""
    after = ps.save_text(d["id"], text, f"{(args.get('message') or '').strip() or 'Update'} ({_by(ctx)})", ps.STUDIO_DIR)
    new = after["revisions"][0]["short"]
    sync.studio_changed()
    a = activity.record(ctx, "studio_save_version", "studio", d["id"], d["title"], version=new, prev_version=prev)
    return {"id": d["id"], "title": d["title"], "changed": True, "version": new, "previous_version": prev, "open": "#/studio/" + d["id"], "activity_id": a["id"],
            "message": "A new version was added; the earlier ones are still in its history. Settings > MCP lists it with an Undo."}


PLAN_SHAPE = {"type": "object", "description": (
    "The plan. Fields: name (required); brief (what the project is for); default_agent (default claude); tags (list); properties (object of text values); "
    "phases (required): a list of {title, prompts}, each prompt {key, title, text, agent?, after?, specs?}. "
    "`key` is a short unique id (letters, digits, - or _). `after` is a list of keys this prompt waits for: leave it out and the prompt follows the previous one in the plan "
    "(the first follows the Brief); [] means it only waits for the Brief (so it can run in parallel). `specs` is a list of {title, text} reference texts attached to that prompt."),
    "properties": {
        "name": {"type": "string"}, "brief": {"type": "string"}, "default_agent": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}},
        "properties": {"type": "object", "additionalProperties": {"type": "string"}},
        "phases": {"type": "array", "items": {"type": "object", "required": ["title", "prompts"], "properties": {
            "title": {"type": "string"},
            "prompts": {"type": "array", "items": {"type": "object", "required": ["key", "title", "text"], "properties": {
                "key": {"type": "string"}, "title": {"type": "string"}, "text": {"type": "string"}, "agent": {"type": "string"},
                "after": {"type": "array", "items": {"type": "string"}},
                "specs": {"type": "array", "items": {"type": "object", "required": ["title", "text"], "properties": {"title": {"type": "string"}, "text": {"type": "string"}}}}}}}}}}},
    "required": ["name", "phases"]}


@tool("linkshell_create_project_from_plan",
      "Create a NEW Linkshell project from a plan: phases of prompts that run in order, with optional specs. " + AGREE.replace("save it", "create it") +
      "Draft the plan in the conversation first, let the user agree, then call this once. It always makes a new project and never touches existing ones; the user then opens it "
      "on the canvas, reads the Brief, ticks it and follows the steps (they can press Tidy up to rearrange). Blocks are laid out for you.",
      {"plan": PLAN_SHAPE}, required=("plan",), scope="write", title="Create a Linkshell project")
def linkshell_create_project_from_plan(args: dict, ctx: dict) -> dict:
    from .. import linkshell as ls
    try:
        data, st = planmod.build(args["plan"])
        p = ls.import_json(data)
    except planmod.PlanError as e:
        raise ToolError(str(e))
    except ls.Invalid as e:
        raise ToolError("The `after` links make a loop: a prompt cannot wait, directly or through others, for itself. Fix the plan." if "loop" in str(e) else f"The plan was refused: {e}")
    pid, name = p["project"]["id"], p["project"]["name"]
    sync.linkshell_changed()
    a = activity.record(ctx, "linkshell_create_project_from_plan", "linkshell", pid, name)
    return {"id": pid, "name": name, "phases": st["phases"], "prompts": st["prompts"], "specs": st["specs"], "links": st["links"], "tags": st["tags"], "open": "#/linkshell/" + pid,
            "activity_id": a["id"], "message": "A new project was created. The Brief is not ticked yet: the user reads the plan, ticks it, then the first prompts become ready. Settings > MCP lists it with an Undo."}
