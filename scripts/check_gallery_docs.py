#!/usr/bin/env python3
"""Checks for the Documents Gallery snapshot in backend/gallery_docs.py. Plain asserts, no server. Needs numpy, so run
it with the project's interpreter:

    .venv/bin/python scripts/check_gallery_docs.py

Everything runs on synthetic documents in a temp directory; your real documents, collections, vectors and settings are never touched.
"""
import hashlib
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-gallery-docs-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend import collections as co  # noqa: E402
from backend import gallery as g  # noqa: E402
from backend import gallery_docs as gd  # noqa: E402
from backend.rag.vectors import text_hash  # noqa: E402


def step(msg: str) -> None:
    print("ok  ", msg)


T0 = 1_767_600_000.0   # a fixed moment in January 2026
_STEMS = {
    "cooking": "recipe simmer garlic onion saucepan butter oven dough whisk season".split(),
    "travel": "flight airport luggage passport itinerary hotel museum train ticket beach".split(),
    "coding": "function python compile debug server database refactor commit endpoint array".split(),
}
TOPICS = {t: [w + e for w in ws for e in ("", "ish", "ery", "ful")] for t, ws in _STEMS.items()}


def body(topic: str, rnd: random.Random, k: int = 70) -> str:
    return " ".join(rnd.choices(TOPICS[topic], k=k))


def doc(i: int, text: str, ts: float, **kw) -> dict:
    return {"id": f"kd-{i:012x}", "name": kw.get("name", f"file{i}.md"), "type": kw.get("type", "markdown"), "ts": ts, "cols": kw.get("cols", ["col-a"]),
            "passages": kw.get("passages", [text])}


def corpus(per: int = 10, seed: int = 1):
    rnd = random.Random(seed)
    docs, truth = [], []
    for j in range(per):
        for t in TOPICS:
            docs.append(doc(len(docs), body(t, rnd), T0 + 86400 * len(docs)))
            truth.append(t)
    return docs, truth


NAMES = {"col-a": "Alpha", "col-b": "Beta"}

# ---------------------------------------------------------------- features
text = "# Title\n\n## Part\n\n- one\n- two\n1. three\n\n| a | b |\n\n```\ncode\n```\n\nTotal 2026 items: 4500 and more words here.\n"
f = gd.doc_features(text, 3)
assert f["hd"] == 2 and f["cd"] == 1 and f["np"] == 3 and f["w"] == len(text.split()), f
assert f["ls"] > 25 and f["nm"] > 5 and f["junk"] is False, f
assert gd.doc_features("```\nopen fence only\n", 1)["cd"] == 1
junk = "0 1 2 3 4 5 6 7 8 9 " * 40
assert gd.doc_features(junk, 1)["junk"] is True and gd.doc_features("short 123", 1)["junk"] is False
step("document measurements: headings, code, list lines, numbers, junk flag")

# ---------------------------------------------------------------- empty and small
e = gd.build_documents([])
assert e["n"] == 0 and e["rows"] == [] and e["mode"] == "documents" and e["features"] == gd.FEATURES_DOCS and e["min_card"] == gd.MIN_CARD
assert gd.build_documents([doc(1, "   ", T0, passages=["  ", ""])])["n"] == 0
keys = {f_["k"] for f_ in gd.FEATURES_DOCS}
assert e["corr"] == gd.CORR_DOCS and set(gd.CORR_DOCS) <= keys and all(f_["tr"] in ("log", "sqrt", "lin") for f_ in gd.FEATURES_DOCS)
assert {f_["k"]: f_.get("unit") for f_ in gd.FEATURES_DOCS if f_.get("unit")} == {"nm": "%", "ls": "%"}
step("empty and blank documents give an empty snapshot")

rnd = random.Random(2)
small = [doc(i, body("cooking", rnd), T0 + i * 100, type=("pdf" if i % 2 else "markdown"), cols=(["col-a", "col-b"] if i == 0 else ["col-b"])) for i in range(6)]
s = gd.build_documents(small, names=NAMES)
assert s["n"] == 6 and s["clusters"] == [] and s["tree"] is None and s["repeats"] == [] and "need" in s["note"]
assert [r["i"] for r in s["rows"]] == list(range(6)) and all(r["x"] is None and r["cited"] is None for r in s["rows"])
assert s["agents"] == ["markdown", "pdf"] and {t["type"]: t["n"] for t in s["types"]} == {"pdf": 3, "markdown": 3}
assert {c["name"]: c["n"] for c in s["collections"]} == {"Alpha": 1, "Beta": 6}, s["collections"]
assert s["rows"][0]["cols"] == ["col-a", "col-b"] and s["rows"][1]["cols"] == ["col-b"]   # sorted by collection name
tot = sum(c["value"] for a in s["treemap"]["children"] for c in a["children"])
assert tot == sum(r["w"] for r in s["rows"]) and {a["name"] for a in s["treemap"]["children"]} == {"markdown", "pdf"}
step("small set: rows, types, collections, treemap (each document once), no groups")

# ---------------------------------------------------------------- groups from words
docs, truth = corpus()
s = gd.build_documents(docs, names=NAMES)
assert s["n"] == 30 and s["method"] == "tfidf-svd" and len(s["clusters"]) == 5 and s["tree"]   # K = n // 6 groups
by = {}
for r, t in zip(s["rows"], truth):
    by.setdefault(r["c"], []).append(t)
assert all(len(set(v)) == 1 for v in by.values()), by
assert all(r["x"] is not None for r in s["rows"]) and s["map"]["kind"] == "full" and s["map"]["shown"] == 30
assert s["terms"] and s["network"]["nodes"] and all(t["df"] <= 0.35 * 30 for t in s["terms"])
assert [r["m"] for r in s["rows"]][0] == "2026-01" and s["months"][0] == "2026-01" and s["months"] == sorted(s["months"])
assert all(k in r for r in s["rows"] for k in keys), "every measurement of the snapshot's list is a field of every row"
assert json.loads(json.dumps(s)) == s
step("30 documents: every group holds one topic (from words), map, terms, months, JSON-safe")

# ---------------------------------------------------------------- vectors, and the 80% rule
reg = {}
basis = np.eye(16)[:3]
for d, t in zip(docs, truth):
    reg[text_hash(d["passages"][0])] = (basis[list(TOPICS).index(t)] + np.random.default_rng(len(reg)).normal(0, 0.05, 16)).astype(np.float32).tolist()
look = lambda model, hashes: {h: reg[h] for h in hashes if h in reg}   # noqa: E731
v = gd.stored_vectors(docs, "m", look)
assert v is not None and v.shape == (30, 16)
assert gd.stored_vectors(docs, "", look) is None and gd.stored_vectors([], "m", look) is None
s2 = gd.build_documents(docs, names=NAMES, vecs_for=lambda it: gd.stored_vectors(it, "m", look))
assert s2["method"] == "embeddings" and len(s2["clusters"]) == 5
by2 = {}
for r, t in zip(s2["rows"], truth):
    by2.setdefault(r["c"], []).append(t)
assert all(len(set(x)) == 1 for x in by2.values())
few = {h: x for h, x in list(reg.items())[:20]}   # 20 of 30 covered: under 80%
assert gd.stored_vectors(docs, "m", lambda m, hs: {h: few[h] for h in hs if h in few}) is None
most = {h: x for h, x in list(reg.items())[:25]}   # 25 of 30: the missing five get the mean
vm = gd.stored_vectors(docs, "m", lambda m, hs: {h: most[h] for h in hs if h in most})
assert vm is not None and vm.shape == (30, 16)
# several passages: the document vector is their mean
two = [doc(0, "", T0, passages=["alpha text", "beta text"])]
vv = gd.stored_vectors(two, "m", lambda m, hs: {text_hash("alpha text"): [1.0, 0.0], text_hash("beta text"): [0.0, 1.0]})
assert np.allclose(vv[0], [0.5, 0.5])
step("stored vectors: mean per document, embeddings used at 80% or more, words under it")

# ---------------------------------------------------------------- repeats (groups of two count for documents)
rnd = random.Random(5)
base = body("coding", rnd, 120)
rep = [dict(d) for d in docs]
rep.append(doc(900, base, T0 + 86400 * 40, name="contract-v1.pdf", type="pdf"))
rep.append(doc(901, base + " plus one extra sentence at the end.", T0 + 86400 * 400, name="contract-v2.pdf", type="pdf"))
sr = gd.build_documents(rep, names=NAMES)
ids = {r["id"]: r["i"] for r in sr["rows"]}
pair = {ids[f"kd-{900:012x}"], ids[f"kd-{901:012x}"]}
groups = [set(x["ids"]) for x in sr["repeats"]]
assert any(pair <= x for x in groups), groups
assert any(len(x) == 2 and x == pair for x in groups) or any(pair <= x for x in groups)
assert all(x["n"] >= 2 for x in sr["repeats"])
step("near-identical documents are found as a repeat group of two")

# the prompts Gallery keeps its rule: groups of 3 or more by default
Zn, _ = g.space(g.tfidf([g.keep_words(g.tokens(d["passages"][0])) for d in rep])[2], None)
assert all(x["n"] >= 3 for x in g.repeat_groups(Zn, [d["passages"][0] for d in rep], [0.0] * len(rep), np.zeros(len(rep), dtype=int), 0.72))
step("gallery.repeat_groups default (groups of 3) unchanged")

# ---------------------------------------------------------------- junk and long documents
jd = [dict(d) for d in docs] + [doc(950, junk, T0 + 1, name="table.pdf", type="pdf")]
sj = gd.build_documents(jd, names=NAMES)
assert sj["junk"] == 1 and [r for r in sj["rows"] if r["id"] == f"kd-{950:012x}"][0]["junk"] is True
long_ = [dict(d) for d in docs] + [doc(951, body("travel", random.Random(8), 70000), T0 + 2, name="huge.txt", type="text")]
t0 = time.time()
sl = gd.build_documents(long_, names=NAMES)
assert time.time() - t0 < 60 and sl["n"] == 31
step("junk documents are flagged and kept out of the words; a very long document does not stall the build")

# ---------------------------------------------------------------- the map is kept when a few documents are new
more = docs + [doc(960, body("cooking", random.Random(9)), T0 + 86400 * 90)]
sp = gd.build_documents(more, names=NAMES, prev=s)
assert sp["map"]["kind"] == "placed" and all(r["x"] is not None for r in sp["rows"])
old = {r["id"]: (r["x"], r["y"]) for r in s["rows"]}
assert all(old[r["id"]] == (r["x"], r["y"]) for r in sp["rows"] if r["id"] in old)
step("map: one new document is placed beside its neighbours, the others do not move")

# ---------------------------------------------------------------- real storage in a temp collections root
ROOT = TMP / "collections"
a = co.create("Alpha", root=ROOT)
b = co.create("Beta", root=ROOT)
rnd = random.Random(11)
added = []
for j in range(12):
    t = list(TOPICS)[j % 3]
    md = f"# {t} notes {j}\n\n{body(t, rnd, 90)}\n\n- {body(t, rnd, 6)}\n".encode()
    r = co.add_document(a["id"] if j % 4 else b["id"], f"{t}-{j}.md", md, root=ROOT)
    added.append(r["document"]["id"])
co.add_to(b["id"], added[1], root=ROOT)   # one document in two collections
bad = co.add_document(a["id"], "weird.xyz", b"\x00\x01 not a supported type", root=ROOT)["document"]
assert bad["status"] == "failed"


def tree_hash(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(f"{p.relative_to(root)}|{p.stat().st_size}|{p.stat().st_mtime_ns}\n".encode())
    return h.hexdigest()


calls = []
G = gd.DocGallery(TMP / "data", ROOT, model=lambda: "", ignore=lambda: "", vector_lookup=None, recheck=0.0)
before = tree_hash(ROOT)
sig1 = G.signature()
assert sig1 == G.signature()
snap = G.build_now()
assert tree_hash(ROOT) == before, "building must not write into the collections folder"
assert snap["n"] == 12 and bad["id"] not in {r["id"] for r in snap["rows"]}, "a failed file has no text and is not a row"
assert {c["name"]: c["n"] for c in snap["collections"]} == {"Alpha": 9, "Beta": 4}, snap["collections"]
assert [r for r in snap["rows"] if r["id"] == added[1]][0]["cols"] == [a["id"], b["id"]]   # Alpha before Beta
assert (TMP / "data" / "gallery" / "documents.json").is_file()
assert not any(p.suffix == ".tmp" for p in (TMP / "data" / "gallery").iterdir())
step("real storage: failed files left out, a document in two collections, nothing written to the collections folder, cache file saved")

# cache reload
G2 = gd.DocGallery(TMP / "data", ROOT, model=lambda: "", ignore=lambda: "", vector_lookup=None, recheck=0.0)
assert G2._snap and G2._snap["n"] == 12 and G2.signature() == G2._sig
step("cache: a new object loads the saved snapshot and sees it as current")

# signature reacts to what the snapshot depends on
co.add_document(a["id"], "extra.md", b"# extra\n\n" + body("travel", rnd, 80).encode(), root=ROOT)
assert G.signature() != sig1
sig2 = G.signature()
co.trash_document(added[2], root=ROOT)
assert G.signature() != sig2
assert gd.DocGallery(TMP / "data", ROOT, model=lambda: "m2", ignore=lambda: "", vector_lookup=None).signature() != G.signature()
assert gd.DocGallery(TMP / "data", ROOT, model=lambda: "", ignore=lambda: "buddy", vector_lookup=None).signature() != G.signature()
assert gd.DocGallery(TMP / "data", ROOT, model=lambda: "", ignore=lambda: "", vector_lookup=None, vector_count=lambda m: 5).signature() != G.signature()
snap = G.build_now()
assert snap["n"] == 12 and added[2] not in {r["id"] for r in snap["rows"]}, "a trashed document is not a row"
step("signature: new document, trashed document, model, ignore words and vector count each change it")

# get(): answers at once, builds in the background, then is ready
G3 = gd.DocGallery(TMP / "data2", ROOT, model=lambda: "", ignore=lambda: "", vector_lookup=None, recheck=0.0)
first = G3.get()
assert first["status"]["state"] in ("building", "ready")
for _ in range(100):
    time.sleep(0.1)
    ans = G3.get()
    if ans["status"]["state"] == "ready" and ans["snapshot"]:
        break
assert ans["status"]["state"] == "ready" and ans["snapshot"]["n"] == 12 and ans["status"]["documents"] == 12 and ans["status"]["stale"] is False
step("get(): background build, then ready with the document count")

# vectors through the class: a lookup that raises must not fail the build
Gv = gd.DocGallery(TMP / "data3", ROOT, model=lambda: "m", ignore=lambda: "", vector_lookup=lambda m, h: 1 / 0, recheck=0.0)
assert Gv.build_now()["n"] == 12 and Gv.build_now()["method"] in ("tfidf-svd", "none")
step("a failing vector lookup falls back to the words")

# an empty collections folder
Ge = gd.DocGallery(TMP / "data4", TMP / "nothing-here", model=lambda: "", ignore=lambda: "", vector_lookup=None)
assert Ge.build_now()["n"] == 0
step("no collections at all: empty snapshot, no error")

# ---------------------------------------------------------------- Use: citations from saved chats
ids_ = [d["id"] for d in docs]   # the rows are in import order, which is the order of `docs`
cites = {"chats": 2, "exchanges": 3, "cited": {ids_[0]: 2, ids_[1]: 1}}
su = gd.build_documents(docs, names=NAMES, cites=cites)
assert su["use"]["history"] is True and su["use"]["exchanges"] == 3 and su["rows"][0]["cited"] == 2 and su["rows"][2]["cited"] == 0
assert sum(1 for r in su["rows"] if r["cited"]) == 2 and sum(1 for r in su["rows"] if r["cited"] == 0) == 28
sn = gd.build_documents(docs, names=NAMES)
assert sn["use"]["history"] is False and all(r["cited"] is None for r in sn["rows"])
step("use: cited counts with saved chats; no history means null counts")

# the closest Library prompts: cosine of stored vectors, only when the groups come from embeddings
rnd = random.Random(7)
lib_items = [{"id": f"p{i}", "t": f"prompt {i}"} for i in range(9)]
Pv = np.array([basis[i % 3] + np.random.default_rng(100 + i).normal(0, 0.05, 16) for i in range(9)], dtype=np.float32)
sne = gd.build_documents(docs, names=NAMES, vecs_for=lambda it: gd.stored_vectors(it, "m", look), prompts_for=lambda: (lib_items, Pv))
assert sne["method"] == "embeddings" and len(sne["nearest"]) == 30
for i, t in enumerate(truth):
    top = sne["nearest"][str(i)]
    assert len(top) == 5 and top[0]["s"] >= top[-1]["s"] and int(top[0]["id"][1:]) % 3 == list(TOPICS).index(t), (i, top[0])
assert gd.build_documents(docs, names=NAMES, prompts_for=lambda: (lib_items, Pv))["nearest"] == {}, "words only: no nearest"
assert gd._nearest(np.ones((2, 4), dtype=np.float32), lib_items, Pv) == {}, "different vector sizes are refused"
step("closest Library prompts: right topic first, five each, nothing from the words method, a size mismatch is refused")

# ---------------------------------------------------------------- chat files in the real storage
CR = TMP / "colls"
ca, cb = co.create("A", root=CR), co.create("B", root=CR)
dids = [co.add_document(ca["id"], f"d{i}.md", f"# d{i}\n\n{body('cooking', rnd, 60)}".encode(), root=CR)["document"]["id"] for i in range(3)]
assert gd.chat_citations(CR) is None and gd.chat_stamp(CR) == gd.chat_stamp(CR)
st0 = gd.chat_stamp(CR)
empty = co.create_chat(ca["id"], root=CR)   # no exchange yet: not counted
assert gd.chat_citations(CR) is None


def ex(*pairs):
    return {"prompt": "q", "response": "a", "retrieved": [{"id": f"{r}#{n}", "ref": r, "cite": c} for r, n, c in pairs]}


ch1 = co.create_chat(ca["id"], root=CR)
co.add_exchange(ca["id"], ch1["id"], ex((dids[0], 0, 1), (dids[0], 1, 2), (dids[1], 0, None)), root=CR)   # two passages of one document: one citation; a found-not-sent one: none
co.add_exchange(ca["id"], ch1["id"], ex((dids[0], 0, 1), ("ps-abc#0", 0, 1)), root=CR)                    # a prompt is not a document
ch2 = co.create_chat("prompts", root=CR)   # a My prompts chat may cite documents too
co.add_exchange("prompts", ch2["id"], ex((dids[2], 0, 1)), root=CR)
cc_ = gd.chat_citations(CR)
assert cc_["chats"] == 2 and cc_["exchanges"] == 3 and cc_["cited"] == {dids[0]: 2, dids[2]: 1}, cc_
assert gd.chat_stamp(CR) != st0
st1 = gd.chat_stamp(CR)
co.add_exchange(ca["id"], ch1["id"], ex((dids[1], 0, 1)), root=CR)
assert gd.chat_stamp(CR) != st1 and gd.chat_citations(CR)["cited"][dids[1]] == 1
cd_ = TMP / "colls" / cb["id"]
cch = co.create_chat(cb["id"], root=CR)
co.add_exchange(cb["id"], cch["id"], ex((dids[2], 0, 1)), root=CR)
assert gd.chat_citations(CR)["cited"][dids[2]] == 2
co.trash_collection(cb["id"], root=CR)   # a trashed collection's chats are not counted
assert gd.chat_citations(CR)["cited"][dids[2]] == 1
bad = co._chats_dir(ca["id"], CR) / "ch-deadbeef.json"
bad.write_text("{not json")
assert gd.chat_citations(CR)["chats"] == 2, "a damaged chat file is skipped"
step("citations from saved chats: once per exchange, only passages that were sent, only documents, My prompts chats included, trashed collections and damaged files left out")

GC = gd.DocGallery(TMP / "dataC", CR, model=lambda: "", ignore=lambda: "", vector_lookup=None, recheck=0.0)
sg = GC.signature()
sc = GC.build_now()
by_id = {r["id"]: r for r in sc["rows"]}
assert sc["use"]["history"] and by_id[dids[0]]["cited"] == 2 and by_id[dids[1]]["cited"] == 1 and sc["use"]["exchanges"] == 4
co.add_exchange(ca["id"], ch1["id"], ex((dids[1], 0, 1)), root=CR)
assert GC.signature() != sg, "a new exchange changes the signature"
step("the class: rows carry the counts, a new exchange changes the signature")

# the class with a Library and stored vectors: nearest prompts end to end
from backend import promptstore as ps  # noqa: E402
from backend.rag import indexer as ix  # noqa: E402
LIBD = TMP / "lib"
tnames = list(TOPICS)
topic_of = lambda text: next(tn for tn in tnames if any(w_ in text for w_ in _STEMS[tn]))   # noqa: E731
for i in range(12):
    ps.write_prompt(body(tnames[i % 3], random.Random(i), 12) + " please", T0 + i * 3600, session_id=f"s{i}", cwd="/work/x", root=LIBD, extra={"agent": "claude"})
for i in range(10):   # ten more documents: 13 in all, enough for groups
    co.add_document(ca["id"], f"{tnames[i % 3]}-{i}.md", f"# {tnames[i % 3]} {i}\n\n{body(tnames[i % 3], rnd, 70)}".encode(), root=CR)
reg2 = {}
for o in ps.load_all(LIBD):
    for p_ in ix.prompt_passages(o, "library"):
        reg2[text_hash(p_["text"])] = (basis[tnames.index(topic_of(o["text"]))] + np.random.default_rng(len(reg2)).normal(0, 0.03, 16)).astype(np.float32).tolist()
dd, nm = gd.load_documents(CR)
for d_ in dd:
    for t_ in d_["passages"]:
        reg2[text_hash(t_)] = (basis[tnames.index(topic_of(t_))] + np.random.default_rng(len(reg2)).normal(0, 0.03, 16)).astype(np.float32).tolist()
look2 = lambda m, hs: {h: reg2[h] for h in hs if h in reg2}   # noqa: E731
GN = gd.DocGallery(TMP / "dataN", CR, model=lambda: "m", ignore=lambda: "", vector_lookup=look2, library_dir=LIBD, recheck=0.0)
sgn = GN.build_now()
assert sgn["n"] == 13 and sgn["method"] == "embeddings" and len(sgn["nearest"]) == 13
for i, r in enumerate(sgn["rows"]):
    top = sgn["nearest"][str(i)]
    want = topic_of(dd[[d_["id"] for d_ in dd].index(r["id"])]["passages"][0])
    pt = topic_of(next(o["text"] for o in ps.load_all(LIBD) if o["id"] == top[0]["id"]))
    assert pt == want and len(top) == 5 and top[0]["t"], (r["title"], want, pt)
sig_a = GN.signature()
ps.write_prompt(body("travel", random.Random(99), 12) + " later", T0 + 99999, session_id="s99", cwd="/work/x", root=LIBD, extra={"agent": "claude"})
assert GN.signature() != sig_a, "a new Library prompt changes the signature when a model is set"
assert gd.DocGallery(TMP / "dataN", CR, model=lambda: "", ignore=lambda: "", vector_lookup=look2, library_dir=LIBD).build_now()["nearest"] == {}, "no model: no nearest prompts"
step("end to end: Library and documents in one embedding space give the closest prompts of the same topic; a new prompt changes the signature; no model, no card")

# ---------------------------------------------------------------- the passage map (stored vectors only)
mdocs = []
for i in range(30):
    t = tnames[i % 3]
    mdocs.append(doc(2000 + i, "", T0 + 86400 * i, passages=[body(t, random.Random(500 + i * 3 + k), 50) for k in range(3)]))
reg3 = {}
for d_ in mdocs:
    for t_ in d_["passages"]:
        reg3[text_hash(t_)] = (basis[tnames.index(topic_of(t_))] + np.random.default_rng(len(reg3)).normal(0, 0.05, 16)).astype(np.float32).tolist()
look3 = lambda m, hs: {h: reg3[h] for h in hs if h in reg3}   # noqa: E731
pm0 = gd.build_passage_map(mdocs, model="", lookup=look3)
assert pm0["kind"] == "none" and pm0["reason"] == "no_model" and pm0["total"] == 90 and pm0["pts"] == []
assert gd.build_passage_map(mdocs, model="m", lookup=None)["reason"] == "no_model"
assert gd.build_passage_map(mdocs, model="m", lookup=lambda m, hs: {})["reason"] == "no_vectors"
pm = gd.build_passage_map(mdocs, model="m", lookup=look3)
assert pm["kind"] == "full" and pm["shown"] == 90 == len(pm["pts"]) and pm["missing"] == 0 and pm["total"] == 90
assert all(0 <= q["x"] <= 1 and 0 <= q["y"] <= 1 and q["d"].startswith("kd-") and q["n"] in (0, 1, 2) and len(q["s"]) <= 100 for q in pm["pts"])
assert json.loads(json.dumps(pm)) == pm
topic_by_doc = {d_["id"]: tnames[i % 3] for i, d_ in enumerate(mdocs)}
XY = np.array([[q["x"], q["y"]] for q in pm["pts"]])
nn = ((XY[:, None, :] - XY[None, :, :]) ** 2).sum(-1)
np.fill_diagonal(nn, 9)
same = np.mean([topic_by_doc[pm["pts"][i]["d"]] == topic_by_doc[pm["pts"][int(nn[i].argmin())]["d"]] for i in range(90)])
assert same > 0.9, same
step("passage map: reasons without a model or vectors; every passage placed; neighbours on the map share a topic")

keep_ = g.MAP_MAX
g.MAP_MAX = 12
try:
    capped = gd.build_passage_map(mdocs, model="m", lookup=look3)
finally:
    g.MAP_MAX = keep_
newest = {d_["id"] for d_ in mdocs[-4:]}
assert capped["shown"] == 12 and {q["d"] for q in capped["pts"]} <= newest | {mdocs[-5]["id"]} and capped["total"] == 90
half = {h: v for h, v in list(reg3.items())[:80]}
pp = gd.build_passage_map(mdocs, model="m", lookup=lambda m, hs: {h: half[h] for h in hs if h in half})
assert pp["shown"] == 80 and pp["missing"] == 10 and pp["total"] == 90
step("passage map: the newest MAP_MAX passages only; passages without a vector are left out and counted")

more = mdocs + [doc(3000, "", T0 + 86400 * 400, passages=[body("travel", random.Random(77), 50)])]
reg3[text_hash(more[-1]["passages"][0])] = (basis[1] + 0.01).astype(np.float32).tolist()
ps2 = gd.build_passage_map(more, model="m", lookup=look3, prev=pm)
assert ps2["kind"] == "placed" and ps2["shown"] == 91
old_ = {(q["d"], q["n"]): (q["x"], q["y"]) for q in pm["pts"]}
assert all(old_[(q["d"], q["n"])] == (q["x"], q["y"]) for q in ps2["pts"] if (q["d"], q["n"]) in old_)
assert gd.build_passage_map(more, model="m", lookup=look3, prev=pm, force=True)["kind"] == "full"
step("passage map: one new passage is placed beside its neighbours and the rest do not move; force redraws")

# the class: asked for, built in the background, kept in passages.json, and not disturbed by chats or the Library
GP = gd.DocGallery(TMP / "dataP", CR, model=lambda: "m", ignore=lambda: "", vector_lookup=look2, library_dir=LIBD, recheck=0.0)
a0 = GP.passages()
assert a0["status"]["state"] in ("building", "ready")
for _ in range(100):
    time.sleep(0.1)
    ans = GP.passages()
    if ans["status"]["state"] == "ready":
        break
assert ans["status"]["state"] == "ready" and ans["part"]["kind"] in ("full", "placed") and ans["part"]["shown"] >= 13 and ans["status"]["stale"] is False
assert (TMP / "dataP" / "gallery" / "passages.json").is_file() and not list((TMP / "dataP" / "gallery").glob("*.tmp"))
GP2 = gd.DocGallery(TMP / "dataP", CR, model=lambda: "m", ignore=lambda: "", vector_lookup=look2, library_dir=LIBD)
assert GP2._pdata and GP2._pdata["shown"] == ans["part"]["shown"] and GP2.psignature() == GP2._psig, "a new object loads the saved passage map"
ps_sig = GP.psignature()
co.add_exchange(ca["id"], ch1["id"], ex((dids[1], 0, 1)), root=CR)
ps.write_prompt(body("coding", random.Random(5), 12) + " zz", T0 + 123456, session_id="s55", cwd="/work/x", root=LIBD, extra={"agent": "claude"})
assert GP.psignature() == ps_sig, "chats and Library prompts do not change the passage map's signature"
co.add_document(ca["id"], "late.md", b"# late\n\n" + body("coding", rnd, 70).encode(), root=CR)
assert GP.psignature() != ps_sig
GM = gd.DocGallery(TMP / "dataM", CR, model=lambda: "", ignore=lambda: "", vector_lookup=look2, recheck=0.0)
for _ in range(100):
    time.sleep(0.1)
    an = GM.passages()
    if an["status"]["state"] != "building":
        break
assert an["status"]["state"] == "none" and an["status"]["reason"] == "no_model" and an["part"] is None
step("the class: built on request in the background, saved and reloaded, unaffected by chats and Library prompts, 'none' with a reason without a model")

# ---------------------------------------------------------------- a word network of long documents must not be a hairball
rr = random.Random(12)
dense = [doc(4000 + i, "", T0 + i, passages=[" ".join(f"zq{chr(97 + k // 26)}{chr(97 + k % 26)}ish" for k in range(60) if rr.random() < 0.3)]) for i in range(24)]   # each word in about a third of the documents
sd = gd.build_documents(dense, names=NAMES)
nodes_ = sd["network"]["nodes"]
assert len(nodes_) >= 10 and len(sd["network"]["edges"]) <= gd.EDGES_PER_NODE * len(nodes_), (len(nodes_), len(sd["network"]["edges"]))
raw_edges = g._terms([g.keep_words(g.tokens(d["passages"][0])) for d in dense], [g.tokens(d["passages"][0]) for d in dense], np.zeros(24, dtype=int), frozenset(), 24)["network"]["edges"]
assert len(raw_edges) > gd.EDGES_PER_NODE * len(nodes_), "the synthetic corpus must be dense enough for the cap to matter"
E = sd["network"]["edges"]
assert all(a["j"] >= b["j"] for a, b in zip(E, E[1:])), "strongest first"
connected_raw = {w_ for e in raw_edges for w_ in (e["a"], e["b"])}
connected_now = {w_ for e in E for w_ in (e["a"], e["b"])}
assert connected_now == connected_raw, "no word that had a line loses all of them"
for node_ in nodes_:
    mine = sorted([e for e in raw_edges if node_["w"] in (e["a"], e["b"])], key=lambda e: (-e["j"], -e["n"], e["a"], e["b"]))[:gd.EDGES_PER_NODE]
    assert all(e in E for e in mine), "each word keeps its three strongest lines"
rep_ = [doc(4100 + i, "", T0 + i, passages=["backend backend backend library prompt " * 12 + f"unique{i} filler{i}"]) for i in range(12)]
assert not any(b["a"] == b["b"] for b in gd.build_documents(rep_, names=NAMES)["bigrams"])
step("the word network keeps at most three lines per word (strongest first); a phrase of one word twice is dropped")

print("\nall Documents Gallery checks passed")
