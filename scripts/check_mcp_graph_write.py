#!/usr/bin/env python3
"""Checks for the Lattice MCP entity tools (graph_start_run, graph_add, graph_unprocessed, the entity search and the activity Undo).
Plain asserts, no server: it seeds temp folders and calls the tools through the protocol layer as an agent would. Needs numpy:

    .venv/bin/python scripts/check_mcp_graph_write.py

Everything lives in a temp folder; your real prompts, collections, vectors and settings are never touched. No model and no service is contacted.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-mcp-graph-write-"))
os.environ.update(FLOWLYSTACK_PROMPTS_DIR=str(TMP / "prompts"), FLOWLYSTACK_SETTINGS_DIR=str(TMP / "settings"), FLOWLYSTACK_ALIAS_DIR=str(TMP / "alias"),
                  FLOWLYSTACK_MEILI_URL="http://127.0.0.1:1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import collections as co  # noqa: E402
from backend import kgraph, kgraph_kinds as kinds, promptstore as ps  # noqa: E402
from backend.mcp import activity, server  # noqa: E402

assert str(ps.PROMPTS_DIR).startswith(str(TMP)), "the prompts folder must be the temp one"
READ = {"scope": "read", "name": "Reader", "id": "t-1"}
WRITE = {"scope": "write", "name": "Cursor", "id": "t-2"}
OTHER = {"scope": "write", "name": "Other agent", "id": "t-3"}


def step(msg):
    print("ok  ", msg)


def call(name, args=None, ctx=WRITE):
    st, b = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}, {}, ctx)
    r = b["result"]
    text = r["content"][0]["text"]
    if r["isError"]:
        return True, text
    out = json.loads(text)
    assert out["notice"] == server.NOTICE
    return False, out


def ok(name, args=None, ctx=WRITE):
    err, out = call(name, args, ctx)
    assert not err, (name, args, out)
    return out


def fails(name, args, needle, ctx=WRITE):
    err, out = call(name, args, ctx)
    assert err and needle.lower() in out.lower(), (name, args, out)


def tree(*roots):
    h = hashlib.sha1()
    for root in roots:
        for p in sorted(Path(root).rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


def stores_tree():
    """Library, Studio and collections: everything under the prompts folder except the Lattice folder itself."""
    h = hashlib.sha1()
    for root in (ps.PROMPTS_DIR,):
        for p in sorted(root.rglob("*")):
            if p.is_file() and "kgraph" not in p.relative_to(root).parts:
                h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


def ments(*names, item, quote):
    return [{"type": "mentions", "to": n, "item": item, "quote": quote} for n in names]


# ---------- seed ----------
T = time.time()
p1 = ps.write_prompt("Our team runs FastAPI behind Caddy. Alice Chen reviews the Deployment plan every Friday.", T - 300, "s1", "", "hook", ps.PROMPTS_DIR, {"agent": "claude"})
p2 = ps.write_prompt("Write a summary of the quarterly incident review for the platform team please.", T - 200, "s2", "", "hook", ps.PROMPTS_DIR, {"agent": "claude"})
sd = ps.create_studio("Kubernetes is the target for the Deployment plan.\nSecond line about Docker images.", "K8s draft", [], None, ps.STUDIO_DIR)["id"]
kit = co.create("Ops notes", "", [])
doc = co.add_document(kit["id"], "ops.md", b"# Ops\n\nThe pager rotation is owned by Bob Marsh.\n\nIncident reviews use the five whys process.")["document"]["id"]
before_stores = stores_tree()

# ---------- the registry and scopes ----------
tools_w = {t["name"]: t for t in server.visible("write")}
new_w = {"graph_start_run", "graph_add"}
assert new_w <= set(tools_w) and new_w.isdisjoint(t["name"] for t in server.visible("read")) and "graph_unprocessed" in {t["name"] for t in server.visible("read")}
assert len(server.visible("read")) == 27 and len(server.visible("write")) == 32
for n in new_w:
    t = server.TOOLS[n]
    assert t["scope"] == "write" and t["annotations"] == {"readOnlyHint": False, "destructiveHint": False} and "agreed" in t["description"].lower() and "Lattice" in t["description"]
fails("graph_start_run", {}, "only read", READ)
fails("graph_add", {"entities": [], "edges": []}, "only read", READ)
assert not (ps.PROMPTS_DIR / "kgraph").exists(), "a refused call writes nothing"
step("graph_start_run and graph_add exist only for write tokens (annotated non-destructive, 'agreed' in the description); graph_unprocessed is a read tool; 27 read and 32 for a write token")

# ---------- wait for the base snapshot ----------
for _ in range(100):
    err, ov = call("graph_overview", ctx=READ)
    if not err:
        break
    time.sleep(0.1)
assert not err, ov
assert ov["entity_layer"]["entities"] == 0 and ov["entity_layer"]["batches"] == 0
step("overview reports the entity layer (empty at first)")

# ---------- graph_unprocessed ----------
u = ok("graph_unprocessed", {}, READ)
assert u["items_total"] == 4 and u["covered"] == 0 and u["not_covered"] == 4 and {i["id"] for i in u["items"]} == {p1, p2, sd, doc}
assert ok("graph_unprocessed", {"types": ["document"]}, READ)["items"][0]["id"] == doc and ok("graph_unprocessed", {"limit": 1}, READ)["returned"] == 1
fails("graph_unprocessed", {"types": ["entity"]}, "may only contain", READ)
step("graph_unprocessed lists every item nothing has covered yet, filtered by type and limit")

# ---------- graph_add: refusals first, nothing is written ----------
GOOD_E = [{"name": "FastAPI", "kind": "technology", "aliases": ["fast api"], "note": "web framework"}, {"name": "Caddy", "kind": "technology"}]
GOOD_X = ments("FastAPI", "Caddy", item=p1, quote="runs FastAPI behind Caddy") + [{"type": "related", "from": "FastAPI", "to": "Caddy", "label": "runs behind", "item": p1, "quote": "FastAPI behind Caddy"}]
fails("graph_add", {"entities": GOOD_E, "edges": ments("FastAPI", "Caddy", item=p1, quote="runs FastAPI behind nginx")}, "does not occur")
fails("graph_add", {"entities": GOOD_E, "edges": ments("FastAPI", item=p1, quote="runs FastAPI behind Caddy")}, "no verified `mentions`")
fails("graph_add", {"entities": [{"name": "X", "kind": "wizard"}], "edges": []}, "kind")
fails("graph_add", {"entities": GOOD_E, "edges": ments("FastAPI", "Caddy", item="nope-1", quote="runs FastAPI behind Caddy")}, "does not exist")
fails("graph_add", {"entities": [], "edges": []}, "nothing to add")
fails("graph_add", {"entities": [{"name": "n", "kind": "other"}] * 201, "edges": []}, "at most 200")
fails("graph_add", {"entities": [], "edges": [{}] * 401}, "at most 400")
fails("graph_add", {"entities": GOOD_E, "bogus": 1}, "unknown argument")
fails("graph_add", {"entities": "x"}, "must be a list")
fails("graph_add", {"run": "gb-ffffffffff", "entities": GOOD_E, "edges": GOOD_X}, "does not exist")
assert not (ps.PROMPTS_DIR / "kgraph").exists() and activity.list_items() == [], "refused calls write no batch and no activity line"
step("refusals name the problem (quote not there, no mention, bad kind, missing item, empty, limits, unknown argument, unknown run) and write nothing")

# ---------- one call = one batch, one activity line with an Undo ----------
a = ok("graph_add", {"entities": GOOD_E, "edges": GOOD_X, "note": "Tech stack"})
assert a["stored"] and a["created"] == 2 and a["merged"] == 0 and a["edges_added"] == 3 and a["batch"].startswith("gb-") and "Knowledge > Lattice" in a["message"]
assert a["run_totals"] == {"entities": 2, "links": 3}
acts = activity.list_items()
assert len(acts) == 1 and acts[0]["what"] == "Added to Lattice (entities and links)" and acts[0]["token"] == "Cursor" and acts[0]["open"] == "#/lattice" and acts[0]["title"].startswith("2 entities, 3 links")
b = kgraph.get_batch(a["batch"])
assert b["by"] == "Cursor" and b["via"] == "mcp" and not b["run"] and b["note"] == "Tech stack"
f = ok("graph_search", {"query": "fastapi", "types": ["entity"]}, READ)
assert f["total"] == 1 and f["items"][0]["type"] == "entity" and f["items"][0]["kind"] == "Technology" and f["items"][0]["aliases"] == ["fast api"] and f["items"][0]["mentioned_in"] == [p1]
assert "entity" in {i["type"] for i in ok("graph_search", {"query": "fast api"}, READ)["items"]}, "found by alias, and without a types filter"
ov = ok("graph_overview", {}, READ)
assert ov["entity_layer"]["entities"] == 2 and ov["entity_layer"]["links"] == 3 and ov["entity_layer"]["batches"] == 1
u = ok("graph_unprocessed", {}, READ)
assert u["covered"] == 1 and p1 not in {i["id"] for i in u["items"]}
dup = ok("graph_add", {"entities": [{"name": "fastapi", "kind": "technology"}], "edges": ments("fastapi", item=p1, quote="runs FastAPI behind Caddy")})
assert dup["stored"] is False and dup["edges_duplicate"] == 1 and dup["created"] == 0 and len(activity.list_items()) == 1, dup
step("one graph_add makes one batch tagged with the token's name and one line in Recent agent activity; entities are found by name or alias; the overview and graph_unprocessed follow")

# ---------- a run: several calls, one batch, one line, one Undo ----------
run = ok("graph_start_run", {"note": "Ops material"})["run"]
r1 = ok("graph_add", {"run": run, "entities": [{"name": "Kubernetes", "kind": "technology"}], "edges": ments("Kubernetes", item=sd, quote="Kubernetes is the target")})
r2 = ok("graph_add", {"run": run, "entities": [{"name": "Bob Marsh", "kind": "person"}, {"name": "Five whys", "kind": "process"}],
                      "edges": ments("Bob Marsh", item=doc, quote="owned by Bob Marsh") + ments("Five whys", item=doc, quote="Incident reviews use the five whys")})
assert r1["batch"] == r2["batch"] == run and r2["run_totals"] == {"entities": 3, "links": 3}
acts = activity.list_items()
assert len(acts) == 2 and acts[0]["title"].startswith("3 entities, 3 links") and "Ops material" in acts[0]["title"], acts
fails("graph_add", {"run": run, "entities": [{"name": "Z", "kind": "other"}], "edges": ments("Z", item=p1, quote="Alice Chen reviews")}, "belongs to someone else", OTHER)
step("a run is one batch and ONE activity line whose totals grow with each call; another token cannot add to it")

# ---------- Undo from Settings > MCP ----------
run_act = acts[0]["id"]
assert "Hidden everywhere in Lattice" in activity.undo(run_act)
assert kgraph.get_batch(run)["undone"] and ok("graph_search", {"query": "kubernetes", "types": ["entity"]}, READ)["total"] == 0
assert ok("graph_search", {"query": "fastapi", "types": ["entity"]}, READ)["total"] == 1, "the other batch is untouched"
assert ok("graph_unprocessed", {"types": ["studio"]}, READ)["not_covered"] == 1, "the undone run no longer covers its items"
try:
    activity.undo(run_act)
    raise AssertionError("second undo accepted")
except activity.UndoError as e:
    assert e.status == 409
fails("graph_add", {"run": run, "entities": [{"name": "Z", "kind": "other"}], "edges": ments("Z", item=p1, quote="Alice Chen reviews")}, "undone")
kgraph.delete_batch(a["batch"])
acts = activity.list_items(5)
first = [x for x in acts if x["title"].startswith("2 entities")][0]
assert "already gone" in activity.undo(first["id"])
removed = activity.delete(first["id"])
assert activity.restore(removed) == 1, "a deleted Lattice line comes back through the toast Undo"
step("Undo hides the whole run (nothing deleted), only that run; a second Undo is a 409; a deleted batch is reported; the activity list's Delete and restore accept the new line")

# ---------- the stores are untouched ----------
assert stores_tree() == before_stores
assert sorted(p.name for p in (ps.PROMPTS_DIR / "kgraph").iterdir()) == ["batches"]
step("Library, Studio and collections are byte-identical after all of it; the entity layer lives only in its own folder")

# ---------- the user's kinds: listed live in the description, label or slug accepted, search shows the label ----------
def add_desc():
    st, b = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {}, WRITE)
    return [t for t in b["result"]["tools"] if t["name"] == "graph_add"][0]
d0 = add_desc()["description"]
assert "Technology: a tool, language, library or service" in d0 and "Other" in d0 and "enum" not in add_desc()["inputSchema"]["properties"]["entities"]["items"]["properties"]["kind"]
kinds.update("technology", {"label": "Tool", "hint": "a command-line tool"})
rec = kinds.add("Recipe", "a dish", "#ff0000", "#00ff00")
d1 = add_desc()["description"]
assert "Tool (technology): a command-line tool" in d1 and "Recipe: a dish" in d1 and "Technology:" not in d1, "the description follows the user's kinds"
r = ok("graph_add", {"entities": [{"name": "Caddy", "kind": "tool"}, {"name": "Soup", "kind": "RECIPE"}, {"name": "Alice Chen", "kind": "person"}],
                     "edges": ments("Caddy", item=p1, quote="behind Caddy") + ments("Soup", item=p1, quote="Alice Chen reviews") + ments("Alice Chen", item=p1, quote="Alice Chen reviews")})
assert r["created"] == 3 and r["edges_added"] == 3
ents = {e["name"]: e for e in kgraph.entities_index(include_hidden=True)["entities"].values()}
assert ents["Soup"]["kind"] == rec["slug"] and ents["Caddy"]["kind"] == "technology"
assert ok("graph_search", {"query": "soup", "types": ["entity"]}, READ)["items"][0]["kind"] == "Recipe", "an agent reads the label, never an ek- slug"
kinds.delete(rec["slug"])
fails("graph_add", {"entities": [{"name": "Pie", "kind": "Recipe"}], "edges": ments("Pie", item=p1, quote="Alice Chen reviews")}, "kind must be one of")
assert ok("graph_search", {"query": "soup", "types": ["entity"]}, READ)["items"][0]["kind"] == "Other", "a deleted kind reads as Other"
kinds.reset()
step("kinds: the tool description follows the user's kinds, label or slug is accepted (any case), a deleted kind is refused, search shows labels")

# ---------- graph_entity, entities inside neighbours and paths, overview, the hidden-runs switch ----------
from backend import settings  # noqa: E402
rg = ok("graph_add", {"entities": [{"name": "Dana Roe", "kind": "person", "aliases": ["D. Roe"]}, {"name": "Pager", "kind": "other"}],
                      "edges": ments("Dana Roe", item=p2, quote="quarterly incident review") + ments("Pager", item=doc, quote="The pager rotation")
                      + [{"type": "related", "from": "Dana Roe", "to": "Pager", "label": "owns", "item": doc, "quote": "pager rotation is owned by Bob Marsh"}]})
ge = ok("graph_entity", {"id": "dana roe"}, READ)
assert ge["name"] == "Dana Roe" and ge["kind"] == "Person" and ge["aliases"] == ["D. Roe"] and ge["mentioned_in"] == 1 and ge["mentions"][0]["item"] == p2 and ge["mentions"][0]["quote"] == "quarterly incident review"
assert ge["related"][0]["direction"] == "out" and ge["related"][0]["label"] == "owns" and ge["related"][0]["other"]["name"] == "Pager" and ge["lattice"].startswith("#/lattice?focus=en-")
assert ok("graph_entity", {"id": ge["id"]}, READ)["id"] == ge["id"] and ok("graph_entity", {"id": "D. Roe"}, READ)["id"] == ge["id"]
fails("graph_entity", {"id": "Nobody"}, "No entity", READ)
en = ok("graph_neighbors", {"id": ge["id"]}, READ)
assert {(x["id"], x["edge"]) for x in en["neighbours"]} >= {(p2, "mentioned_in")} and any(x["edge"] == "related" and x["title"] == "Pager" for x in en["neighbours"])
inn = ok("graph_neighbors", {"id": p2}, READ)
assert any(x["id"] == ge["id"] and x["edge"] == "mentions" and x["type"] == "entity" and x["quote"] for x in inn["neighbours"])
assert ok("graph_neighbors", {"id": ge["id"], "layers": ["similar"]}, READ)["total"] == 0, "entity lines are explicit facts"
pa = ok("graph_path", {"from": ge["id"], "to": doc}, READ)
assert pa["found"] and pa["path"][-1]["id"] == doc and pa["steps"] == 2 and pa["path"][0]["title"] == "Pager"
ovl = ok("graph_overview", {}, READ)["entity_layer"]
assert ovl["by_kind"].get("Person", 0) >= 1 and ovl["most_mentioned"] and ovl["hidden_runs"] == 0
kgraph.hide_batch(rg["batch"])
assert ok("graph_search", {"query": "dana", "types": ["entity"]}, READ)["total"] == 0, "a hidden run is kept from agents by default"
fails("graph_entity", {"id": ge["id"]}, "No entity", READ)
fails("graph_neighbors", {"id": ge["id"]}, "No node has the id", READ)
o2 = ok("graph_overview", {}, READ)["entity_layer"]
assert o2["hidden_runs"] == 1 and o2["hidden_runs_shared"] is False and "left out" in o2["note"]
settings.update("mcp", {"share_hidden": True})
assert ok("graph_search", {"query": "dana", "types": ["entity"]}, READ)["total"] == 1 and ok("graph_entity", {"id": ge["id"]}, READ)["name"] == "Dana Roe"
assert ok("graph_overview", {}, READ)["entity_layer"]["hidden_runs_shared"] is True
kgraph.undo_batch(rg["batch"])
assert ok("graph_search", {"query": "dana", "types": ["entity"]}, READ)["total"] == 0, "an undone run is never shown, even with the switch on"
settings.update("mcp", {"share_hidden": False})
step("graph_entity reads an entity by id, name or alias with quotes and links; neighbours and paths pass through entities; a hidden run is kept from agents until Settings > MCP shares it; an undone run never shows")

print("\nall Lattice MCP entity-tool checks passed")
