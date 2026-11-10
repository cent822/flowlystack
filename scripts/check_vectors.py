#!/usr/bin/env python3
"""Checks for the Collections vector store (backend/rag/vectors.py and lance.py). Plain asserts, temp folders only.

    .venv/bin/python scripts/check_vectors.py        # needs lancedb and numpy, so not the system python3
"""
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.rag.lance import INDEX_MIN_ROWS, LanceEngine   # noqa: E402
from backend.rag.vectors import ModelChanged, VectorCopy, VectorError, VectorStore, text_hash   # noqa: E402


def step(msg: str) -> None:
    print("ok  ", msg)


def raises(fn, exc, needle=""):
    try:
        fn()
    except exc as e:
        assert needle.lower() in str(e).lower(), f"{needle!r} not in {e}"
        return
    raise AssertionError(f"expected {exc.__name__}")


TMP = Path(tempfile.mkdtemp(prefix="flowlystack-vectors-check-"))
MODEL, DIM = "fake-embed", 8


def row(i, vec, source="document", ref="kd-a", collections=("c1",), tags=("t",), text=None):
    text = text if text is not None else f"passage {i}"
    return {"id": f"{ref}#{i}", "vector": list(vec), "source": source, "ref": ref, "collections": list(collections),
            "tags": list(tags), "text_hash": text_hash(text)}


def unit(i):   # axis vector: passage i is the exact answer to query i
    v = [0.0] * DIM
    v[i % DIM] = 1.0
    return v


def open_store(name="a", model=MODEL, dim=DIM):
    eng = LanceEngine()
    eng.open(TMP / name / "vectors", model, dim)
    return VectorStore(eng, VectorCopy(TMP / name / "embeddings.db"), model, dim)


# ---------------------------------------------------------------- basics
s = open_store()
s.upsert([row(0, unit(0)), row(1, unit(1), source="library", ref="p-1", collections=("c2",), tags=("t", "u")),
          row(2, unit(2), source="studio", ref="ps-1", collections=("c1", "c2"), tags=("u",))])
assert s.count() == 3
top = s.query(unit(1), k=3)
assert top[0]["id"] == "p-1#1" and abs(top[0]["score"] - 1.0) < 1e-6 and "vector" not in top[0]
assert [h["score"] for h in top] == sorted((h["score"] for h in top), reverse=True)
step("upsert and nearest-first query; score is cosine similarity; vectors are not returned")

assert {h["id"] for h in s.query(unit(0), 10, {"collections": ["c2"]})} == {"p-1#1", "ps-1#2"}
assert {h["id"] for h in s.query(unit(0), 10, {"collections": ["c1", "c2"]})} == {"kd-a#0", "p-1#1", "ps-1#2"}
assert {h["id"] for h in s.query(unit(0), 10, {"tags": ["t", "u"]})} == {"p-1#1"}          # tags: all of them
assert {h["id"] for h in s.query(unit(0), 10, {"source": "studio"})} == {"ps-1#2"}
assert {h["id"] for h in s.query(unit(0), 10, {"collections": ["c1"], "tags": ["u"]})} == {"ps-1#2"}
assert s.query(unit(0), 10, {"collections": ["nope"]}) == []
step("filters: any collection, all tags, source, and combinations")

assert [h["id"] for h in s.query(unit(0), 10, {"tags": ["it's \"odd\""]})] == []
s.upsert([row(9, unit(3), tags=("it's \"odd\"",), ref="kd-q'x")])
assert [h["id"] for h in s.query(unit(0), 10, {"tags": ["it's \"odd\""]})] == ["kd-q'x#9"]
s.delete_ref("kd-q'x")
step("quotes in tags and ids cannot break a filter or a delete")

s.upsert([row(1, unit(5), source="library", ref="p-1", collections=("c2",), tags=("new",))])   # same id again: replaced, not duplicated
assert s.count() == 3 and s.query(unit(5), 1)[0]["id"] == "p-1#1" and s.query(unit(5), 1)[0]["tags"] == ["new"]
assert [h["id"] for h in s.query(unit(1), 3)].count("p-1#1") == 1
step("upserting an existing id replaces it")

s.delete(["kd-a#0"])
assert "kd-a#0" not in {h["id"] for h in s.query(unit(0), 10)} and s.count() == 2
s.delete_ref("ps-1")
assert {h["id"] for h in s.query(unit(0), 10)} == {"p-1#1"}
s.delete([])
step("deleted passages are never returned (by id, and by document)")

s.set_collections("p-1", ["c7", "c8"])
assert s.query(unit(5), 1, {"collections": ["c7"]})[0]["collections"] == ["c7", "c8"] and s.query(unit(5), 1, {"collections": ["c2"]}) == []
s.set_collections("p-1", [])
assert s.query(unit(5), 1)[0]["collections"] == []
step("moving a document rewrites only its collections")

raises(lambda: s.upsert([row(3, [1.0, 2.0])]), VectorError, "numbers")
raises(lambda: s.query([1.0], 3), VectorError, "expects")
step("a vector of the wrong size is refused")

s.finish()
s.close()
s = open_store()   # restart
assert s.count() == 1 and s.query(unit(5), 1)[0]["id"] == "p-1#1"
step("data survives a restart")
s.close()

# many small writes must not leave a trail of old versions on disk: after finish() only the latest remains, and an old index is trimmed on open
import lancedb
for i in range(6):
    s = open_store()
    s.upsert([row(20 + i, unit(i % 8), ref="kd-v")])
    s.close()
_ver = lambda: len(lancedb.connect(str(TMP / "a" / "vectors")).open_table("chunks").list_versions())
assert _ver() > 1, "the test needs old versions to start from"
s = open_store(); assert _ver() == 1, _ver()   # opening an index with old versions trims them
s.upsert([row(40, unit(2), ref="kd-w")]); s.upsert([row(41, unit(3), ref="kd-w")]); s.finish()
assert _ver() == 1 and s.count() >= 3
s.close()
step("only the latest version is kept on disk (after finish, and trimmed when an old index is opened)")

eng = LanceEngine()
raises(lambda: eng.open(TMP / "a" / "vectors", "other-model", DIM), ModelChanged, "rebuild")
raises(lambda: eng.open(TMP / "a" / "vectors", MODEL, DIM + 1), ModelChanged, "rebuild")
(TMP / "a" / "vectors" / "meta.json").write_text("{not json")
raises(lambda: LanceEngine().open(TMP / "a" / "vectors", MODEL, DIM), VectorError, "cannot be read")
step("a changed model or vector size is refused with 'rebuild'; a broken meta.json is a readable error")

# ---------------------------------------------------------------- portable copy
c = VectorCopy(TMP / "copy.db")
h1, h2 = text_hash("same text"), text_hash("other")
c.put("m1", [(h1, [1.0, 2.0]), (h2, [3.0, 4.0])])
c.put("m2", [(h1, [9.0, 9.0, 9.0])])
assert c.get("m1", [h1, h2, "missing"]) == {h1: [1.0, 2.0], h2: [3.0, 4.0]} and c.get("m2", [h1]) == {h1: [9.0, 9.0, 9.0]}
assert c.count() == 3 and c.count("m1") == 2
c.put("m1", [(h1, [5.0, 6.0])])
assert c.get("m1", [h1]) == {h1: [5.0, 6.0]} and c.count("m1") == 2
assert c.prune({h1}, "m1") == 1 and c.count("m1") == 1 and c.count("m2") == 1
assert c.get("m1", [text_hash(str(i)) for i in range(1200)]) == {}   # more hashes than SQLite allows variables for
c.close()
step("portable copy: keyed by text hash and model, replace, prune per model, large lookups")

s = open_store("dup")
s.upsert([row(0, unit(0), text="same"), row(1, unit(0), text="same")])
assert s.copy.count(MODEL) == 1 and s.count() == 2
s.close()
step("two passages with the same text share one stored vector")

# ---------------------------------------------------------------- scale, incremental writes, rebuild
N, D = 5000, 64
rng = np.random.default_rng(7)
centres = rng.normal(size=(40, D))
base = (centres[rng.integers(0, 40, N)] + rng.normal(scale=0.6, size=(N, D))).astype("float32")
s = open_store("big", "big-model", D)
metas = []
t0 = time.time()
for i in range(0, N, 500):
    chunk = [{**row(j, base[j], text=f"t{j}", ref=f"kd-{j % 50:02d}", collections=(f"c{j % 3}",), tags=(f"g{j % 4}",)), "vector": base[j].tolist()}
             for j in range(i, i + 500)]
    s.upsert(chunk)
    metas += [{k: v for k, v in x.items() if k != "vector"} for x in chunk]
assert s.count() == N and not s.engine._indexed() and N >= INDEX_MIN_ROWS
s.finish()
assert s.engine._indexed()
step(f"{N} passages in {time.time() - t0:.1f}s; the HNSW index is built once the table is large enough")


def brute(q, k, ok=lambda j: True):
    sims = base @ q / (np.linalg.norm(base, axis=1) * np.linalg.norm(q))
    order = [j for j in np.argsort(-sims) if ok(j)][:k]
    return {f"kd-{j % 50:02d}#{j}" for j in order}


def recall(queries, where=None, ok=lambda j: True, k=10):
    hit = 0
    for q in queries:
        got = {h["id"] for h in s.query(q.tolist(), k, where)}
        hit += len(got & brute(q, k, ok))
    return hit / (k * len(queries))


Q = (centres[rng.integers(0, 40, 40)] + rng.normal(scale=0.6, size=(40, D))).astype("float32")
r_plain = recall(Q)
r_filt = recall(Q, {"collections": ["c1"], "tags": ["g2"]}, lambda j: j % 3 == 1 and j % 4 == 2)
assert r_plain >= 0.9 and r_filt >= 0.9, (r_plain, r_filt)
step(f"recall@10 against exact search: {r_plain:.3f} plain, {r_filt:.3f} with collection and tag filters")


def latency(n=60):
    ts = []
    for q in Q[:n % len(Q) or len(Q)]:
        t = time.perf_counter(); s.query(q.tolist(), 6); ts.append((time.perf_counter() - t) * 1000)
    return sorted(ts)[len(ts) // 2]


p50_before = latency()
for j in range(N, N + 200):   # one prompt at a time, the way the app writes
    v = (centres[j % 40] + rng.normal(scale=0.6, size=D)).astype("float32")
    s.upsert([row(j, v, text=f"t{j}", ref=f"kd-{j % 50:02d}", collections=(f"c{j % 3}",), tags=(f"g{j % 4}",))])
frags_before = s.engine._table.stats()["fragment_stats"]["num_fragments"]
p50_slow = latency()
s.finish()
frags_after = s.engine._table.stats()["fragment_stats"]["num_fragments"]
p50_after = latency()
assert s.count() == N + 200 and frags_after < frags_before and frags_after <= 3, (frags_before, frags_after)
assert p50_after < 50, p50_after
print(f"      query p50: {p50_before:.1f} ms indexed, {p50_slow:.1f} ms after 200 single writes ({frags_before} files), "
      f"{p50_after:.1f} ms after finish() ({frags_after} files)")
step("200 single writes then finish(): the small files are compacted and queries stay fast")
s.close()

# lose the engine's folder entirely: rebuild from the portable copy, no embedding needed
all_metas = metas + [{k: v for k, v in row(j, [0], text=f"t{j}", ref=f"kd-{j % 50:02d}", collections=(f"c{j % 3}",), tags=(f"g{j % 4}",)).items() if k != "vector"}
                     for j in range(N, N + 200)]
shutil.rmtree(TMP / "big" / "vectors")
eng = LanceEngine()
eng.open(TMP / "big" / "vectors", "big-model", D)
s = VectorStore(eng, VectorCopy(TMP / "big" / "embeddings.db"), "big-model", D)
assert s.count() == 0
extra = {"id": "kd-new#1", "source": "document", "ref": "kd-new", "collections": ["c0"], "tags": [], "text_hash": text_hash("never embedded")}
missing = s.rebuild(all_metas + [extra])
assert [m["id"] for m in missing] == ["kd-new#1"], missing[:3]
assert s.count() == N + 200 and s.engine._indexed()
s_r = recall(Q)
assert s_r >= 0.9, s_r
step(f"rebuilt {N + 200} passages from the copy without embedding anything; only the one with no stored vector is reported missing (recall {s_r:.3f})")
s.close()

shutil.rmtree(TMP, ignore_errors=True)
print("\nall vector checks passed")
