"""Lattice tools (read only): how the user's prompts, Studio prompts and documents connect. They read the base
snapshot the Lattice page keeps. If none exists yet they start the same background build the page starts (it reads the user's files and the stored
vectors, calls no model and writes only its own cache), and say it is being built. Similar-in-meaning lines are estimates, never facts."""
from __future__ import annotations

from collections import deque
from urllib.parse import quote

from .. import kgraph, settings
from . import activity
from .common import LIMIT, iso, limit_of
from .server import ToolError, tool
from .tools_write import AGREE

FLOOR, CLOSEST = 0.4, 5          # the page's defaults for the "similar" lines
ITEMS = ("prompt", "studio", "document")
TYPES = ("prompt", "studio", "document", "collection", "tag", "project", "reference", "linkshell")
SEARCH_TYPES = TYPES + ("entity",)    # entities are the agent-made layer (people, technologies, concepts ...), searched by name or alias
LAYERS = {"type": "array", "maxItems": 2, "items": {"type": "string", "enum": ["explicit", "similar"]}, "description": "Which kinds of line to follow (default both). explicit = collection, tag, project, derived from, followed by (the next prompt of the same session), same text, refers to (both name the same link, file or ticket id), used in (a prompt used in a Linkshell project), names a document, and the entity layer (mentions = an entity found in an item, related = a link between two entities, each with its quote); similar = estimated by meaning."}
SCORE = {"type": "number", "minimum": 0.2, "maximum": 1, "description": f"Smallest similarity score for a similar line (default {FLOOR}; scores are low, 0.4 is already close)."}
CLOSE = {"type": "integer", "minimum": 1, "maximum": 12, "description": f"How many closest neighbours each item may have (default {CLOSEST})."}
NODE = {"type": "string", "minLength": 1, "maxLength": 200, "description": "A node id from graph_search, graph_neighbors or graph_overview (a Library prompt id, a Studio id ps-…, a document id kd-…, a collection id col-…, tag:<name>, project:<name>, ref:<kind>:<name> or an entity id en-…)."}
READ_WITH = "Read an item's text with library_get (Library), studio_get (Studio) or collections_search (documents)."


def _snapshot() -> tuple:
    """(status, snapshot) of the Lattice base layer. Starts the background build when there is none (and the page's own recheck rules otherwise)."""
    from .. import kgraph_api
    a = kgraph_api.get().get()
    s = a["snapshot"]
    if not s:
        if a["status"]["state"] == "error":
            raise ToolError("Lattice could not be built: " + (a["status"].get("error") or "unknown error") + ". Ask the user to open Knowledge > Lattice and press Refresh.")
        raise ToolError("Lattice is being built from the user's files (no model is called). Try again in a few seconds.")
    if not s.get("n_items"):
        raise ToolError("There is nothing to connect yet: the user has no prompts, Studio prompts or documents.")
    return a["status"], s


def _status(st: dict, s: dict) -> dict:
    return {"state": st["state"], "stale": st["stale"], "built_at": iso(st["built_at"]), "method": s["method"], "items": s["n_items"],
            "note": {"embeddings": "similar lines are estimated from the stored embeddings", "tfidf-svd": "similar lines are estimated from shared words (no stored vectors for most items)",
                     "none": "no similar lines"}.get(s["method"], "")}


def _href(s: dict, i: int, adj: list) -> str:
    n = s["nodes"][i]
    if n["t"] == "prompt":
        return "#/prompts/" + n["id"]
    if n["t"] == "studio":
        return "#/studio/" + n["id"]
    if n["t"] == "collection":
        return "#/collections/" + n["id"]
    if n["t"] == "linkshell":
        return "#/linkshell/" + n["id"].split(":", 1)[1]
    if n["t"] == "document":
        for ei in adj[i]:
            e = s["edges"][ei]
            if e[2] == "in_collection" and e[0] == i:
                return f"#/collections/{s['nodes'][e[1]]['id']}/documents/{n['id']}"
    return ""


def _adj(s: dict) -> list:
    adj = [[] for _ in s["nodes"]]
    for k, e in enumerate(s["edges"]):
        adj[e[0]].append(k)
        adj[e[1]].append(k)
    return adj


def _on(e: list, layers, floor: float, closest: int) -> bool:
    if e[2] == "similar":
        return "similar" in layers and e[3] >= floor and e[4] < closest
    return "explicit" in layers


def _index(s: dict, ref: str) -> int:
    for i, n in enumerate(s["nodes"]):
        if n["id"] == ref:
            return i
    raise ToolError(f"No node has the id {ref!r}. Find ids with graph_search or graph_overview.")


def _view(s: dict, i: int, adj: list) -> dict:
    n = s["nodes"][i]
    return {"id": n["id"], "type": n["t"], **({"reference_kind": n["rk"]} if n.get("rk") else {}), "title": n["n"], "connections": n["d"], "open": _href(s, i, adj)}


def _opts(args: dict) -> tuple:
    layers = tuple(args.get("layers") or ("explicit", "similar"))
    if any(x not in ("explicit", "similar") for x in layers):
        raise ToolError("layers may only contain 'explicit' and 'similar'.")
    return (layers, float(args.get("min_score", FLOOR)), int(args.get("closest", CLOSEST)))


def _edge_view(e: list) -> dict:
    return {"edge": e[2], **({"score": e[3], "estimate": True} if e[2] == "similar" else {})}


def _share_hidden() -> bool:
    """Runs the user hid on the Lattice page are kept from agents unless Settings > MCP says to share them (undone runs are never shown)."""
    return bool(settings.get("mcp.share_hidden"))


def _lattice(ref: str) -> str:
    """A link that opens the Lattice page with this node chosen: give it to the user when you point at something."""
    return "#/lattice?focus=" + quote(ref, safe="")


class _Graph:
    """The base snapshot and the entity layer seen as ONE graph of string ids, so a path or a neighbour list can pass through an entity."""

    def __init__(self, s: dict):
        self.s, self.adj = s, _adj(s)
        self.pos = {n["id"]: i for i, n in enumerate(s["nodes"])}
        self.ix = kgraph.entities_index(include_hidden=_share_hidden())
        self.ents = self.ix["entities"]
        self.by_ent: dict = {}
        self.by_item: dict = {}
        for e in self.ix["edges"]:
            if e["type"] == "mentions":
                self.by_ent.setdefault(e["to"], []).append(e)
                self.by_item.setdefault(e["item"], []).append(e)
            else:
                self.by_ent.setdefault(e["to"], []).append(e)
                self.by_ent.setdefault(e["from"], []).append(e)

    def has(self, ref: str) -> bool:
        return ref in self.pos or ref in self.ents

    def need(self, ref: str) -> str:
        if not self.has(ref):
            raise ToolError(f"No node has the id {ref!r}. Find ids with graph_search or graph_overview.")
        return ref

    def view(self, ref: str) -> dict:
        if ref in self.pos:
            return _view(self.s, self.pos[ref], self.adj)
        e = self.ents[ref]
        return {"id": ref, "type": "entity", "kind": _kind_label(e["kind"]), "title": e["name"], "connections": len(self.by_ent.get(ref, ())), "open": ""}

    def links(self, ref: str, layers, floor: float, closest: int):
        """(other id, line) for every line that touches `ref` and is switched on."""
        if ref in self.pos:
            i = self.pos[ref]
            for ei in self.adj[i]:
                e = self.s["edges"][ei]
                if _on(e, layers, floor, closest):
                    yield self.s["nodes"][e[1] if e[0] == i else e[0]]["id"], _edge_view(e)
            if "explicit" in layers:
                for e in self.by_item.get(ref, ()):
                    yield e["to"], {"edge": "mentions", "quote": e["quote"]}
        elif "explicit" in layers:
            for e in self.by_ent.get(ref, ()):
                if e["type"] == "mentions":
                    if e["item"] in self.pos:
                        yield e["item"], {"edge": "mentioned_in", "quote": e["quote"]}
                else:
                    out = e["from"] == ref
                    yield (e["to"] if out else e["from"]), {"edge": "related", "label": e["label"], "direction": "out" if out else "in", "quote": e["quote"], "source": e["item"]}


@tool("graph_overview", "Describe the Lattice graph of the user's own material: how many Library prompts, Studio prompts, documents, collections, tags, projects, references (a link, file or ticket id named by 2 or more items) and Linkshell projects (only those connected to a prompt or reference) it holds, how many lines of each kind connect "
      "them, the most connected items (hubs), and how many items connect to nothing. Explicit lines (in a collection, tagged, in a project, derived from, followed by = the next prompt of the same session, same text, refers to = both name the same link, file or ticket id, names a document) are facts; similar lines are estimates of closeness in meaning. "
      "It also summarises the entity layer (people, technologies and concepts agents found, with their kinds and the most mentioned). Start here, then use graph_search, graph_neighbors and graph_entity.", title="Lattice overview")
def graph_overview(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    adj = _adj(s)
    hubs = sorted((i for i, n in enumerate(s["nodes"]) if n["t"] in ITEMS or n["t"] == "collection"), key=lambda i: -s["nodes"][i]["d"])[:10]
    shown = sum(1 for e in s["edges"] if e[2] != "similar" or (e[3] >= FLOOR and e[4] < CLOSEST))
    return {"status": _status(st, s), "nodes": s["counts"], "lines": s.get("edge_counts", {}), "lines_at_default_settings": shown,
            "default_settings": {"min_score": FLOOR, "closest": CLOSEST}, "unconnected_items": s.get("orphans", 0), "capped": s.get("capped", 0),
            "hubs": [_view(s, i, adj) for i in hubs], "entity_layer": _entity_counts(),
            "how_to_read": "Node ids work in graph_neighbors and graph_path; entity ids (en-…) also in graph_entity. List the items that connect to nothing with graph_search (unconnected: true). "
                           "To point the user at something, give them the link #/lattice?focus=<the id, URL-encoded>: it opens Lattice with that node chosen. " + READ_WITH}


def _entity_counts() -> dict:
    share = _share_hidden()
    ix = kgraph.entities_index(include_hidden=share)
    kinds: dict = {}
    seen: dict = {}
    for e in ix["entities"].values():
        k = _kind_label(e["kind"])
        kinds[k] = kinds.get(k, 0) + 1
    for e in ix["edges"]:
        if e["type"] == "mentions":
            seen.setdefault(e["to"], set()).add(e["item"])
    top = sorted(ix["entities"].values(), key=lambda e: -len(seen.get(e["id"], ())))[:8]
    batches = [b for b in kgraph.list_batches() if not b["undone"]]
    hidden = sum(1 for b in batches if b["hidden"])
    return {"entities": len(ix["entities"]), "links": len(ix["edges"]), "batches": len(batches), "by_kind": kinds,
            "most_mentioned": [{"id": e["id"], "name": e["name"], "kind": _kind_label(e["kind"]), "mentioned_in_count": len(seen.get(e["id"], ()))} for e in top if seen.get(e["id"])],
            "hidden_runs": hidden, "hidden_runs_shared": share,
            "note": "Entities and their links are made by agents (and a local model) with the user's agreement; every link carries a quote from the item it came from. "
                    + (f"{hidden} run(s) the user hid on the Lattice page are " + ("included (the user allows it in Settings > MCP)." if share else "left out (the user keeps them from agents; they can allow it in Settings > MCP).") if hidden else "")
                    + " Find entities with graph_search (types: entity) and read one with graph_entity."}


@tool("graph_search", "Find nodes of the Lattice graph by words in their title (all words must match, any case): Library prompts, Studio prompts, documents, collections, tags, projects, references and entities. "
      "Give a query, or unconnected: true to list the items (prompts, Studio prompts, documents) that connect to nothing in the base graph (good candidates to tag or file). "
      "Returns ids to use with graph_neighbors, graph_path and graph_entity.", {"query": {"type": "string", "minLength": 1, "maxLength": 200, "description": "Words to look for in titles. Optional with unconnected."},
                                                                   "types": {"type": "array", "maxItems": 8, "items": {"type": "string", "enum": list(SEARCH_TYPES)}, "description": "Only these kinds of node (entity = the agent-made layer)."},
                                                                   "unconnected": {"type": "boolean", "description": "Only items that have no line to anything else (collection, tag, project, same session, references, similar). Entities do not count as a connection here."},
                                                                   "limit": LIMIT}, title="Search the Lattice graph")
def graph_search(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    adj = _adj(s)
    words = (args.get("query") or "").lower().split()
    lone = bool(args.get("unconnected"))
    if not words and not lone:
        raise ToolError("The query is empty. Give words to look for, or unconnected: true.")
    types = set(args.get("types") or (ITEMS if lone else SEARCH_TYPES))
    if not types <= set(SEARCH_TYPES):
        raise ToolError("types may only contain: " + ", ".join(SEARCH_TYPES) + ".")
    if lone:
        types &= set(ITEMS)
    found = [i for i, n in enumerate(s["nodes"]) if n["t"] in types and (not lone or n["d"] == 0) and all(w in n["n"].lower() or w in n["id"].lower() for w in words)]
    found.sort(key=lambda i: -s["nodes"][i]["d"])
    rows = [_view(s, i, adj) for i in found]
    if "entity" in types and words and not lone:
        rows += _entity_hits(words)
    return {"status": _status(st, s), "total": len(rows), "returned": min(len(rows), limit_of(args)), "items": rows[:limit_of(args)]}


def _kind_label(slug: str) -> str:
    """What the user calls a kind (a deleted or unknown one is Other), so an agent never reads an `ek-…` slug."""
    k = kgraph.kinds.get(slug)
    return k["label"] if k and not k["deleted"] else (kgraph.kinds.get(kgraph.kinds.OTHER) or {}).get("label", "Other")


def _entity_hits(words: list) -> list:
    ix = kgraph.entities_index(include_hidden=_share_hidden())
    seen: dict = {}
    for e in ix["edges"]:
        if e["type"] == "mentions":
            seen.setdefault(e["to"], set()).add(e["item"])
    hits = [e for e in ix["entities"].values() if all(w in " ".join([e["name"]] + e["aliases"] + [e["id"]]).lower() for w in words)]
    hits.sort(key=lambda e: -len(seen.get(e["id"], ())))
    return [{"id": e["id"], "type": "entity", "kind": _kind_label(e["kind"]), "title": e["name"], "aliases": e["aliases"], "note": e["note"], "mentioned_in": sorted(seen.get(e["id"], ()))[:10],
             "mentioned_in_count": len(seen.get(e["id"], ()))} for e in hits]


@tool("graph_entity", "Read one entity of the Lattice graph (a person, technology or concept agents found in the user's material) with its evidence: its kind, aliases and note, every item that mentions it with the exact quote, "
      "and every link to another entity with its label, direction and quote. Use it to see what the user's Lattice already says about something before you add to it or answer about it. "
      "Give an entity id (en-…) from graph_search, or an exact name or alias. " + READ_WITH,
      {"id": {"type": "string", "minLength": 1, "maxLength": 200, "description": "An entity id (en-…), or the entity's exact name or one of its aliases."}, "limit": LIMIT}, required=("id",), title="Read an entity")
def graph_entity(args: dict, ctx: dict) -> dict:
    from .. import kgraph_api
    ix = kgraph.entities_index(include_hidden=_share_hidden(), item_exists=kgraph_api._stores().exists)
    ents, ref = ix["entities"], args["id"].strip()
    e = ents.get(ref)
    if e is None:
        low = ref.lower()
        cands = [x for x in ents.values() if low == x["name"].lower() or low in (a.lower() for a in x["aliases"])]
        if len(cands) > 1:
            raise ToolError("More than one entity answers to that name: " + "; ".join(f"{c['id']} ({c['name']}, {_kind_label(c['kind'])})" for c in cands[:8]) + ". Ask again with the id.")
        if not cands:
            raise ToolError(f"No entity has the id or name {ref!r}. Find entities with graph_search (types: entity).")
        e = cands[0]
    titles: dict = {}
    try:
        _, s = _snapshot()
        titles = {n["id"]: (n["t"], n["n"]) for n in s["nodes"] if n["t"] in ITEMS}
    except ToolError:
        pass   # the evidence is still readable without item titles
    n = limit_of(args)
    mentions, related = [], []
    for x in ix["edges"]:
        if x["type"] == "mentions" and x["to"] == e["id"]:
            t = titles.get(x["item"])
            mentions.append({"item": x["item"], **({"type": t[0], "title": t[1]} if t else {}), "quote": x["quote"], "source_gone": x["source_gone"], "added_by": x["by"] or x["via"]})
        elif x["type"] == "related" and e["id"] in (x["from"], x["to"]):
            out = x["from"] == e["id"]
            o = ents.get(x["to"] if out else x["from"])
            related.append({"direction": "out" if out else "in", "label": x["label"], "other": {"id": o["id"], "name": o["name"], "kind": _kind_label(o["kind"])} if o else None,
                            "item": x["item"], "quote": x["quote"], "source_gone": x["source_gone"], "added_by": x["by"] or x["via"]})
    return {"id": e["id"], "name": e["name"], "kind": _kind_label(e["kind"]), "aliases": e["aliases"], "note": e["note"], "runs": len(e["batches"]), "lattice": _lattice(e["id"]),
            "mentioned_in": len(mentions), "mentions": mentions[:n], "related_count": len(related), "related": related[:n],
            "how_to_read": "A quote is copied from its item's text. source_gone means the item was deleted since. A link between two entities points from the first to the second (direction out = this entity is the first)."}


@tool("graph_neighbors", "List what a node is connected to in the Lattice graph, with the kind of line: in_collection, tagged, in_project, derived_from, followed_by, same_text, refers_to, refers_doc, used_in (a prompt used in a Linkshell project) (facts), "
      "mentions (an item names an entity, with the quote), mentioned_in and related (entity lines, with their quotes) or similar (an estimate of closeness in meaning, with its score). Works for entities too (id en-…). "
      "depth 2 also lists what the neighbours connect to, with the neighbour it came through. Use it to find related prompts and documents before answering. " + READ_WITH,
      {"id": NODE, "depth": {"type": "integer", "minimum": 1, "maximum": 2, "description": "1 (default) or 2 steps."}, "layers": LAYERS, "min_score": SCORE, "closest": CLOSE, "limit": LIMIT},
      required=("id",), title="Neighbours of a node")
def graph_neighbors(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    g = _Graph(s)
    start = g.need(args["id"])
    layers, floor, closest = _opts(args)
    depth = int(args.get("depth", 1))
    seen, ring, out = {start}, [start], []
    for step in range(depth):
        nxt = []
        for a in ring:
            for b, line in g.links(a, layers, floor, closest):
                if b in seen or not g.has(b):
                    continue
                seen.add(b)
                out.append({**g.view(b), **line, "step": step + 1, **({"through": a} if step else {})})
                nxt.append(b)
        ring = nxt
    out.sort(key=lambda r: (r["step"], r["edge"] == "similar", -(r.get("score") or 0), -r["connections"]))
    return {"status": _status(st, s), "node": {**g.view(start), "lattice": _lattice(start)}, "settings": {"layers": list(layers), "min_score": floor, "closest": closest, "depth": depth},
            "total": len(out), "returned": min(len(out), limit_of(args)), "neighbours": out[:limit_of(args)]}


@tool("graph_path", "Find the shortest chain of connections between two nodes of the Lattice graph (at most 6 steps), to show how two items relate, for example a prompt and a document. "
      "It may pass through entities (an item and an entity it mentions). Each step says whether the line is a fact (explicit) or an estimate (similar).", {"from": NODE, "to": NODE, "layers": LAYERS, "min_score": SCORE, "closest": CLOSE},
      required=("from", "to"), title="Path between two nodes")
def graph_path(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    g = _Graph(s)
    a, b = g.need(args["from"]), g.need(args["to"])
    layers, floor, closest = _opts(args)
    prev: dict = {a: None}
    q = deque([(a, 0)])
    while q:
        x, d = q.popleft()
        if x == b:
            break
        if d >= 6:
            continue
        for y, line in g.links(x, layers, floor, closest):
            if y not in prev and g.has(y):
                prev[y] = (x, line)
                q.append((y, d + 1))
    settings_out = {"layers": list(layers), "min_score": floor, "closest": closest}
    if b not in prev:
        return {"status": _status(st, s), "found": False, "settings": settings_out,
                "message": "No connection within 6 steps with these settings. Lower min_score, raise closest, or follow both layers."}
    chain, x = [], b
    while prev[x] is not None:
        px, line = prev[x]
        chain.append({**g.view(x), **line, "from": px})
        x = px
    chain.reverse()
    return {"status": _status(st, s), "found": True, "steps": len(chain), "start": {**g.view(a), "lattice": _lattice(a)}, "path": chain, "settings": settings_out}


@tool("graph_refresh", "Rebuild the Lattice base layer from the user's files now (the Refresh button of the Lattice page). Use it when a Lattice answer says stale: true, or after the user added or changed items. "
      "It reads local files and the stored vectors, calls no model, writes only the Lattice's own cache and does not touch the entity layer. It runs in the background: call graph_overview a few seconds later.", title="Refresh the Lattice")
def graph_refresh(args: dict, ctx: dict) -> dict:
    from .. import kgraph_api
    a = kgraph_api.get().rebuild()
    st = a["status"]
    return {"state": st["state"], "stale": st["stale"], "built_at": iso(st["built_at"]), "message": "Building in the background. Call graph_overview in a few seconds; while it runs, answers still come from the previous build."}


@tool("graph_unprocessed", "List items (Library prompts, Studio prompts, documents) that no entity run has covered yet, newest first, so you can work through the user's material in pieces and "
      "add entities with graph_add. " + READ_WITH, {"limit": LIMIT, "types": {"type": "array", "maxItems": 3, "items": {"type": "string", "enum": list(ITEMS)}, "description": "Only these kinds of item."}},
      title="Items not yet covered by entities")
def graph_unprocessed(args: dict, ctx: dict) -> dict:
    st, s = _snapshot()
    adj = _adj(s)
    types = set(args.get("types") or ITEMS)
    if not types <= set(ITEMS):
        raise ToolError("types may only contain: " + ", ".join(ITEMS) + ".")
    done = kgraph.covered_items()
    todo = [i for i, n in enumerate(s["nodes"]) if n["t"] in types and n["id"] not in done]
    total = sum(1 for n in s["nodes"] if n["t"] in types)
    return {"status": _status(st, s), "items_total": total, "covered": total - len(todo), "not_covered": len(todo), "returned": min(len(todo), limit_of(args)),
            "items": [_view(s, i, adj) for i in todo[:limit_of(args)]],
            "how_to_continue": "Read an item's text, find the entities in it with a short exact quote each, agree with the user, then call graph_add. " + READ_WITH}


# ---------------------------------------------------------------- write tools (write tokens only, step 2)

ADDED = "The user reviews this in Knowledge > Lattice; Settings > MCP lists the run with an Undo."
ENTITY_SHAPE = {"type": "object", "required": ["name", "kind"], "properties": {
    "name": {"type": "string", "maxLength": 120}, "kind": {"type": "string", "maxLength": 60, "description": "One of the kinds listed in this tool's description (its name, case does not matter)."},
    "aliases": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 120}}, "note": {"type": "string", "maxLength": 200}}}
EDGE_SHAPE = {"type": "object", "required": ["type", "to", "item", "quote"], "properties": {
    "type": {"type": "string", "enum": ["mentions", "related"]},
    "from": {"type": "string", "description": "related: an entity name given in this call or an entity id (en-…). mentions: leave out (it is `item`)."},
    "to": {"type": "string", "description": "An entity name given in this call, or an existing entity id (en-…)."},
    "label": {"type": "string", "maxLength": 60, "description": "related only, required: what the relationship is, e.g. 'built on'."},
    "item": {"type": "string", "description": "The Library, Studio (ps-…) or document (kd-…) id the quote comes from."},
    "quote": {"type": "string", "maxLength": 200, "description": "Copied exactly from that item's text (8 to 200 characters). The server checks it occurs there."}}}


@tool("graph_start_run", AGREE.replace("save it", "add it to their Lattice") + "Open a run: graph_add calls that carry its id all belong to one batch, so the user can undo everything you added with ONE click. "
      "A run closes after an hour without a call. Use it when you will add in several calls; a single graph_add without a run makes its own batch.",
      {"note": {"type": "string", "maxLength": 200, "description": "What this run is for, shown to the user (for example 'People and tools in the Kitchen notes collection')."}},
      scope="write", title="Start a Lattice run")
def graph_start_run(args: dict, ctx: dict) -> dict:
    r = kgraph.start_run(ctx.get("name", ""), args.get("note", ""), "mcp")
    return {"run": r["id"], "closes_after_idle_minutes": kgraph.RUN_IDLE // 60,
            "message": "Pass this run id to graph_add. Nothing is visible to the user until your first graph_add stores something."}


@tool("graph_add", AGREE.replace("save it", "add it to their Lattice") + "Add entities (people, technologies, concepts ...) and the links between them to the user's Lattice graph. Every link needs the item it comes from and a quote copied exactly from that item "
      "(the server checks the quote occurs there and refuses the whole call otherwise, naming the first problem). Every NEW entity needs at least one `mentions` link in the same call. "
      "Entities are matched by name and kind, so repeating one adds an alias, never a duplicate. Limits per call: 200 entities, 400 links. You can only add: nothing is deleted or changed. " + READ_WITH,
      {"run": {"type": "string", "maxLength": 20, "description": "A run id from graph_start_run (optional)."},
       "note": {"type": "string", "maxLength": 200, "description": "Without a run: what this addition is, shown to the user."},
       "entities": {"type": "array", "maxItems": 200, "items": ENTITY_SHAPE, "description": "[{name, kind, aliases?, note?}]. kind: one of the kinds named in the tool description."},
       "edges": {"type": "array", "maxItems": 400, "items": EDGE_SHAPE, "description": "[{type: mentions|related, to, item, quote, from?, label?}]. mentions: the entity `to` appears in `item`. related: `from` and `to` are entities with a `label`."}},
      scope="write", title="Add entities and links to Lattice",
      live=lambda d: d + " Kinds you may use (the user can rename or add kinds, so use these names): " + kgraph.kinds.describe() + ".")
def graph_add(args: dict, ctx: dict) -> dict:
    try:
        r = kgraph.add_batch({"entities": args.get("entities", []), "edges": args.get("edges", [])}, by=ctx.get("name", ""), via="mcp", note=args.get("note", ""), run=args.get("run") or None, strict=True)
    except kgraph.Invalid as e:
        raise ToolError(str(e))
    out = {k: r[k] for k in ("created", "merged", "edges_added", "edges_duplicate")}
    if not r["stored"]:
        return {**out, "stored": False, "message": "Nothing new was stored: every link was already there."}
    b = kgraph.get_batch(r["batch"])
    n_ent, n_edge = sum(1 for e in b["entities"] if not e["merged"]), len(b["edges"])
    a = activity.touch(ctx, "graph_add", "lattice", r["batch"], f"{n_ent} {'entity' if n_ent == 1 else 'entities'}, {n_edge} {'link' if n_edge == 1 else 'links'}" +(f" ({b['note']})" if b["note"] else ""))
    return {**out, "stored": True, "batch": r["batch"], "run_totals": {"entities": n_ent, "links": n_edge}, "activity_id": a["id"], "message": ADDED}
