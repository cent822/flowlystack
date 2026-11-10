#!/usr/bin/env python3
"""Checks for Lattice's entity layer, backend/kgraph.py. Plain asserts, no server, standard library plus the
project's own modules (no numpy), so `python3` is enough:

    python3 scripts/check_kgraph_store.py

Everything runs on synthetic prompts and documents in a temp directory; your real prompts, collections and settings are never touched.
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-kgstore-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import collections as co  # noqa: E402
from backend import kgraph as kg  # noqa: E402
from backend import promptstore as ps  # noqa: E402

LIB, STUDIO, COL, KG = TMP / "prompts", TMP / "prompts" / "studio", TMP / "collections", TMP / "kgraph"
ST = kg.Stores(LIB, STUDIO, COL)


def step(msg: str) -> None:
    print("ok  ", msg)


def tree(root: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")) if root.exists() else []:
        if p.is_file():
            h.update(str(p.relative_to(root)).encode() + p.read_bytes())
    return h.hexdigest()


def add(payload, **kw):
    kw.setdefault("by", "claude-test")
    return kg.add_batch(payload, root=KG, stores=kw.pop("stores", kg.Stores(LIB, STUDIO, COL)), **kw)


def refused(payload, words, **kw):
    before = tree(KG)
    try:
        add(payload, **kw)
    except kg.Invalid as e:
        assert words.lower() in str(e).lower(), f"expected '{words}' in: {e}"
        assert tree(KG) == before, "a refused call must write nothing"
        return str(e)
    raise AssertionError(f"was accepted, expected a refusal containing '{words}'")


def ments(*pairs, item, quote):
    return [{"type": "mentions", "to": n, "item": item, "quote": quote} for n in pairs]


# ---------------------------------------------------------------- the world
LIB_TEXT = "Our team runs FastAPI behind Caddy.   Alice Chen reviews the Deployment plan every Friday and tracks p95 latency."
pid = ps.write_prompt(LIB_TEXT, time.time() - 100, "s1", "", "hook", LIB, {"agent": "claude"})
sd = ps.create_studio("Kubernetes is the target for the Deployment plan.\nSecond line about Docker images.", "K8s draft", [], None, STUDIO)["id"]
c1 = co.create("Kitchen notes", "", [], COL)
doc = co.add_document(c1["id"], "ops.md", b"# Ops\n\nThe pager rotation is owned by Bob Marsh.\n\nIncident reviews use the five whys process.", COL)["document"]["id"]

# ---------------------------------------------------------------- empty
assert kg.list_batches(KG) == [] and kg.damaged(KG) == []
ix = kg.entities_index(KG)
assert ix["entities"] == {} and ix["edges"] == [] and ix["by_key"] == {}
step("no folder yet: no batches, an empty index, nothing damaged")

# ---------------------------------------------------------------- accepted
r = add({"entities": [{"name": "FastAPI", "kind": "technology", "aliases": ["fast api"], "note": "web framework"},
                      {"name": "Caddy", "kind": "technology"}],
         "edges": ments("FastAPI", "Caddy", item=pid, quote="runs FastAPI behind Caddy")
         + [{"type": "related", "from": "FastAPI", "to": "Caddy", "label": "runs behind", "item": pid, "quote": "FastAPI behind Caddy"}]}, note="first")
assert r["stored"] and r["created"] == 2 and r["merged"] == 0 and r["edges_added"] == 3 and r["refused_count"] == 0, r
b1 = kg.get_batch(r["batch"], KG)
assert b1 and b1["by"] == "claude-test" and b1["via"] == "mcp" and b1["note"] == "first" and not b1["run"] and not b1["hidden"] and not b1["undone"]
assert (KG / "batches" / (r["batch"] + ".json")).is_file() and not list((KG / "batches").glob("*.tmp"))
ix = kg.entities_index(KG)
assert {e["name"] for e in ix["entities"].values()} == {"FastAPI", "Caddy"} and len(ix["edges"]) == 3
fa = ix["entities"][ix["by_key"]["fastapi|technology"]]
assert fa["aliases"] == ["fast api"] and fa["note"] == "web framework" and fa["id"].startswith("en-") and len(fa["id"]) == 13
assert all(e["by"] == "claude-test" and e["via"] == "mcp" and not e["source_gone"] for e in ix["edges"])
s = kg.list_batches(KG)[0]
assert s["entities"] == 2 and s["edges"] == 3 and s["by"] == "claude-test" and not s["open"]
step("an accepted call stores one batch with entities, mentions and a related edge; the index shows them with who made them")

# studio and document items, a quote across a line break and with other spacing and capital letters
r2 = add({"entities": [{"name": "Kubernetes", "kind": "technology"}, {"name": "Bob Marsh", "kind": "person"}, {"name": "Five whys", "kind": "process"}],
          "edges": ments("Kubernetes", item=sd, quote="KUBERNETES   is the target\nfor the deployment plan")
          + ments("Bob Marsh", item=doc, quote="owned by Bob Marsh")
          + ments("Five whys", item=doc, quote="incident reviews use the five whys process")})
assert r2["created"] == 3 and r2["edges_added"] == 3
step("quotes are found in Studio prompts and in documents, ignoring spacing, line breaks and capital letters")

# ---------------------------------------------------------------- refused (strict): nothing is written
M = lambda **k: {"entities": [{"name": "Zed", "kind": "concept"}], "edges": [{"type": "mentions", "to": "Zed", "item": pid, "quote": "Alice Chen reviews the Deployment plan"} | k]}
refused(M(quote="Alice Chen was fired yesterday"), "does not occur")
refused(M(item="no-such-item-1"), "does not exist")
refused(M(quote="Alice"), "too short")
refused(M(quote="x" * 201), "limit is 200")
refused(M(quote=""), "is empty")
refused(M(type="knows"), "type must be")
refused(M(to="Nobody"), "no entity is named")
refused(M(**{"from": sd}), "goes from the item")
refused({"entities": [{"name": "Zed", "kind": "wizard"}], "edges": []}, "kind must be one of")
refused({"entities": [{"name": "   ", "kind": "concept"}], "edges": []}, "name is empty")
refused({"entities": [{"name": "n" * 121, "kind": "concept"}], "edges": []}, "limit is 120")
refused({"entities": [{"name": "Zed", "kind": "concept", "aliases": list("abcdefghi")}], "edges": []}, "aliases")
refused({"entities": [{"name": "Zed", "kind": "concept", "note": "n" * 201}], "edges": []}, "limit is 200")
refused({"entities": [{"name": "Zed", "kind": "concept"}], "edges": []}, "no verified `mentions`")
refused({"entities": [], "edges": []}, "Nothing to add")
refused("text", "object")
refused({"entities": "x"}, "must be lists")
refused({"entities": [{"name": "Zed", "kind": "concept"}], "edges": [{"type": "related", "from": "Zed", "to": "Zed", "label": "x", "item": pid, "quote": "Alice Chen reviews"}]}, "itself")
refused({"entities": [{"name": "Zed", "kind": "concept"}, {"name": "Yan", "kind": "concept"}],
         "edges": ments("Zed", "Yan", item=pid, quote="Alice Chen reviews the Deployment")
         + [{"type": "related", "from": "Zed", "to": "Yan", "item": pid, "quote": "Alice Chen reviews the Deployment"}]}, "needs a label")
refused({"entities": [{"name": "Zed", "kind": "concept"}], "edges": ments("Zed", item=pid, quote="Alice Chen reviews the Deployment plan")
         + [{"type": "related", "from": "Zed", "to": "en-0000000000", "label": "x", "item": pid, "quote": "Alice Chen reviews the Deployment"}]}, "no entity with id")
refused({"entities": [{"name": "Z", "kind": "concept"}] * 201, "edges": []}, "limit is 200")
refused({"entities": [], "edges": [{}] * 401}, "limit is 400")
n_before = len(kg.list_batches(KG))
msg = refused({"entities": [{"name": "Zed", "kind": "concept"}], "edges": [{"type": "mentions", "to": "Zed", "item": pid, "quote": "Alice Chen reviews the Deployment plan"},
                                                                          {"type": "mentions", "to": "Zed", "item": sd, "quote": "this is not in the studio prompt"}]}, "edge 2")
assert len(kg.list_batches(KG)) == n_before
step("strict refusals write nothing and name the first failing entity or edge (kind, name, size, item, quote, label, references, limits)")

# the boundary of the quote length: 200 characters pass, and a 50-word quote of short words fits
long_text = " ".join(f"w{n % 7}x" for n in range(60))     # 60 short words
lp = ps.write_prompt(long_text + " end", time.time(), "s2", "", "hook", LIB, {"agent": "claude"})
q50 = " ".join(long_text.split()[:50])
assert len(q50) <= 200
assert add({"entities": [{"name": "Wordy", "kind": "other"}], "edges": ments("Wordy", item=lp, quote=q50)})["created"] == 1
text200 = "a" * 199 + "b"
lp2 = ps.write_prompt("start " + text200 + " finish", time.time(), "s3", "", "hook", LIB, {"agent": "claude"})
assert add({"entities": [{"name": "Edge200", "kind": "other"}], "edges": ments("Edge200", item=lp2, quote=text200)})["created"] == 1
refused({"entities": [{"name": "Edge201", "kind": "other"}], "edges": ments("Edge201", item=lp2, quote="start " + text200[:196] + "x" * 6)}, "limit is 200")
step("a 50-word quote of short words and a quote of exactly 200 characters pass; 201 does not")

# ---------------------------------------------------------------- de-duplication
r3 = add({"entities": [{"name": "  fastapi. ", "kind": "technology", "aliases": ["FastAPI framework", "fast api"], "note": "ignored: the note exists"}],
          "edges": ments("fastapi", item=pid, quote="FastAPI behind Caddy")})   # same edge as before except the quote: edge is new, entity merged
assert r3["created"] == 0 and r3["merged"] == 1 and r3["edges_added"] == 0 and r3["edges_duplicate"] == 1, r3   # same type, item and entity: one edge
ix = kg.entities_index(KG)
fa = ix["entities"][ix["by_key"]["fastapi|technology"]]
assert fa["aliases"] == ["fast api", "FastAPI framework"], fa["aliases"]
assert len([e for e in ix["entities"].values() if e["key"] == "fastapi|technology"]) == 1
r4 = add({"entities": [{"name": "FASTAPI", "kind": "technology", "aliases": ["FastAPI framework"], "note": "x"}],
          "edges": ments("FastAPI", item=sd, quote="Docker images")})   # a different item: a new edge, the entity merges and keeps its id
ix = kg.entities_index(KG)
fa2 = ix["entities"][ix["by_key"]["fastapi|technology"]]
assert r4["created"] == 0 and r4["merged"] == 1 and r4["edges_added"] == 1 and fa2["id"] == fa["id"] and "FastAPI framework" in fa2["aliases"]
assert fa2["note"] == "web framework" and len(fa2["batches"]) == 3, fa2   # created in the first batch, carried by the two later ones
# the same name in another kind is another entity; a bare name that now matches two kinds must be given as an id
r5 = add({"entities": [{"name": "Caddy", "kind": "product"}], "edges": [{"type": "mentions", "to": "Caddy", "item": pid, "quote": "behind Caddy"}]})
assert r5["created"] == 1
refused({"entities": [], "edges": ments("Caddy", item=pid, quote="behind Caddy")}, "more than one entity")
caddy = ix["by_key"]["caddy|technology"]
assert add({"entities": [], "edges": ments(caddy, item=sd, quote="Docker images")})["edges_added"] == 1   # by id
step("entities de-duplicate by normalised name and kind across calls and batches (aliases join, the note is never overwritten); an ambiguous name needs the id")

# ---------------------------------------------------------------- undo of the creator keeps what later batches carried
first = r["batch"]
kg.undo_batch(first, KG)
ix = kg.entities_index(KG)
assert "fastapi|technology" in ix["by_key"], "a later batch carried the entity, so it survives"
assert "caddy|technology" in ix["by_key"], "a later batch carried the entity by id"
assert all(e["batch"] != first for e in ix["edges"])
assert [s for s in kg.list_batches(KG) if s["id"] == first][0]["undone"] > 0
try:
    kg.undo_batch(first, KG)
    raise AssertionError("second undo accepted")
except kg.Invalid as e:
    assert e.status == 409
kg.reinstate_batch(first, KG)
assert len(kg.entities_index(KG)["edges"]) > 0 and any(e["batch"] == first for e in kg.entities_index(KG)["edges"])
step("Undo hides a whole batch (nothing deleted), entities other batches carried survive it, and the batch can be brought back")

# ---------------------------------------------------------------- non-strict (the local-model route)
r6 = add({"entities": [{"name": "Good one", "kind": "concept"}, {"name": "Bad kind", "kind": "nope"}, {"name": "Unsourced", "kind": "concept"}, {"name": "Fake", "kind": "person"}],
          "edges": ments("Good one", item=pid, quote="Alice Chen reviews the Deployment plan")
          + ments("Fake", item=pid, quote="this sentence is invented by a small model")
          + ments("Bad kind", item=pid, quote="Alice Chen reviews the Deployment plan")}, by="local model", via="local", strict=False)
assert r6["stored"] and r6["created"] == 1 and r6["edges_added"] == 1 and r6["refused_count"] >= 4, r6
assert kg.get_batch(r6["batch"], KG)["via"] == "local"
ix = kg.entities_index(KG)
assert "good one|concept" in ix["by_key"] and "fake|person" not in ix["by_key"] and "unsourced|concept" not in ix["by_key"] and "bad kind|nope" not in ix["by_key"]
r7 = add({"entities": [{"name": "Only fake", "kind": "concept"}], "edges": ments("Only fake", item=pid, quote="nothing like this in the item")}, by="local model", via="local", strict=False)
assert not r7["stored"] and r7["refused_count"] >= 2
step("non-strict calls keep what verifies and count what was rejected; a call with nothing left writes no batch")

# ---------------------------------------------------------------- runs
run = kg.start_run("claude-test", "building the cooking layer", root=KG)
assert run["run"] and run["open"] and run["entities"] == 0
a = add({"entities": [{"name": "Run one", "kind": "concept"}], "edges": ments("Run one", item=pid, quote="Alice Chen reviews the Deployment plan")}, run=run["id"])
b = add({"entities": [{"name": "Run two", "kind": "concept"}], "edges": ments("Run two", item=sd, quote="Docker images")}, run=run["id"])
assert a["batch"] == b["batch"] == run["id"]
rb = kg.get_batch(run["id"], KG)
assert len(rb["entities"]) == 2 and len(rb["edges"]) == 2
refused({"entities": [{"name": "Other", "kind": "concept"}], "edges": ments("Other", item=pid, quote="Alice Chen reviews")}, "belongs to someone else", run=run["id"], by="intruder")
refused({"entities": [{"name": "Other", "kind": "concept"}], "edges": ments("Other", item=pid, quote="Alice Chen reviews")}, "does not exist", run=first)   # a one-call batch is not a run
refused({"entities": [{"name": "Other", "kind": "concept"}], "edges": ments("Other", item=pid, quote="Alice Chen reviews")}, "does not exist", run="gb-ffffffffff")
real_now = kg._now
kg._now = lambda: real_now() + kg.RUN_IDLE + 5
try:
    refused({"entities": [{"name": "Other", "kind": "concept"}], "edges": ments("Other", item=pid, quote="Alice Chen reviews")}, "closed", run=run["id"])
    assert not [s for s in kg.list_batches(KG) if s["id"] == run["id"]][0]["open"]
finally:
    kg._now = real_now
kg.undo_batch(run["id"], KG)
refused({"entities": [{"name": "Other", "kind": "concept"}], "edges": ments("Other", item=pid, quote="Alice Chen reviews")}, "undone", run=run["id"])
assert "run one|concept" not in kg.entities_index(KG)["by_key"]
kg.reinstate_batch(run["id"], KG)
assert "run one|concept" in kg.entities_index(KG)["by_key"]
step("a run is one batch: calls join it, other owners and closed or undone runs are refused, one Undo removes all of it")

# ---------------------------------------------------------------- hide, delete, restore
kg.hide_batch(run["id"], True, KG)
assert "run one|concept" not in kg.entities_index(KG)["by_key"] and "run one|concept" in kg.entities_index(KG, include_hidden=True)["by_key"]
kg.hide_batch(run["id"], False, KG)
raw = kg.delete_batch(run["id"], KG)
assert not (KG / "batches" / (run["id"] + ".json")).exists() and raw["id"] == run["id"] and len(raw["entities"]) == 2
try:
    kg.delete_batch(run["id"], KG)
    raise AssertionError("second delete accepted")
except kg.Invalid as e:
    assert e.status == 404
kg.restore_batch(json.loads(json.dumps(raw)), KG)
assert "run two|concept" in kg.entities_index(KG)["by_key"]
try:
    kg.restore_batch(raw, KG)
    raise AssertionError("restore over an existing batch accepted")
except kg.Invalid as e:
    assert e.status == 409
for bad in ({}, {"id": "gb-zz"}, "x", None):
    try:
        kg.restore_batch(bad, KG)
        raise AssertionError("restored something that is not a batch")
    except kg.Invalid as e:
        assert e.status == 400
ok = kg.restore_batch({"id": "gb-0123456789", "ts": 1, "by": "x" * 99, "entities": [{"id": "x"}, {"id": "en-aaaaaaaaaa", "name": "Kept", "kind": "wizard"}], "edges": [{"type": "knows"}]}, KG)
assert ok["entities"] == 0 and ok["edges"] == 0 and len(kg.get_batch("gb-0123456789", KG)["by"]) == 60   # bad rows are dropped, fields clipped
kg.delete_batch("gb-0123456789", KG)
step("hide, delete and restore work; restore re-checks the shape, refuses an existing id and drops bad rows")

# ---------------------------------------------------------------- delete one entity (and its edges) with Undo
ix = kg.entities_index(KG)
rt = ix["by_key"]["run one|concept"]
removed = kg.delete_entity(rt, KG)
ix = kg.entities_index(KG)
assert rt not in ix["entities"] and not [e for e in ix["edges"] if e["to"] == rt or e["from"] == rt]
assert kg.restore_entity(json.loads(json.dumps(removed)), KG) >= 2
ix = kg.entities_index(KG)
assert rt in ix["entities"] and [e for e in ix["edges"] if e["to"] == rt]
for bad_id in ("x", "en-ffffffffff"):
    try:
        kg.delete_entity(bad_id, KG)
        raise AssertionError("deleted an entity that does not exist")
    except kg.Invalid as e:
        assert e.status == 404
step("deleting an entity removes it and its edges everywhere and returns what it took, so Undo can put it back")

# ---------------------------------------------------------------- an item that disappears
ps.trash(sd, STUDIO) if hasattr(ps, "trash") else None
ix = kg.entities_index(KG, item_exists=kg.Stores(LIB, STUDIO, COL).exists)
gone = [e for e in ix["edges"] if e["item"] == sd]
assert gone and all(e["source_gone"] for e in gone) and all(e["quote"] for e in gone)
assert not [e for e in ix["edges"] if e["item"] == pid and e["source_gone"]]
refused({"entities": [{"name": "Late", "kind": "concept"}], "edges": ments("Late", item=sd, quote="Docker images")}, "does not exist")
step("when an item is trashed its entity edges stay with the quote as written and are marked 'source gone'; new edges to it are refused")

# ---------------------------------------------------------------- concurrent writes
errs = []
def worker(n):
    try:
        add({"entities": [{"name": f"Concurrent {n}", "kind": "concept"}, {"name": "Shared name", "kind": "concept"}],
             "edges": ments(f"Concurrent {n}", "Shared name", item=pid, quote="Alice Chen reviews the Deployment plan")}, by=f"t{n}")
    except Exception as e:   # noqa: BLE001
        errs.append(repr(e))
ts = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
[t.start() for t in ts]
[t.join() for t in ts]
assert not errs, errs
ix = kg.entities_index(KG)
assert sum(1 for e in ix["entities"].values() if e["name"].startswith("Concurrent")) == 12
assert sum(1 for e in ix["entities"].values() if e["key"] == "shared name|concept") == 1, "the same name written at once is still one entity"
assert not kg.damaged(KG) and not list((KG / "batches").glob("*.tmp"))
ids = [e["id"] for e in ix["entities"].values()]
assert len(ids) == len(set(ids))
step("12 simultaneous writers: every batch is complete, one shared entity, no stray temp files, unique ids")

# ---------------------------------------------------------------- a damaged file
bad_file = KG / "batches" / "gb-deadbeef00.json"
bad_file.write_text('{"id": "gb-deadbeef00", "entities": [')
mirror = KG / "batches" / "gb-deadbeef01.json"
mirror.write_text(json.dumps({"id": "gb-feedface11"}))   # file name and id disagree
n_ok = len(kg.list_batches(KG))
assert kg.damaged(KG) == ["gb-deadbeef00.json", "gb-deadbeef01.json"]
assert add({"entities": [{"name": "After damage", "kind": "concept"}], "edges": ments("After damage", item=pid, quote="Alice Chen reviews the Deployment plan")})["created"] == 1
assert len(kg.list_batches(KG)) == n_ok + 1 and "after damage|concept" in kg.entities_index(KG)["by_key"]
assert bad_file.read_text() == '{"id": "gb-deadbeef00", "entities": [', "a damaged file is never rewritten"
step("a damaged or mismatched file is skipped and reported, never rewritten, and does not stop new writes")

# ---------------------------------------------------------------- the stores are untouched
lib_before = tree(LIB)
add({"entities": [{"name": "Read only", "kind": "concept"}], "edges": ments("Read only", item=pid, quote="Alice Chen reviews the Deployment plan")})
assert tree(LIB) == lib_before and not (LIB / "kgraph").exists() and not (COL / "kgraph").exists()
step("adding an entity reads the stores and writes only into the kgraph folder")

# ---------------------------------------------------------------- items a run read (a local-model run that found nothing)
rr = kg.start_run("local model: m", "reads", "local", root=KG)
assert rr["read"] == 0
fresh = ps.create_studio("A note nobody has extracted anything from yet.", "Fresh", [], None, STUDIO)["id"]
kg.mark_read(rr["id"], [fresh, "bad id!", fresh, doc], KG)
raw = kg.get_batch(rr["id"], KG)
assert raw["read"] == [fresh, doc] and kg.list_batches(KG)[0]["read"] == 2
assert {fresh, doc} <= kg.covered_items(KG) and pid in kg.covered_items(KG)
kg.undo_batch(rr["id"], KG)
assert fresh not in kg.covered_items(KG), "an undone run no longer covers its items"
kg.reinstate_batch(rr["id"], KG)
kg.hide_batch(rr["id"], True, KG)
assert fresh in kg.covered_items(KG), "a hidden run still counts as read"
back = kg.delete_batch(rr["id"], KG)
assert fresh not in kg.covered_items(KG)
kg.restore_batch(json.loads(json.dumps(back)), KG)
assert kg.get_batch(rr["id"], KG)["read"] == [fresh, doc], "restore keeps the read items"
try:
    kg.mark_read("gb-ffffffffff", [doc], KG)
    raise AssertionError("marked a run that does not exist")
except kg.Invalid as e:
    assert e.status == 404
step("a run can remember the items it read (even with nothing found): they count as covered, undo frees them, delete and restore keep them")

print("\nall Lattice entity-layer checks passed")
