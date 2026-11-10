#!/usr/bin/env python3
"""Checks for Linkshell projects in Lattice's base layer (backend/kgraph_build.py: `gather_linkshell`, the `linkshell` node and the `used_in` and
`refers_to` lines). Plain asserts, no server. Needs numpy, so run it with the project's interpreter:

    .venv/bin/python scripts/check_kgraph_linkshell.py

Everything runs on synthetic prompts and Linkshell projects in a temp directory; your real prompts and Linkshell projects are never read or touched
(the library folder passed in decides where Linkshell is read from).
"""
import copy
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-kgraph-ls-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "prompts")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
os.environ["FLOWLYSTACK_ALIAS_DIR"] = str(TMP / "alias")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import kgraph_build as kb  # noqa: E402
from backend import linkshell as ls  # noqa: E402
from backend import promptstore as ps  # noqa: E402

LIB, STUDIO, LSR = TMP / "prompts", TMP / "prompts" / "studio", TMP / "prompts" / "linkshell"
assert str(ps.PROMPTS_DIR).startswith(str(TMP)), "the prompts folder must be the temp one"


def step(msg: str) -> None:
    print("ok  ", msg)


def tree(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")) if root.exists() else []:
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


T0 = time.time() - 10 * 86400


def lib(text: str, n: int) -> str:
    return ps.write_prompt(text, T0 + n * 3600, f"s{n}", "", "hook", LIB, {"agent": "claude"})


def block(bid, typ, **kw):
    return {"id": bid, "type": typ, "title": bid, "x": 0, "y": 0, "w": 190, "h": 88, "frame": "", "agent": "claude", "status": "todo", **kw}


def project(name: str, blocks: list, texts: dict | None = None) -> str:
    pid = ls.create(name, LSR)["project"]["id"]
    g = copy.deepcopy(ls.get(pid, LSR)["graph"])
    g["blocks"] += [block(bid, typ, **extra) for bid, typ, extra in blocks]
    ls.save_graph(pid, g, g["rev"], LSR)
    for bid, text in (texts or {}).items():
        ls.save_text(pid, bid, text, root=LSR)
    return pid


# ---------------------------------------------------------------- fixtures
A_TEXT = "Write a README with install steps and a short usage example"
a = lib(A_TEXT, 1)
b = lib("See https://example.com/docs/guide for the setup guide and the notes", 2)
c = lib("yes", 3)
lib("A completely different prompt about travel itinerary planning", 4)
lib("Another unrelated prompt about cooking pasta with garlic and butter", 5)
s1 = ps.create_studio("Draft a release note for the new version of the app", "Release note", None, None, STUDIO)["id"]

p1 = project("Readme", [("readme", "prompt", {})], {"readme": "  WRITE a README  with install steps\nand a short usage example "})   # identical text, case and spacing ignored
p2 = project("Release", [("rel", "prompt", {"derived_from": {"store": "studio", "id": s1}})], {"rel": "something else entirely, written by hand here"})   # loaded From Studio
p3 = project("Docs", [("doc", "reference", {"urls": ["https://example.com/docs/guide"]})])   # a link another item names
p4 = project("Alone", [("x", "prompt", {})], {"x": "nothing in common with any other prompt or reference at all"})   # no connection: no node
p5 = project("Short", [("y", "prompt", {})], {"y": "yes"})   # the text equals a prompt but is too short to count
p6 = project("Launch", [("lb", "prompt", {})], {"lb": "a block this project has, unrelated to the saved prompt"})
s2 = ps.create_studio("Plan the launch checklist for the beta release", "Launch", None, {"store": "linkshell", "id": p6, "block": "lb"}, STUDIO)["id"]   # saved from a block

# ---------------------------------------------------------------- reading
assert kb.ALGO == 4
assert kb.gather_linkshell(None) == [] and kb.gather_linkshell(TMP / "nowhere") == []
lsp = kb.gather_linkshell(LIB)
assert {p["id"] for p in lsp} == {p1, p2, p3, p4, p5, p6}
byid = {p["id"]: p for p in lsp}
assert byid[p1]["texts"] == [" ".join(A_TEXT.casefold().split())] and byid[p2]["studio"] == [s1] and "example.com/docs/guide" in byid[p3]["urls"]
assert byid[p5]["texts"] == [], "a text shorter than SAME_MIN is never kept for comparing"
step("gather_linkshell reads projects from <library>/linkshell only: normalised Prompt and Spec texts of enough length, Studio sources, Reference links")

# ---------------------------------------------------------------- the graph
before = tree(LSR)
items, cols = kb.gather(LIB, STUDIO, None)
snap = kb.build(items, cols, linkshell=lsp)
assert tree(LSR) == before, "building never writes to Linkshell"
nodes = {n["id"]: n for n in snap["nodes"]}
ls_nodes = {i for i, n in nodes.items() if n["t"] == "linkshell"}
assert ls_nodes == {"linkshell:" + x for x in (p1, p2, p3, p6)}, ls_nodes
assert snap["counts"]["linkshell"] == 4 and all(nodes[i]["n"] for i in ls_nodes)
assert {nodes[i]["n"] for i in ls_nodes} == {"Readme", "Release", "Docs", "Launch"}
assert "linkshell:" + p4 not in nodes and "linkshell:" + p5 not in nodes, "a project with no real connection is not a node"
assert {n["t"] for n in snap["nodes"]} <= {"prompt", "studio", "document", "collection", "tag", "project", "reference", "linkshell"}, "blocks are never nodes"


def lines(kind: str) -> set:
    return {(snap["nodes"][e[0]]["id"], snap["nodes"][e[1]]["id"]) for e in snap["edges"] if e[2] == kind}


assert lines("used_in") == {(a, "linkshell:" + p1), (s1, "linkshell:" + p2), (s2, "linkshell:" + p6)}, lines("used_in")
refs = lines("refers_to")
ref = next(y for x, y in refs if x == b)
assert ref.startswith("ref:") and ("linkshell:" + p3, ref) in refs, refs
assert snap["edge_counts"]["used_in"] == 3 and snap["n_items"] == len(items) and snap["orphans"] == sum(1 for n in snap["nodes"] if n["t"] in ("prompt", "studio", "document") and n["d"] == 0)
assert all(e[3] == 1 for e in snap["edges"] if e[2] in ("used_in",)), "these are facts, not estimates"
text = json.dumps(snap)
assert "something else entirely" not in text and "unrelated to the saved prompt" not in text and "nothing in common" not in text, "the snapshot holds ids and titles, never block text"
assert kb.build(items, cols)["counts"].get("linkshell") is None, "without Linkshell input nothing changes"
step("a project is a node only with a real connection (identical text, loaded From Studio, saved to Studio from a block, a shared link); blocks and short texts never are; nothing is written to Linkshell; no text in the snapshot")

# ---------------------------------------------------------------- the running snapshot
kg = kb.KGraph(TMP / "data", LIB, STUDIO, None, model=lambda: "", ignore=lambda: "", vector_lookup=None)
sig0 = kg.signature()
s = kg.build_now()
assert s["counts"]["linkshell"] == 4 and (TMP / "data" / "kgraph" / "base.json").is_file() and kg.signature() == sig0
ls.save_text(p4, "x", "now this block holds the same text as the first library prompt: " + A_TEXT.lower(), root=LSR)
assert kg.signature() != sig0, "a change inside a Linkshell block is noticed"
sig1 = kg.signature()
ls.update(p1, {"name": "Readme renamed"}, LSR)
assert kg.signature() != sig1, "so is a renamed project"
step("the running snapshot includes Linkshell and a change in a block or a project name triggers a rebuild")

print("all Linkshell-in-Lattice checks passed")
