#!/usr/bin/env python3
"""Checks for the Lattice MCP read tools (backend/mcp/tools_graph.py). Plain asserts, no server: it seeds temp
folders and calls the tools through the protocol layer, as an agent would. Needs numpy, so run it with the project's Python:

    .venv/bin/python scripts/check_mcp_graph.py

Everything lives in a temp folder; your real prompts, collections, vectors and settings are never touched. No model and no service is contacted.
"""
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-mcp-graph-"))
os.environ.update(FLOWLYSTACK_PROMPTS_DIR=str(TMP / "prompts"), FLOWLYSTACK_SETTINGS_DIR=str(TMP / "settings"), FLOWLYSTACK_ALIAS_DIR=str(TMP / "alias"),
                  FLOWLYSTACK_MEILI_URL="http://127.0.0.1:1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import collections as co  # noqa: E402
from backend import kgraph_api, promptstore as ps  # noqa: E402
from backend.mcp import server  # noqa: E402

assert str(ps.PROMPTS_DIR).startswith(str(TMP)), "the prompts folder must be the temp one"


def step(msg):
    print("ok  ", msg)


def call(name, args=None, scope="read"):
    st, b = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}}, {}, {"scope": scope, "name": "t", "id": "t-1"})
    r = b["result"]
    text = r["content"][0]["text"]
    assert len(text) <= server.MAX_OUT
    if r["isError"]:
        return True, text
    out = json.loads(text)
    assert out["notice"] == server.NOTICE
    return False, out


def ok(name, args=None):
    err, out = call(name, args)
    assert not err, (name, args, out)
    return out


def fails(name, args, needle):
    err, out = call(name, args)
    assert err and needle.lower() in out.lower(), (name, args, out)


def tree():
    h = hashlib.sha1()
    for root in (TMP / "prompts",):
        for p in sorted(root.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


# ---------- seed: three topics, tags, a derived Studio prompt, two collections with documents ----------
STEMS = {"cooking": "recipe simmer garlic onion saucepan butter oven dough whisk season".split(), "travel": "flight airport luggage passport itinerary hotel museum train ticket beach".split(),
         "coding": "function python compile debug server database refactor commit endpoint array".split()}
TOPICS = {t: [w + e for w in ws for e in ("", "ish", "ery", "ful")] for t, ws in STEMS.items()}
rnd = random.Random(5)
T0 = time.time() - 30 * 86400
lib, ids = {}, {t: [] for t in TOPICS}
for n in range(8):
    for t in TOPICS:
        pid = ps.write_prompt(" ".join(rnd.choices(TOPICS[t], k=11)) + " please", T0 + len(lib) * 3600, f"s{n}", "", "hook", ps.PROMPTS_DIR, {"agent": "claude"})
        lib[pid] = t
        ids[t].append(pid)
for pid in ids["cooking"][:3]:
    ps.update_meta(pid, {"tags": ["kitchen"]}, ps.PROMPTS_DIR)
studio = ps.create_studio(" ".join(rnd.choices(TOPICS["cooking"], k=12)), "Dough plan", ["kitchen"], {"store": "library", "id": ids["cooking"][0]}, ps.STUDIO_DIR)
kit = co.create("Kitchen notes", "", [])
trips = co.create("Trips", "", [])
dsoup = co.add_document(kit["id"], "soup.md", ("# Soup\n\n" + " ".join(rnd.choices(TOPICS["cooking"], k=70))).encode())["document"]["id"]
drome = co.add_document(trips["id"], "rome.md", ("# Rome\n\n" + " ".join(rnd.choices(TOPICS["travel"], k=70))).encode())["document"]["id"]
before = tree()
cols_before = sorted(p.name for p in co._root(None).rglob("*") if p.is_file())

# ---------- the registry ----------
tools = {t["name"]: t for t in server.visible("read")}
assert {"graph_overview", "graph_search", "graph_neighbors", "graph_path"} <= set(tools) and all(tools[n]["scope"] == "read" and tools[n]["annotations"]["readOnlyHint"] for n in tools if n.startswith("graph_"))
assert {"graph_entity", "graph_refresh"} <= set(tools) and "graph_unprocessed" in tools and sum(t["scope"] == "read" for t in server.TOOLS.values()) == 27 and sum(t["scope"] == "write" for t in server.TOOLS.values()) == 5
step("seven read tools are registered for every token (27 read tools in all, 5 write)")

# ---------- no snapshot yet: it starts the page's own background build and says so ----------
err, text = call("graph_overview")
if err:
    assert "being built" in text, text
for _ in range(100):
    err, ov = call("graph_overview")
    if not err:
        break
    time.sleep(0.1)
assert not err, ov
step("the first call starts the same background build the page starts and says it is being built, then answers")

# ---------- overview ----------
assert ov["status"]["state"] == "ready" and ov["status"]["method"] == "tfidf-svd" and "words" in ov["status"]["note"] and ov["status"]["items"] == 27
assert ov["nodes"]["prompt"] == 24 and ov["nodes"]["studio"] == 1 and ov["nodes"]["document"] == 2 and ov["nodes"]["collection"] == 2 and ov["nodes"]["tag"] == 1
assert ov["lines"]["in_collection"] == 2 and ov["lines"]["derived_from"] == 1 and ov["lines"]["similar"] > 0 and ov["default_settings"] == {"min_score": 0.4, "closest": 5}
assert 0 < len(ov["hubs"]) <= 10 and all({"id", "type", "title", "connections", "open"} <= set(h) for h in ov["hubs"]) and ov["unconnected_items"] >= 0
assert ov["hubs"][0]["connections"] >= ov["hubs"][-1]["connections"] and "library_get" in ov["how_to_read"]
step("overview: counts by type, lines by kind, hubs by connections, the method in plain words, the defaults")

# ---------- search ----------
r = ok("graph_search", {"query": "kitchen"})
assert {x["type"] for x in r["items"]} == {"collection", "tag"} and r["total"] == 2
r = ok("graph_search", {"query": "SOUP .MD", "types": ["document"]})
assert r["total"] == 1 and r["items"][0]["id"] == dsoup and r["items"][0]["open"] == f"#/collections/{kit['id']}/documents/{dsoup}"
r = ok("graph_search", {"query": "Dough plan"})
assert r["items"][0]["id"] == studio["id"] and r["items"][0]["open"] == "#/studio/" + studio["id"]
assert ok("graph_search", {"query": "zzzzzz-nothing"})["total"] == 0 and len(ok("graph_search", {"query": "e", "limit": 3})["items"]) == 3
fails("graph_search", {"query": "   "}, "empty")
step("search: all words must match in any case, filters by type, gives ids and where to open each, limits, and an empty query is refused")

# ---------- neighbours ----------
n1 = ok("graph_neighbors", {"id": studio["id"]})
kinds = {(x["id"], x["edge"]) for x in n1["neighbours"]}
assert (ids["cooking"][0], "derived_from") in kinds and ("tag:kitchen", "tagged") in kinds
nf = ok("graph_neighbors", {"id": ids["cooking"][1], "layers": ["explicit"]})   # the 3 prompts of one session follow each other: a fact, so it is in the explicit layer
assert (ids["travel"][1], "followed_by") in {(x["id"], x["edge"]) for x in nf["neighbours"]} and all("estimate" not in x for x in nf["neighbours"])
assert not [x for x in ok("graph_neighbors", {"id": ids["cooking"][1], "layers": ["similar"]})["neighbours"] if x["edge"] == "followed_by"]
sim = [x for x in n1["neighbours"] if x["edge"] == "similar"]
assert sim and all(x["estimate"] is True and 0.4 <= x["score"] <= 1 and x["step"] == 1 for x in sim) and n1["settings"] == {"layers": ["explicit", "similar"], "min_score": 0.4, "closest": 5, "depth": 1}
assert all(lib.get(x["id"]) == "cooking" or x["type"] != "prompt" for x in sim)
only = ok("graph_neighbors", {"id": studio["id"], "layers": ["explicit"]})
assert only["neighbours"] and all(x["edge"] != "similar" for x in only["neighbours"])
assert not [x for x in ok("graph_neighbors", {"id": studio["id"], "min_score": 1.0})["neighbours"] if x["edge"] == "similar" and x["score"] < 1.0]
assert len([x for x in ok("graph_neighbors", {"id": studio["id"], "closest": 1})["neighbours"] if x["edge"] == "similar"]) <= len(sim)
d2 = ok("graph_neighbors", {"id": studio["id"], "depth": 2, "limit": 100})
assert d2["total"] > n1["total"] and {x["step"] for x in d2["neighbours"]} == {1, 2} and all("through" in x for x in d2["neighbours"] if x["step"] == 2)
assert all(x["through"] in {y["id"] for y in d2["neighbours"] if y["step"] == 1} for x in d2["neighbours"] if x["step"] == 2)
assert d2["neighbours"] == sorted(d2["neighbours"], key=lambda x: x["step"]) and len(ok("graph_neighbors", {"id": studio["id"], "depth": 2, "limit": 4})["neighbours"]) == 4
col = ok("graph_neighbors", {"id": kit["id"]})
assert {(x["id"], x["edge"]) for x in col["neighbours"]} == {(dsoup, "in_collection")}
fails("graph_neighbors", {"id": "no-such-node"}, "No node has the id")
fails("graph_neighbors", {"id": studio["id"], "depth": 3}, "depth")
fails("graph_neighbors", {"id": studio["id"], "layers": ["maybe"]}, "layers")
step("neighbours: explicit lines are facts, similar lines carry an estimate flag and score, settings and depth 2 (with `through`) work, bad input says why")

# ---------- path ----------
p1 = ok("graph_path", {"from": studio["id"], "to": ids["cooking"][0]})
assert p1["found"] and p1["steps"] == 1 and p1["path"][0]["edge"] == "derived_from" and p1["path"][0]["from"] == studio["id"]
p2 = ok("graph_path", {"from": dsoup, "to": studio["id"]})
assert p2["found"] and 1 <= p2["steps"] <= 6 and p2["path"][-1]["id"] == studio["id"] and all({"edge", "from"} <= set(s_) for s_ in p2["path"])
p3 = ok("graph_path", {"from": dsoup, "to": drome, "layers": ["explicit"]})
assert p3["found"] is False and "No connection" in p3["message"]
p4 = ok("graph_path", {"from": studio["id"], "to": studio["id"]})
assert p4["found"] and p4["steps"] == 0 and p4["path"] == []
fails("graph_path", {"from": studio["id"], "to": "nope"}, "No node has the id")
step("path: shortest chain with the kind of each line, not found with explicit lines only, same node is a zero-step path, unknown ids are refused")

# ---------- read-only ----------
assert tree() == before and sorted(p.name for p in co._root(None).rglob("*") if p.is_file()) == cols_before
assert (TMP / "settings" / "kgraph" / "base.json").is_file()
step("the tools wrote nothing but the graph's own cache: prompts, Studio and collections are byte-identical")

# ---------- unconnected items, the deep-link hint, graph_refresh ----------
lone = ok("graph_search", {"unconnected": True, "limit": 100})
assert lone["total"] == ov["unconnected_items"] and all(x["type"] in ("prompt", "studio", "document") and x["connections"] == 0 for x in lone["items"])
assert ok("graph_search", {"unconnected": True, "types": ["document"]})["total"] <= lone["total"]
fails("graph_search", {}, "query is empty")
assert "#/lattice?focus=" in ok("graph_overview")["how_to_read"]
nn = ok("graph_neighbors", {"id": "tag:kitchen"})
assert nn["node"]["lattice"] == "#/lattice?focus=tag%3Akitchen"
fails("graph_neighbors", {"id": "en-nope"}, "No node has the id")
rf = ok("graph_refresh")
assert rf["state"] in ("building", "ready") and "background" in rf["message"]
for _ in range(100):
    if ok("graph_overview")["status"]["state"] == "ready":
        break
    time.sleep(0.1)
step("graph_search lists unconnected items, a query is still required otherwise, node views carry a Lattice link, an unknown entity id is refused, graph_refresh rebuilds in the background")

print("\nall Lattice MCP tool checks passed")
