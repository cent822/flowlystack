#!/usr/bin/env python3
"""Checks for Lattice's base layer, backend/kgraph_build.py. Plain asserts, no server. Needs numpy, so run it
with the project's interpreter:

    .venv/bin/python scripts/check_kgraph.py

Everything runs on synthetic prompts, documents and vectors in a temp directory; your real prompts, collections, vectors and settings are never touched.
"""
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-kgraph-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend import collections as co  # noqa: E402
from backend import kgraph_build as kb  # noqa: E402
from backend import promptstore as ps  # noqa: E402
from backend.rag import vectors  # noqa: E402

LIB, STUDIO, COL = TMP / "prompts", TMP / "prompts" / "studio", TMP / "collections"


def step(msg: str) -> None:
    print("ok  ", msg)


T0 = time.time() - 30 * 86400
_STEMS = {
    "cooking": "recipe simmer garlic onion saucepan butter oven dough whisk season".split(),
    "travel": "flight airport luggage passport itinerary hotel museum train ticket beach".split(),
    "coding": "function python compile debug server database refactor commit endpoint array".split(),
}
TOPICS = {t: [w + e for w in ws for e in ("", "ish", "ery", "ful")] for t, ws in _STEMS.items()}
rnd = random.Random(7)


def text_of(topic: str) -> str:
    return " ".join(rnd.choices(TOPICS[topic], k=rnd.randint(9, 12))) + " please make it"


def tree(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")) if root.exists() else []:
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------- empty
s = kb.build([], [])
assert s["n_items"] == 0 and s["nodes"] == [] and s["edges"] == [] and s["method"] == "none"
items, cols = kb.gather(LIB, STUDIO, COL)   # folders that do not exist yet
assert items == [] and cols == []
step("nothing at all, and folders that do not exist yet, give an empty snapshot without a crash")

# ---------------------------------------------------------------- a small world on disk
truth = {}
lib_ids = {t: [] for t in TOPICS}
for n in range(8):
    for t in TOPICS:
        pid = ps.write_prompt(text_of(t), T0 + len(truth) * 3600, f"s{n}", "", "hook", LIB, {"agent": "claude"})
        truth[pid] = t
        lib_ids[t].append(pid)
for pid in lib_ids["cooking"][:3]:
    ps.update_meta(pid, {"tags": ["kitchen", "weekly"]}, LIB)
ps.update_meta(lib_ids["travel"][0], {"tags": ["lonely-tag"]}, LIB)   # used once: never a node
ps.update_meta(lib_ids["coding"][0], {"tags": ["weekly"]}, LIB)
sd1 = ps.create_studio(text_of("cooking"), "Dough plan", ["kitchen"], {"store": "library", "id": lib_ids["cooking"][0]}, STUDIO)
sd2 = ps.create_studio(text_of("coding"), "Orphan draft", [], {"store": "library", "id": "gone-forever"}, STUDIO)
truth[sd1["id"]], truth[sd2["id"]] = "cooking", "coding"
c1 = co.create("Kitchen notes", "", ["kitchen"], COL)
c2 = co.create("Trips", "", [], COL)
docs = {}
for name, topic, cid in (("soup.md", "cooking", c1["id"]), ("pasta.md", "cooking", c1["id"]), ("rome.md", "travel", c2["id"])):
    r = co.add_document(cid, name, ("# " + name + "\n\n" + text_of(topic) + "\n\n" + text_of(topic)).encode(), COL)
    docs[name] = r["document"]["id"]
    truth[docs[name]] = topic
co.add_to(c2["id"], docs["pasta.md"], COL)   # one document in two collections
bad = co.add_document(c1["id"], "broken.pdf", b"not a pdf", COL)["document"]["id"]   # failed, no text
before = (tree(LIB), tree(COL))

items, cols = kb.gather(LIB, STUDIO, COL)
assert {i["type"] for i in items} == {"prompt", "studio", "document"} and len(cols) == 2
assert sum(i["type"] == "prompt" for i in items) == 24 and sum(i["type"] == "studio" for i in items) == 2 and sum(i["type"] == "document" for i in items) == 4
assert all(i["vt"] for i in items if i["type"] != "document" or i["id"] != bad) and next(i for i in items if i["id"] == bad)["vt"] == []
step("gather reads Library, Studio, documents and collections (a failed document is still an item, with no text)")

s = kb.build(items, cols)
nodes = {n["id"]: n for n in s["nodes"]}
at = {n["id"]: k for k, n in enumerate(s["nodes"])}
assert s["n_items"] == 30 and s["counts"]["prompt"] == 24 and s["counts"]["studio"] == 2 and s["counts"]["document"] == 4 and s["counts"]["collection"] == 2
assert {"tag:kitchen", "tag:weekly"} <= set(nodes) and "tag:lonely-tag" not in nodes and s["counts"]["tag"] == 2
assert all(set(n) == {"id", "t", "n", "d"} for n in s["nodes"]) and "text" not in json.dumps(s["edges"])
kinds = s["edge_counts"]
assert kinds["in_collection"] == 5, kinds   # soup, pasta, broken in c1; rome, pasta in c2
assert [e for e in s["edges"] if e[2] == "derived_from"] == [[at[sd1["id"]], at[lib_ids["cooking"][0]], "derived_from", 1, 0]]   # the dead link makes no edge
tagged = {(s["nodes"][e[0]]["id"], s["nodes"][e[1]]["id"]) for e in s["edges"] if e[2] == "tagged"}
assert (lib_ids["cooking"][0], "tag:kitchen") in tagged and (sd1["id"], "tag:kitchen") in tagged and (c1["id"], "tag:kitchen") in tagged
assert (lib_ids["coding"][0], "tag:weekly") in tagged and (lib_ids["cooking"][1], "tag:weekly") in tagged
step("explicit edges: collections, tags used twice or more (a lonely tag is no node), derived-from only to a prompt that exists; the snapshot holds no text")

assert s["method"] == "tfidf-svd" and kinds["similar"] > 0
sim = [e for e in s["edges"] if e[2] == "similar"]
assert all(e[0] < e[1] for e in sim) and len({(e[0], e[1]) for e in sim}) == len(sim) and all(kb.MIN_SCORE <= e[3] <= 1 and 0 <= e[4] < kb.TOPK for e in sim)
same = sum(truth[s["nodes"][e[0]]["id"]] == truth[s["nodes"][e[1]]["id"]] for e in sim if s["nodes"][e[0]]["id"] in truth and s["nodes"][e[1]]["id"] in truth)
tot = sum(1 for e in sim if s["nodes"][e[0]]["id"] in truth and s["nodes"][e[1]]["id"] in truth)
assert tot and same / tot >= 0.9, (same, tot)
assert all(s["nodes"][e[0]]["t"] != "collection" and s["nodes"][e[1]]["t"] != "tag" for e in sim) and nodes[bad]["d"] == 1   # only the collection edge: no text, no similarity
assert s["orphans"] == 0 and set(s["scores"]) == {"p10", "p50", "p90", "p99"}
step(f"similar edges: each pair once, scores and ranks in range, no edge for an item without text, {same} of {tot} join items of the same topic (words only)")

# ---------------------------------------------------------------- stored vectors, and the 80% rule
topic_dir = {t: np.eye(3)[k] for k, t in enumerate(TOPICS)}
by_hash = {}
for i in items:
    if truth.get(i["id"]):
        for tx in i["vt"]:
            by_hash[vectors.text_hash(tx)] = (topic_dir[truth[i["id"]]] + np.random.default_rng(len(by_hash)).normal(0, 0.15, 3)).astype(np.float32)


def lookup(model, hashes):
    return {h: by_hash[h] for h in hashes if h in by_hash}


V = kb.stored_vectors([i for i in items if i["text"].strip()], "m", lookup)
assert V is not None and V.shape == (len([i for i in items if i["text"].strip()]), 3)
assert kb.stored_vectors(items, "", lookup) is None and kb.stored_vectors([], "m", lookup) is None
s2 = kb.build(items, cols, vecs_for=lambda it: kb.stored_vectors(it, "m", lookup))
assert s2["method"] == "embeddings"
sim2 = [e for e in s2["edges"] if e[2] == "similar"]
same2 = sum(truth[s2["nodes"][e[0]]["id"]] == truth[s2["nodes"][e[1]]["id"]] for e in sim2)
assert sim2 and same2 / len(sim2) >= 0.9, (same2, len(sim2))
half = {h: v for k, (h, v) in enumerate(by_hash.items()) if k % 2}   # about half of the texts have a vector: under 80%
assert kb.stored_vectors([i for i in items if i["text"].strip()], "m", lambda m, hs: {h: half[h] for h in hs if h in half}) is None
s3 = kb.build(items, cols, vecs_for=lambda it: kb.stored_vectors(it, "m", lambda m, hs: {h: half[h] for h in hs if h in half}))
assert s3["method"] == "tfidf-svd"
step("stored vectors give method embeddings and group by topic; under 80% covered the words are used for all items, never a mix")

# ---------------------------------------------------------------- limits
s4 = kb.build(items, cols, cap=10)
assert s4["n_items"] == 10 and s4["capped"] == 20 and s4["counts"]["prompt"] + s4["counts"]["studio"] + s4["counts"]["document"] == 10
assert all(0 <= e[0] < len(s4["nodes"]) and 0 <= e[1] < len(s4["nodes"]) for e in s4["edges"])
s5 = kb.build(items, cols, topk=2)
per = {}
for e in s5["edges"]:
    if e[2] == "similar":
        per[e[0]] = per.get(e[0], 0) + 1
        per[e[1]] = per.get(e[1], 0) + 1
assert all(e[4] < 2 for e in s5["edges"] if e[2] == "similar")
one = kb.build([items[0]], [])
assert one["n_items"] == 1 and one["edges"] == [] and one["method"] == "none"
step("the cap keeps the newest items and says how many were left out; K limits the stored ranks; one item makes no similarity")

# ---------------------------------------------------------------- the running snapshot
mdl = {"v": ""}
kg = kb.KGraph(TMP / "data", LIB, STUDIO, COL, model=lambda: mdl["v"], ignore=lambda: "", vector_lookup=lookup, vector_count=lambda m: len(by_hash) if m else 0)
sig0 = kg.signature()
snap = kg.build_now()
assert snap["n_items"] == 30 and (TMP / "data" / "kgraph" / "base.json").is_file() and kg.signature() == sig0
kg2 = kb.KGraph(TMP / "data", LIB, STUDIO, COL, model=lambda: "", ignore=lambda: "", vector_lookup=None)
a = kg2._answer()
assert a["snapshot"]["n_items"] == 30 and a["status"]["state"] == "ready" and a["status"]["method"] == "tfidf-svd"
ps.write_prompt(text_of("travel"), time.time(), "new", "", "hook", LIB, {"agent": "claude"})
assert kg.signature() != sig0
co.add_to(c2["id"], docs["soup.md"], COL)
assert kg.signature() != sig0
mdl["v"] = "m"
sigm = kg.signature()
assert sigm != sig0
kg3 = kb.KGraph(TMP / "data2", LIB, STUDIO, COL, model=lambda: "m", ignore=lambda: "", vector_lookup=lookup, vector_count=lambda m: len(by_hash), recheck=0.0)
first = kg3.get()
assert first["status"]["state"] == "building" and first["snapshot"] is None
for _ in range(100):
    time.sleep(0.1)
    ans = kg3.get()
    if ans["status"]["state"] == "ready":
        break
assert ans["status"]["state"] == "ready" and ans["snapshot"]["n_items"] == 31 and ans["snapshot"]["method"] in ("embeddings", "tfidf-svd")
broken = kb.KGraph(TMP / "data3", LIB, STUDIO, COL, model=lambda: "", ignore=lambda: "", vector_lookup=None, recheck=0.0)
broken._gather = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
b = broken.get()
time.sleep(0.2)
b = broken.get()
assert b["status"]["state"] == "error" and "boom" in b["status"]["error"] and b["snapshot"] is None
step("the running snapshot is saved and reloaded, its signature changes with prompts, membership and model, it builds in the background, and an error is shown, not raised")

after = (tree(LIB), tree(COL))
assert after[0] != before[0] and after[1] != before[1]   # the check itself added a prompt and a membership above
step("a build writes only under its own data folder (checked next)")
before2 = (tree(LIB), tree(COL))
kb.build(*kb.gather(LIB, STUDIO, COL))
kg.build_now()
assert (tree(LIB), tree(COL)) == before2
step("gathering and building leave the prompts and collections folders byte-identical")


# ---------------------------------------------------------------- facts from the capture: project, session order, identical text
L2 = TMP / "facts" / "prompts"
Tm = time.time() - 3 * 86400
a1 = ps.write_prompt("first prompt of the alpha session about the billing report", Tm, "sess-a", "/work/alpha", "hook", L2, {"agent": "claude"})
a2 = ps.write_prompt("second prompt of the alpha session about the billing report", Tm + 60, "sess-a", "/work/alpha", "hook", L2, {"agent": "claude"})
a3 = ps.write_prompt("third prompt of the alpha session about the billing report", Tm + 120, "sess-a", "/work/alpha", "hook", L2, {"agent": "claude"})
b1 = ps.write_prompt("one prompt of the beta project in its own session here", Tm + 30, "sess-b", "/work/beta", "hook", L2, {"agent": "claude"})
b2 = ps.write_prompt("another prompt of the beta project in another session", Tm + 90, "sess-c", "/work/alpha", "hook", L2, {"agent": "claude"})   # alpha again, other session
d1 = ps.write_prompt("Please summarise the weekly report in three bullet points.", Tm + 200, "sess-d", "", "hook", L2, {"agent": "claude"})
d2 = ps.write_prompt("please   SUMMARISE the weekly report in three bullet points.", Tm + 300, "sess-e", "", "hook", L2, {"agent": "claude"})   # same text: case and spaces ignored
d3 = ps.write_prompt("Please summarise the weekly report in three bullet points.", Tm + 400, "", "", "hook", L2, {"agent": "claude"})   # no session
sh1 = ps.write_prompt("yes continue", Tm + 500, "sess-f", "", "hook", L2, {"agent": "claude"})
sh2 = ps.write_prompt("yes continue", Tm + 600, "sess-g", "", "hook", L2, {"agent": "claude"})   # too short to count as the same text
f_items, f_cols = kb.gather(L2, None, None)
fs = kb.build(f_items, f_cols)
ix = {n["id"]: i for i, n in enumerate(fs["nodes"])}
E = lambda kind: {(fs["nodes"][e[0]]["id"], fs["nodes"][e[1]]["id"]) for e in fs["edges"] if e[2] == kind}
assert "project:alpha" in ix and fs["nodes"][ix["project:alpha"]]["t"] == "project", "a project used by 3 prompts is a node"
assert "project:beta" not in ix, "a project used once is no node (the tag rule)"
assert E("in_project") == {(a1, "project:alpha"), (a2, "project:alpha"), (a3, "project:alpha"), (b2, "project:alpha")}, E("in_project")
assert E("followed_by") == {(a1, a2), (a2, a3)}, E("followed_by")   # a chain in time order inside one session; single-prompt sessions and no session: none
assert E("same_text") == {(d2, d1), (d3, d1)}, E("same_text")   # every copy to the oldest; case and spaces ignored; two short texts are not joined
assert all(e[3] == 1 and e[4] == 0 for e in fs["edges"] if e[2] in ("in_project", "followed_by", "same_text")), "facts have score 1 and rank 0"
assert fs["edge_counts"]["followed_by"] == 2 and fs["algo"] == kb.ALGO
assert not any("alpha session" in json.dumps(n) for n in fs["nodes"] if n["t"] == "project"), "a project node holds only its name"
step("facts from the capture: project nodes (2 or more prompts), session chains in time order, identical text to the oldest copy (case and spaces ignored, short texts never), all score 1")
cap = kb.build(f_items, f_cols, cap=4)
assert cap["capped"] == len(f_items) - 4 and all(max(e[0], e[1]) < len(cap["nodes"]) for e in cap["edges"]), "edges only join items inside the cap"
step("the cap drops edges to items that were left out")


# ---------------------------------------------------------------- shared references: a link, file or ticket named by two or more items
def mk(id_, type_, title, text, ts=0.0):
    return {"id": id_, "type": type_, "title": title, "tags": [], "cols": [], "derived": "", "updated": ts, "ts": ts, "session": "", "project": "", "text": text, "vt": []}


ri = [mk("p1", "prompt", "one", "please fix backend/main.py and read https://example.com/docs/ about PROJ-12", 1),
      mk("p2", "prompt", "two", "same bug in backend/main.py, see https://EXAMPLE.com/docs and PROJ-12 and lonely.py", 2),
      mk("p3", "prompt", "three", "summarise Q3-notes.txt for me and also backend/main.py", 3),
      mk("s1", "studio", "four", "draft about https://example.com/docs and nothing else here", 4),
      mk("d1", "document", "Q3-notes.txt", "meeting notes about backend/main.py", 5),
      mk("d2", "document", "Q3 report final.pdf", "a report", 6),
      mk("p4", "prompt", "five", "the Q3 Report Final.pdf is long; Node.js and UTF-8 are not references", 7)]
rs = kb.build(ri, [])
rx = {n["id"]: i for i, n in enumerate(rs["nodes"])}
R = lambda kind: {(rs["nodes"][e[0]]["id"], rs["nodes"][e[1]]["id"]) for e in rs["edges"] if e[2] == kind}
refs = {n["id"] for n in rs["nodes"] if n["t"] == "reference"}
assert refs == {"ref:file:backend/main.py", "ref:link:example.com/docs", "ref:ticket:PROJ-12"}, refs   # used by two or more items; lonely.py (once), Node.js, UTF-8: no
assert rs["nodes"][rx["ref:file:backend/main.py"]]["rk"] == "file" and rs["nodes"][rx["ref:link:example.com/docs"]]["rk"] == "link" and rs["nodes"][rx["ref:ticket:PROJ-12"]]["rk"] == "ticket"
assert R("refers_to") == {("p1", "ref:file:backend/main.py"), ("p2", "ref:file:backend/main.py"), ("p3", "ref:file:backend/main.py"), ("d1", "ref:file:backend/main.py"),
                          ("p1", "ref:link:example.com/docs"), ("p2", "ref:link:example.com/docs"), ("s1", "ref:link:example.com/docs"),
                          ("p1", "ref:ticket:PROJ-12"), ("p2", "ref:ticket:PROJ-12")}, R("refers_to")
assert R("refers_doc") == {("p3", "d1"), ("p4", "d2")}, R("refers_doc")   # by file name; a name with spaces by substring, case folded; a document never names itself
assert all(e[3] == 1 and e[4] == 0 for e in rs["edges"] if e[2] in ("refers_to", "refers_doc"))
assert all(set(n) == {"id", "t", "n", "d", "rk"} for n in rs["nodes"] if n["t"] == "reference"), "a reference node holds its name, kind and count, nothing else (no surrounding text)"
step("shared references: a link, file or ticket named by two or more items is one node; items link to it; products and numbers are not references; a prompt naming a document links to it")

many = [mk(f"q{i}", "prompt", f"q{i}", " ".join(f"dir{j}/file{j}.py" for j in range(60)), i) for i in range(3)]
rm = kb.build(many, [])
per = {}
for e in rm["edges"]:
    if e[2] == "refers_to":
        per[e[0]] = per.get(e[0], 0) + 1
assert per and max(per.values()) == kb.REF_PER_ITEM, per
step("one item keeps at most 30 reference lines")

print("\nall Lattice base-layer checks passed")
