#!/usr/bin/env python3
"""Checks for the Gallery snapshot in backend/gallery.py. Plain asserts, no server. Needs numpy, so run it with the project's
interpreter:

    .venv/bin/python scripts/check_gallery.py

Everything runs on synthetic prompts in a temp directory; your real prompts, vectors and settings are never touched.
"""
import datetime
import gzip
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-gallery-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from backend import gallery as g  # noqa: E402
from backend import promptstore as ps  # noqa: E402
from backend.rag import indexer, vectors  # noqa: E402

LIB = TMP / "prompts"
STUDIO = LIB / "studio"


def step(msg: str) -> None:
    print("ok  ", msg)


T0 = datetime.datetime(2026, 1, 5, 9, 0).timestamp()
_STEMS = {
    "cooking": "recipe simmer garlic onion saucepan butter oven dough whisk season".split(),
    "travel": "flight airport luggage passport itinerary hotel museum train ticket beach".split(),
    "coding": "function python compile debug server database refactor commit endpoint array".split(),
}
# 40 words a topic (stem + ending): prompts of one topic share a theme but are not copies of each other
TOPICS = {t: [w + e for w in ws for e in ("", "ish", "ery", "ful")] for t, ws in _STEMS.items()}


def item(i: int, text: str, ts: float, **kw) -> dict:
    """What promptstore.load_all returns for one prompt (only the fields the snapshot reads)."""
    meta = {"title": kw.get("title", ""), "tags": kw.get("tags", []), "starred": kw.get("star", False), "purpose": ""}
    return {"id": f"p{i:04d}", "text": text, "ts": ts, "agent": kw.get("agent", "claude"), "meta": meta, "title": meta["title"] or text[:40],
            "project": kw.get("project", ""), "model": kw.get("model", ""), "updated": ts, "_path": ""}


def corpus(per: int = 20, seed: int = 1):
    rnd = random.Random(seed)
    items, truth = [], []
    for j in range(per):
        for t, words in TOPICS.items():
            text = " ".join(rnd.choices(words, k=rnd.randint(8, 12))) + " please make it"
            items.append(item(len(items), text, T0 + len(items) * 7 * 3600, agent=rnd.choice(["claude", "codex", "ollama"])))
            truth.append(t)
    return items, truth


# ---------------------------------------------------------------- empty and tiny libraries
s = g.build([], [])
assert s["n"] == 0 and s["rows"] == [] and s["clusters"] == [] and s["method"] == "none"
for n in (1, 9):
    s = g.build([item(i, f"short note number {i} about nothing", T0 + i) for i in range(n)], [])
    assert s["n"] == n and len(s["rows"]) == n and s["clusters"] == [] and s["terms"] == [] and all(r["x"] is None for r in s["rows"]), n
step("empty library and 1 or 9 prompts: rows only, no groups, map or words, no crash")

# ---------------------------------------------------------------- 60 prompts, three topics, words only (no stored vectors)
items, truth = corpus()
rep = "Please summarise the weekly report and list the three biggest risks with owners and dates"
for k in range(5):
    items.append(item(len(items), rep + (" thanks" if k % 2 else ""), T0 + (200 + k * 90) * 3600))
    truth.append("repeat")
items.append(item(len(items), "hello", T0 + 300 * 3600)); truth.append("hello")
items.append(item(len(items), "hello", T0 + 301 * 3600)); truth.append("hello")
items.append(item(len(items), "hello", T0 + 302 * 3600)); truth.append("hello")
s = g.build(items, [])
n = len(items)
assert s["n"] == n and s["method"] == "tfidf-svd" and 1 < len(s["clusters"]) <= g.K, (s["method"], len(s["clusters"]))
assert sum(c["n"] for c in s["clusters"]) == n and [c["n"] for c in s["clusters"]] == sorted((c["n"] for c in s["clusters"]), reverse=True)
tmap = {o["id"]: t for o, t in zip(items, truth)}   # rows are sorted by time, the corpus is not: match by id
by = {}
for r in s["rows"]:
    t = tmap[r["id"]]
    if t in TOPICS:
        by.setdefault(r["c"], []).append(t)
purity = sum(max(v.count(t) for t in TOPICS) for v in by.values()) / sum(len(v) for v in by.values())
assert purity >= 0.9, purity
step(f"topic groups follow the topics (purity {purity:.2f}), sizes sorted, every prompt in exactly one group")

assert all(0 <= r["x"] <= 1 and 0 <= r["y"] <= 1 for r in s["rows"]) and s["map"] == {"kind": "full", "shown": n, "cap": g.MAP_MAX}
words = {t["w"] for t in s["terms"]}
assert words and not (words & g.STOP) and "please" not in words and "make" not in words
assert all(t["df"] == len(t["ids"]) and 1 <= t["cluster"] <= g.K or t["cluster"] == 0 for t in s["terms"])
assert s["network"]["nodes"] and all(e["a"] in {x["w"] for x in s["network"]["nodes"]} for e in s["network"]["edges"])
step("map positions are inside 0..1, words exclude stop words and filler, posting lists match the counts")

s2 = g.build(items, [], ignore=g.ignore_set("Recipe, garlic\nbutter"))
w2 = {t["w"] for t in s2["terms"]} | {b["a"] for b in s2["bigrams"]} | {b["b"] for b in s2["bigrams"]}
assert not ({"recipe", "garlic", "butter"} & w2) and "simmer" in {t["w"] for t in s2["terms"]} | w2
assert g.ignore_set(" A,b ; C\n") == frozenset({"a", "b", "c"}) and g.ignore_set("") == frozenset()
step("the user's noise words are removed from words and phrases (any case, comma, space or line separated)")

groups = s["repeats"]
rid = lambda grp: {s["rows"][i]["id"] for i in grp["ids"]}
assert groups and groups[0]["n"] == 5 and rid(groups[0]) == {o["id"] for o, t in zip(items, truth) if t == "repeat"}, groups[:1]
assert not any(rid(r) & {o["id"] for o, t in zip(items, truth) if t == "hello"} for r in groups), "three short 'hello' prompts must not form a repeat group"
assert groups[0]["first"] < groups[0]["last"] and groups[0]["sample"].startswith("Please summarise")
step("a retyped prompt forms a repeat group; short prompts never do")

# ---------------------------------------------------------------- local time buckets, features, other scripts, code-only prompts
odd = [item(i, t, T0 + i * 3600) for i, t in enumerate(["```python\nprint(1)\n```", "Привет, мир! Как дела?", "日本語のプロンプト", "Fill {{name}} and {{name}} and {{city}}? Really?",
                                                          "plain words only here for padding", "more padding words for the check", "another padding line of words", "padding padding words again",
                                                          "yet another line of padding text", "one last padding sentence here"])]
so = g.build(odd, [])
r = so["rows"]
assert r[0]["cd"] == 1 and r[0]["ch"] == len(odd[0]["text"]) and r[3]["v"] == 2 and r[3]["q"] == 2 and r[1]["ln"] == 1
assert r[0]["d"] == datetime.datetime.fromtimestamp(T0).strftime("%Y-%m-%d") and r[0]["m"] == r[0]["d"][:7]
assert abs(r[0]["h"] - 9.0) < 0.01 and r[0]["t"] == int(T0 * 1000)
step("features and local-time buckets (code fences, variables, question marks, hour); code-only and non-English prompts do not crash")

# ---------------------------------------------------------------- life, treemap, version chains
lib = [item(0, "alpha", T0, title="Named", agent="claude", project="/x/proj"), item(1, "beta", T0 + 1, star=True, agent="codex", model="gpt"), item(2, "gamma", T0 + 2, agent="ollama", model="gemma")]
stu = [{"id": "ps-1", "title": "S1", "meta": {"status": "refined"}, "_path": ""}, {"id": "ps-2", "title": "S2", "meta": {"status": "draft"}, "_path": ""}]
vers = {"ps-1": [{"id": "a", "message": "Created", "ts": 1.0}, {"id": "b", "message": "Edit", "ts": 2.0}], "ps-2": [{"id": "c", "message": "Created", "ts": 1.0}]}
sl = g.build(lib, stu, versions_of=lambda o: 2 if o["id"] == "p0001" else 1, studio_versions=lambda o: vers[o["id"]])
lf = sl["life"]
assert lf["library"] == 3 and lf["studio"] == 2
assert {x["name"]: (x["n"], x["edited"]) for x in lf["lib_groups"]} == {"Kept as captured": (1, 0), "Titled or tagged": (1, 0), "Starred": (1, 1)}
assert {x["name"]: (x["n"], x["edited"]) for x in lf["stu_groups"]} == {"Draft": (1, 0), "Refined": (1, 1)}
assert sum(c["value"] for a in sl["treemap"]["children"] for c in a["children"]) == 3
assert [v["id"] for v in sl["vtrees"][0]["versions"]] == ["a", "b"] and len(sl["vtrees"]) == 1   # a prompt with one version has no chain
step("lifecycle groups, treemap totals and version chains (only prompts with 2+ versions)")

# ---------------------------------------------------------------- stored vectors: used when they cover the prompts, else the words
def fake_store(its, cover=1.0):
    rnd = np.random.default_rng(4)
    store = {}
    for i, o in enumerate(its):
        t = truth[i]
        base = np.zeros(12, dtype=np.float32)
        base[list(TOPICS).index(t) if t in TOPICS else 3 + (7 if t == "repeat" else 8)] = 1.0
        if rnd.random() <= cover:
            for p in indexer.prompt_passages(o, "library"):
                store[vectors.text_hash(p["text"])] = list(base + rnd.normal(0, 0.02 if t == "repeat" else 0.5, 12).astype(np.float32))
    return store


st = fake_store(items)
lookup = lambda model, hashes: {h: st[h] for h in hashes if h in st}
V = g.stored_vectors(items, "m1", lookup)
assert V is not None and V.shape == (n, 12) and g.stored_vectors(items, "", lookup) is None
assert g.stored_vectors(items, "m1", lambda m, hs: {}) is None
st60 = fake_store(items, cover=0.6)
assert g.stored_vectors(items, "m1", lambda m, hs: {h: st60[h] for h in hs if h in st60}) is None   # under 80% covered: the words are used for all
se = g.build(items, [], vecs_for=lambda its: g.stored_vectors(its, "m1", lookup))
assert se["method"] == "embeddings" and se["repeats"] and se["repeats"][0]["n"] == 5, (se["method"], se["repeats"][:1])
step("stored vectors are found by the indexer's passage text, used when 80%+ of prompts have one (method embeddings), else the words are used")

# ---------------------------------------------------------------- the map stays put when a few prompts are new
a = g.build(items, [])
more = items + [item(len(items), " ".join(TOPICS["travel"][:6]) + " please make it", T0 + 400 * 3600)]
b = g.build(more, [], prev=a)
assert b["map"]["kind"] == "placed" and len(b["rows"]) == n + 1
ak = {r["id"]: (r["x"], r["y"]) for r in a["rows"]}
assert all((r["x"], r["y"]) == ak[r["id"]] for r in b["rows"] if r["id"] in ak), "known prompts must keep their position"
newrow = b["rows"][-1]
assert 0 <= newrow["x"] <= 1 and 0 <= newrow["y"] <= 1
assert g.build(more, [], prev=a, force_map=True)["map"]["kind"] == "full"
many = items + [item(len(items) + k, "extra words about travel plans number %d" % k, T0 + (500 + k) * 3600) for k in range(12)]
assert g.build(many, [], prev=a)["map"]["kind"] == "full"   # more than 5% new: drawn again
step("a new prompt is placed beside its neighbours and the others do not move; Refresh map or many new prompts redraw it")

g.MAP_MAX = 12
sc = g.build(items[:30], [])
assert sc["map"] == {"kind": "full", "shown": 12, "cap": 12}
assert all(r["x"] is None for r in sc["rows"][:18]) and all(r["x"] is not None for r in sc["rows"][18:])
g.MAP_MAX = 3000
step("the map is capped to the newest MAP_MAX prompts; older ones have no position")

# ---------------------------------------------------------------- the running copy: files, signature, cache, background build
for i in range(14):
    ps.write_prompt(" ".join(random.Random(i).choices(TOPICS["coding"], k=9)) + " now", T0 + i * 3600, session_id=f"s{i}", cwd="/work/demo", root=LIB, extra={"agent": "claude"})
ps.create_studio("A studio prompt about travel plans and tickets", "Trip", ["travel"], root=STUDIO)
gal = g.Gallery(TMP / "data", LIB, STUDIO, model=lambda: "", ignore=lambda: "", vector_lookup=None, recheck=0.0)
before = gal.signature()
snap = gal.build_now()
assert snap["n"] == 14 and snap["life"]["studio"] == 1 and (TMP / "data" / "gallery" / "snapshot.json").exists()
assert gal.signature() == before
again = g.Gallery(TMP / "data", LIB, STUDIO, model=lambda: "", ignore=lambda: "", vector_lookup=None)
assert again._snap and again._snap["n"] == 14 and again._sig == before   # the cache file is read back
ps.write_prompt("one more prompt about databases and endpoints", T0 + 99 * 3600, session_id="new", root=LIB, extra={"agent": "claude"})
assert gal.signature() != before
changed = g.Gallery(TMP / "data", LIB, STUDIO, model=lambda: "", ignore=lambda: "alpha", vector_lookup=None)
assert changed.signature() != gal.signature()   # the ignore words are part of what the snapshot depends on
first = gal.get()
assert first["snapshot"]["n"] == 14 and first["status"]["state"] in ("building", "ready")   # answers at once with what it has
for _ in range(100):
    time.sleep(0.1)
    cur = gal.get()
    if cur["status"]["state"] == "ready" and cur["snapshot"]["n"] == 15:
        break
assert cur["snapshot"]["n"] == 15 and cur["status"]["state"] == "ready" and not cur["status"]["stale"] and cur["status"]["error"] == ""
step("signature covers prompts, model, vectors and ignore words; the cache file is reloaded; get() answers at once, rebuilds in the background and ends ready")

raw = g.gz(cur)
assert json.loads(gzip.decompress(raw))["snapshot"]["n"] == 15
step("gzip round trip of the response body")

print("\nall gallery checks passed")
