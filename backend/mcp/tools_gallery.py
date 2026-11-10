"""Gallery tools (read only): patterns in the user's own prompts. They read the snapshot the Gallery page already keeps and never start a build."""
from __future__ import annotations

from .common import LIMIT, iso, limit_of
from .server import ToolError, tool


def _snapshot() -> tuple:
    """(status, snapshot) of what the Gallery has built so far, without starting a build."""
    from .. import gallery_api
    a = gallery_api.get()._answer()
    s = a["snapshot"]
    if not s or not s.get("n"):
        raise ToolError("The Gallery has not been built yet, or the Library has no prompts. Ask the user to open Knowledge > Gallery in FlowlyStack once.")
    return a["status"], s


def _status(st: dict, snap: dict) -> dict:
    """`stale` is only true while a rebuild is running; it does not say the Library moved on. So also say whether the snapshot still matches the prompts
    (`out_of_date`: any add, edit, delete or settings change, the same test the Gallery page uses to rebuild) and what can be counted: Library prompts added
    since (not in the snapshot) and removed since (in it, gone now). An edit changes `out_of_date` but not these two counts."""
    from .. import gallery_api, promptstore as ps
    lib, studio = ps.load_all(), ps.load_all(ps.STUDIO_DIR)
    now = {o["id"] for o in lib if (o.get("text") or "").strip()}   # the Gallery leaves out prompts with no text
    had = {r["id"] for r in snap.get("rows", [])}
    added, removed = len(now - had), len(had - now)
    out_of_date = not gallery_api.get().is_current(lib, studio)
    out = {"state": st["state"], "stale": st["stale"], "built_at": iso(st["built_at"]), "method": st["method"], "prompts": st["prompts"], "library_now": len(now),
           "newer_prompts": added, "removed_prompts": removed, "out_of_date": out_of_date}
    if out_of_date:
        bits = [f"{added} Library prompt(s) added" if added else "", f"{removed} removed" if removed else ""]
        what = " and ".join(b for b in bits if b) or "prompts were edited, or a Gallery setting changed"
        out["advice"] = f"This snapshot is out of date ({what} since it was built), so the numbers below may not match the Library. Ask the user to open Knowledge > Gallery in FlowlyStack to refresh it."
    return out


@tool("gallery_overview", "Describe the patterns in the user's Library: how many prompts, the groups they fall into (with their characteristic words), the most distinctive words and phrases, "
      "and how many near-duplicate families exist. Read from the Gallery page's last snapshot; it never triggers a new build.", title="Gallery overview")
def gallery_overview(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    return {"status": _status(st, s), "prompts": s["n"], "agents": s["agents"], "months": [s["months"][0], s["months"][-1]] if s["months"] else [],
            "library_prompts": s["life"]["library"], "studio_prompts": s["life"]["studio"],
            "groups": [{"id": c["id"], "label": c["label"], "prompts": c["n"], "words": c["terms"][:6]} for c in s["clusters"]],
            "top_words": [{"word": t["w"], "prompts": t["df"], "group": t["cluster"]} for t in s["terms"][:25]],
            "top_phrases": [{"phrase": f"{b['a']} {b['b']}", "prompts": b["n"]} for b in s["bigrams"][:10]], "repeat_families": len(s["repeats"])}


@tool("gallery_repeats", "List families of near-duplicate prompts in the Library (three or more nearly the same), largest first, with the prompt ids so you can read them with library_get. "
      "Useful for cleaning up or turning a prompt the user keeps retyping into a Studio prompt.", {"limit": {**LIMIT, "description": "How many families (default 20)."}}, title="Repeated prompts")
def gallery_repeats(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    rows, label = s["rows"], {c["id"]: c["label"] for c in s["clusters"]}
    fams = []
    for r in s["repeats"][:limit_of(args)]:
        ids = [rows[i]["id"] for i in r["ids"] if i < len(rows)]
        fams.append({"prompts": r["n"], "ids": ids[:30], "first": iso(r["first"]), "last": iso(r["last"]), "sample": r["sample"], "group": label.get(r["cluster"], "")})
    return {"status": _status(st, s), "total_families": len(s["repeats"]), "families": fams}


@tool("gallery_group", "List the prompts in one Gallery group (an id from gallery_overview), newest first, with a short excerpt each.",
      {"id": {"type": "integer", "minimum": 0, "maximum": 1000, "description": "A group id from gallery_overview."}, "limit": LIMIT}, required=("id",), title="Prompts in a Gallery group")
def gallery_group(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    c = next((c for c in s["clusters"] if c["id"] == args["id"]), None)
    if not c:
        raise ToolError("No group has that id. Use gallery_overview to list groups.")
    members = sorted((r for r in s["rows"] if r["c"] == c["id"]), key=lambda r: -r["t"])
    return {"status": _status(st, s), "group": {"id": c["id"], "label": c["label"], "prompts": c["n"], "words": c["terms"]}, "returned": min(len(members), limit_of(args)),
            "items": [{"id": r["id"], "title": r["title"], "excerpt": r["s"], "tags": r["tags"], "agent": r["a"], "time": iso(r["t"] / 1000)} for r in members[:limit_of(args)]]}
