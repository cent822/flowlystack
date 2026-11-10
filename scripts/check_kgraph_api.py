#!/usr/bin/env python3
"""API checks for /api/kgraph (Lattice). Plain asserts, standard library only. It needs a TEST server with an
empty temp prompts folder and its own empty settings folder, and it writes prompt files into that folder, so never point it at your real one
(every variable on its own line; zsh does not split a shell variable of settings):

    T=$(mktemp -d); S=$(mktemp -d)
    env FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 FLOWLYSTACK_AUTH=off ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$T BASE=http://127.0.0.1:8799 python3 scripts/check_kgraph_api.py

Stop the server by the PID on port 8799 afterwards.
"""
import gzip
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_openai import FakeOpenAI   # noqa: E402
from backend import kgraph as kg   # noqa: E402  (the entity layer files: standard library)
from backend import promptstore as ps   # noqa: E402  (only its file writer: standard library)


def step(msg: str) -> None:
    print("ok  ", msg)


def call(method: str, path: str, gzip_ok: bool = True, body=None, expect: int = 200):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data, headers={"Accept-Encoding": "gzip" if gzip_ok else "identity", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, enc, hd, code = r.read(), r.headers.get("Content-Encoding", ""), r.headers, r.status
    except urllib.error.HTTPError as e:
        raw, enc, hd, code = e.read(), e.headers.get("Content-Encoding", ""), e.headers, e.code
    assert code == expect, (method, path, code, raw[:200])
    return json.loads(gzip.decompress(raw) if enc == "gzip" else raw), hd


def wait_ready(n: int, tries: int = 150):
    for _ in range(tries):
        d, _h = call("GET", "/api/kgraph")
        if d["status"]["state"] == "ready" and d["snapshot"] and d["snapshot"]["n_items"] == n and not d["status"]["stale"]:
            return d
        time.sleep(0.2)
    raise AssertionError(f"snapshot did not reach {n} items: {d['status']}")


# empty folder: the first look answers at once (building, no snapshot yet), then an empty snapshot
d, h = call("GET", "/api/kgraph")
assert set(d) == {"status", "snapshot"} and d["status"]["state"] in ("building", "ready") and h["Cache-Control"] == "no-store"
d = wait_ready(0)
assert d["snapshot"]["nodes"] == [] and d["snapshot"]["method"] == "none"
step("an empty library answers at once with a status and builds an empty snapshot (no crash, never cached)")

rnd = random.Random(2)
topics = {"cooking": "recipe simmer garlic onion saucepan butter oven dough whisk season".split(), "travel": "flight airport luggage passport itinerary hotel museum train ticket beach".split()}
T0 = time.time() - 20 * 86400
for n in range(14):
    t = "cooking" if n % 2 else "travel"
    ps.write_prompt(" ".join(rnd.choices(topics[t], k=10)) + " please", T0 + n * 7200, f"s{n}", "", "hook", PROMPTS, {"agent": "claude"})
d = wait_ready(14)
s = d["snapshot"]
assert s["method"] == "tfidf-svd" and s["counts"]["prompt"] == 14 and s["edge_counts"]["similar"] > 0
assert all(set(n) == {"id", "t", "n", "d"} for n in s["nodes"]) and all(len(e) == 5 for e in s["edges"])
assert "please" not in json.dumps(s["edges"]) and all("text" not in n for n in s["nodes"])
step("14 prompts: words method, nodes and edges in the compact shape, no prompt text beyond titles")

raw, h = call("GET", "/api/kgraph", gzip_ok=False)
assert raw["snapshot"]["n_items"] == 14 and h.get("Content-Encoding") is None
_, h2 = call("GET", "/api/kgraph", gzip_ok=True)
assert h2["Content-Encoding"] == "gzip"
step("gzip only when the browser accepts it")

ps.write_prompt("recipe garlic butter oven dough please", time.time(), "new", "", "hook", PROMPTS, {"agent": "claude"})
for _ in range(100):   # the signature check runs at most every 5 s
    d, _h = call("GET", "/api/kgraph")
    if d["snapshot"] and d["snapshot"]["n_items"] == 15 and d["status"]["state"] == "ready":
        break
    time.sleep(0.3)
assert d["snapshot"]["n_items"] == 15, d["status"]
step("a new prompt is picked up by a background rebuild")

r, _ = call("POST", "/api/kgraph/rebuild")
assert r["status"]["state"] in ("building", "ready") and r["snapshot"] is not None
wait_ready(15)
step("POST /api/kgraph/rebuild answers at once and builds again")

# ---------- the entity layer: list, evidence, hide, undo, delete, restore ----------
e0, _ = call("GET", "/api/kgraph/entities")
assert e0["entities"] == [] and e0["edges"] == [] and e0["batches"] == [] and e0["damaged"] == []
step("no entity layer yet: empty lists")

QUOTE_A = "Alice Chen leads the Platform team at Acme Corp"
pa = ps.write_prompt(QUOTE_A + " every day.", time.time(), "ent1", "", "hook", PROMPTS, {"agent": "claude"})
pb = ps.write_prompt("Kubernetes runs the deployment plan for the team.", time.time(), "ent2", "", "hook", PROMPTS, {"agent": "claude"})
run = kg.start_run("Cursor", "People and tools")
r1 = kg.add_batch({"entities": [{"name": "Alice Chen", "kind": "person", "aliases": ["Alice"]}, {"name": "Acme Corp", "kind": "organization"}],
                   "edges": [{"type": "mentions", "to": "Alice Chen", "item": pa, "quote": QUOTE_A}, {"type": "mentions", "to": "Acme Corp", "item": pa, "quote": "Platform team at Acme Corp"},
                             {"type": "related", "from": "Alice Chen", "to": "Acme Corp", "label": "works at", "item": pa, "quote": QUOTE_A}]}, by="Cursor", run=run["id"])
r2 = kg.add_batch({"entities": [{"name": "Kubernetes", "kind": "technology"}], "edges": [{"type": "mentions", "to": "Kubernetes", "item": pb, "quote": "Kubernetes runs the deployment plan"}]},
                  by="local model", via="local", note="Tech")
e1, _ = call("GET", "/api/kgraph/entities")
names = {e["name"]: e for e in e1["entities"]}
assert set(names) == {"Alice Chen", "Acme Corp", "Kubernetes"} and len(e1["edges"]) == 4 and len(e1["batches"]) == 2
assert all(not x["source_gone"] for x in e1["edges"]) and "quote" not in json.dumps(e1) and QUOTE_A not in json.dumps(e1), "the list carries no quotes"
assert {b["id"]: b["entities"] for b in e1["batches"]} == {r1["batch"]: 2, r2["batch"]: 1}
step("the entity list has entities, edges and batches, and no quotes")

alice = names["Alice Chen"]["id"]
d1, _ = call("GET", "/api/kgraph/entity/" + alice)
assert d1["entity"]["aliases"] == ["Alice"] and len(d1["evidence"]) == 2
men = [x for x in d1["evidence"] if x["type"] == "mentions"][0]
rel = [x for x in d1["evidence"] if x["type"] == "related"][0]
assert men["quote"] == QUOTE_A and men["item"] == pa and men["by"] == "Cursor" and men["via"] == "mcp" and men["run_note"] == "People and tools" and men["when"] > 0
assert rel["label"] == "works at" and rel["direction"] == "out" and rel["other"]["name"] == "Acme Corp"
call("GET", "/api/kgraph/entity/en-0000000000", expect=404)
step("one entity's evidence has the quote, the source item, who made it and the run; an unknown id is 404")

assert call("PATCH", f"/api/kgraph/batches/{r1['batch']}", body={"hidden": True})[0]["batch"]["hidden"] is True
e2, _ = call("GET", "/api/kgraph/entities")
assert {e["name"] for e in e2["entities"]} == {"Kubernetes"} and [b["hidden"] for b in e2["batches"] if b["id"] == r1["batch"]] == [True]
assert call("GET", "/api/kgraph/entity/" + alice)[0]["evidence"][0]["hidden"] is True
call("PATCH", f"/api/kgraph/batches/{r1['batch']}", body={"hidden": False})
call("PATCH", "/api/kgraph/batches/gb-ffffffffff", body={"hidden": True}, expect=404)
call("PATCH", "/api/kgraph/batches/not-an-id", body={"hidden": True}, expect=404)
step("Hide takes a run out of the picture and keeps it in the list; Show brings it back; unknown or malformed ids are 404")

call("POST", f"/api/kgraph/batches/{r1['batch']}/undo")
assert {e["name"] for e in call("GET", "/api/kgraph/entities")[0]["entities"]} == {"Kubernetes"}
call("GET", "/api/kgraph/entity/" + alice, expect=404)
call("POST", f"/api/kgraph/batches/{r1['batch']}/undo", expect=409)
call("POST", f"/api/kgraph/batches/{r1['batch']}/reinstate")
call("POST", f"/api/kgraph/batches/{r1['batch']}/reinstate", expect=409)
assert len(call("GET", "/api/kgraph/entities")[0]["entities"]) == 3
step("Undo hides a run everywhere (its entities are gone from the list and the evidence), twice is 409, Restore brings it back")

gone = call("DELETE", f"/api/kgraph/batches/{r2['batch']}")[0]["removed"]
assert gone["id"] == r2["batch"] and len(gone["entities"]) == 1 and not (PROMPTS / "kgraph" / "batches" / (r2["batch"] + ".json")).exists()
call("DELETE", f"/api/kgraph/batches/{r2['batch']}", expect=404)
assert call("POST", "/api/kgraph/batches/restore", body={"removed": gone})[0]["batch"]["id"] == r2["batch"]
call("POST", "/api/kgraph/batches/restore", body={"removed": gone}, expect=409)
call("POST", "/api/kgraph/batches/restore", body={"removed": {"id": "nope"}}, expect=400)
call("POST", "/api/kgraph/batches/restore", body={}, expect=400)
assert len(call("GET", "/api/kgraph/entities")[0]["entities"]) == 3
step("Delete returns the raw run, a second delete is 404, restore puts it back (an existing one is 409, forged ones 400)")

removed = call("DELETE", "/api/kgraph/entities/" + alice)[0]["removed"]
e3, _ = call("GET", "/api/kgraph/entities")
assert "Alice Chen" not in {e["name"] for e in e3["entities"]} and not [x for x in e3["edges"] if alice in (x["from"], x["to"])]
call("DELETE", "/api/kgraph/entities/" + alice, expect=404)
call("DELETE", "/api/kgraph/entities/junk", expect=404)
assert call("POST", "/api/kgraph/entities/restore", body={"removed": removed})[0]["restored"] >= 3
assert "Alice Chen" in {e["name"] for e in call("GET", "/api/kgraph/entities")[0]["entities"]}
assert call("POST", "/api/kgraph/entities/restore", body={"removed": {"parts": ["junk"]}})[0]["restored"] == 0
step("deleting an entity removes it and its lines and returns them; restore puts them back; junk is ignored or 404")

ps.trash(pa, PROMPTS)   # the source item disappears: the lines stay, marked, with the quote as written
e4, _ = call("GET", "/api/kgraph/entities")
assert [x for x in e4["edges"] if x["item"] == pa] and all(x["source_gone"] for x in e4["edges"] if x["item"] == pa) and not any(x["source_gone"] for x in e4["edges"] if x["item"] == pb)
assert all(x["quote"] == QUOTE_A for x in call("GET", "/api/kgraph/entity/" + alice)[0]["evidence"] if x["item"] == pa and x["type"] == "related") and call("GET", "/api/kgraph/entity/" + alice)[0]["evidence"][0]["source_gone"]
step("a trashed source marks its lines 'source gone' and keeps the quote as written")

# ---------- Build with a local model: nothing is sent until Start; a fake OpenAI-compatible server stands in for the runtime ----------
fake = FakeOpenAI(extra_models=["extract", "extract-bad", "extract-junk", "extract-slow"])
conn = call("POST", "/api/settings/runtimes", body={"kind": "custom", "name": "Fake runtime", "url": fake.url})[0]
RT = conn["id"]
for n in ("Dana Whitfield", "Evan Brooks"):
    ps.write_prompt(f"{n} owns the Billing Service and writes the weekly report.", time.time(), "x" + n[:2], "", "hook", PROMPTS, {"agent": "claude"})
chats = lambda: [x for x in fake.seen if x[0] == "POST"]
SC = {"kind": "source", "source": "library", "skip_covered": True}
pv, _ = call("POST", "/api/kgraph/extract/preview", body={"scope": SC, "provider": RT, "model": "extract"})
assert pv["items"] >= 17 and pv["chars"] > 0 and pv["model"] == "extract" and pv["provider"] == RT and pv["host"] == f"127.0.0.1:{fake.port}" and pv["local"] is True
assert chats() == [], "a preview sends nothing to any model"
call("POST", "/api/kgraph/extract/preview", body={"scope": SC, "provider": "rt-00000000", "model": "x"}, expect=404)
call("POST", "/api/kgraph/extract/preview", body={"scope": SC, "provider": RT, "model": ""}, expect=400)
call("POST", "/api/kgraph/extract/preview", body={"scope": {"kind": "nope"}, "provider": RT, "model": "extract"}, expect=400)
pv_default, _ = call("POST", "/api/kgraph/extract/preview", body={"scope": SC, "model": "gemma3:1b"})
assert pv_default["provider"] == "ollama" and pv_default["host"] == "127.0.0.1:11434" and pv_default["local"] is True and chats() == []
st0, _ = call("GET", "/api/kgraph/extract")
assert st0["state"] == "idle"
call("POST", "/api/kgraph/extract/stop", expect=409)
call("POST", "/api/kgraph/extract/start", body={"scope": SC, "provider": RT, "model": "extract", "expect": {"items": pv["items"] + 1, "chars": pv["chars"]}}, expect=409)
call("POST", "/api/kgraph/extract/start", body={"scope": SC, "provider": RT, "model": "extract"}, expect=409)
assert chats() == [], "nothing is sent unless Start carries the numbers the user saw"
step("preview sends nothing (Ollama is the default provider), unknown provider 404, no model or bad scope 400, Start without matching numbers is 409 and sends nothing")

started, _ = call("POST", "/api/kgraph/extract/start", body={"scope": SC, "provider": RT, "model": "extract", "expect": {"items": pv["items"], "chars": pv["chars"]}})
assert started["state"] in ("running", "done") and started["total"] == pv["items"]
for _ in range(150):
    st, _ = call("GET", "/api/kgraph/extract")
    if st["state"] not in ("running", "stopping"):
        break
    time.sleep(0.2)
assert st["state"] == "done" and st["done"] == pv["items"] and st["created"] >= 2 and st["failed"] == 0 and st["batch"], st
assert len(chats()) == pv["items"], "one request per item, only after Start"
sent = fake.last_body["messages"]
assert [m["role"] for m in sent] == ["system", "user", "user"] and sent[2]["content"].startswith("----------\n") and sent[2]["content"].endswith("\n----------")
ent, _ = call("GET", "/api/kgraph/entities")
mine = [b for b in ent["batches"] if b["id"] == st["batch"]][0]
assert mine["via"] == "local" and "local model" in mine["by"] and mine["run"] and {"Dana Whitfield", "Evan Brooks", "Billing Service"} <= {e["name"] for e in ent["entities"]} | {"Billing Service"}
assert {"Dana Whitfield", "Evan Brooks"} <= {e["name"] for e in ent["entities"]}
step("Start reads each item once with the three-message shape and writes one local batch that the entity list shows")

call("POST", "/api/kgraph/extract/start", body={"scope": SC, "provider": RT, "model": "extract-bad", "expect": {"items": 0, "chars": 0}}, expect=400)   # nothing left to read: every item is covered
pvb, _ = call("POST", "/api/kgraph/extract/preview", body={"scope": {"kind": "source", "source": "library", "skip_covered": False}, "provider": RT, "model": "extract-bad"})
n_before = len(call("GET", "/api/kgraph/entities")[0]["entities"])
call("POST", "/api/kgraph/extract/start", body={"scope": {"kind": "source", "source": "library", "skip_covered": False}, "provider": RT, "model": "extract-bad", "expect": {"items": pvb["items"], "chars": pvb["chars"]}})
for _ in range(150):
    st, _ = call("GET", "/api/kgraph/extract")
    if st["state"] not in ("running", "stopping"):
        break
    time.sleep(0.2)
assert st["state"] == "done" and st["created"] == 0 and st["refused"] > 0, st
assert len(call("GET", "/api/kgraph/entities")[0]["entities"]) == n_before
if st["batch"]:
    call("DELETE", f"/api/kgraph/batches/{st['batch']}")
step("a model that invents quotes is rejected item by item (counted); no entity is added")

slow_scope = {"kind": "source", "source": "library", "skip_covered": False}
pvs, _ = call("POST", "/api/kgraph/extract/preview", body={"scope": slow_scope, "provider": RT, "model": "extract-slow"})
call("POST", "/api/kgraph/extract/start", body={"scope": slow_scope, "provider": RT, "model": "extract-slow", "expect": {"items": pvs["items"], "chars": pvs["chars"]}})
call("POST", "/api/kgraph/extract/start", body={"scope": slow_scope, "provider": RT, "model": "extract-slow", "expect": {"items": pvs["items"], "chars": pvs["chars"]}}, expect=409)
time.sleep(0.8)
t0 = time.time()
assert call("POST", "/api/kgraph/extract/stop")[0]["state"] == "stopping"
for _ in range(100):
    st, _ = call("GET", "/api/kgraph/extract")
    if st["state"] not in ("running", "stopping"):
        break
    time.sleep(0.1)
assert st["state"] == "stopped" and time.time() - t0 < 6 and st["done"] < pvs["items"], st
if st["batch"]:
    call("DELETE", f"/api/kgraph/batches/{st['batch']}")
step("a second Start while one runs is 409; Stop ends the run within a moment")
fake.close()

# ---------------------------------------------------------------- entity kinds
kd, _ = call("GET", "/api/kgraph/kinds")
assert [k["slug"] for k in kd["kinds"]][:10] == list(kg.kinds.DEFAULT_SLUGS) and kd["limits"] == {"total": 30, "label": 24, "hint": 100}
call("PATCH", "/api/kgraph/kinds/technology", body={"label": "Tool", "light": "#112233", "dark": "#445566"})
call("PATCH", "/api/kgraph/kinds/person", body={"label": "tool"}, expect=409)
call("PATCH", "/api/kgraph/kinds/person", body={"light": "red"}, expect=400)
call("PATCH", "/api/kgraph/kinds/zzz", body={"label": "x"}, expect=404)
made, _ = call("POST", "/api/kgraph/kinds", body={"label": "Recipe", "hint": "a dish", "light": "#ff0000", "dark": "#00ff00"})
slug = made["kind"]["slug"]
assert slug.startswith("ek-") and [k["label"] for k in made["kinds"]][-1] == "Recipe"
call("POST", "/api/kgraph/kinds", body={"label": "recipe", "light": "#000000", "dark": "#ffffff"}, expect=409)
call("DELETE", "/api/kgraph/kinds/other", expect=409)
gone, _ = call("DELETE", f"/api/kgraph/kinds/{slug}")
assert [k for k in gone["kinds"] if k["slug"] == slug][0]["deleted"] is True
call("PATCH", f"/api/kgraph/kinds/{slug}", body={"label": "x"}, expect=409)
back, _ = call("POST", f"/api/kgraph/kinds/{slug}/restore")
assert not [k for k in back["kinds"] if k["slug"] == slug][0]["deleted"]
assert (PROMPTS / "kgraph" / "kinds.json").exists()
rs, _ = call("POST", "/api/kgraph/kinds/reset")
assert len(rs["kinds"]) == 10 and rs["kinds"][3]["label"] == "Technology" and not (PROMPTS / "kgraph" / "kinds.json").exists()
step("kinds: list with limits, rename and recolour, add, refusals (409 name taken or limit, 400 colour, 404), soft delete, restore, reset")

# node colours (display data): overrides only, light and dark apart, per type and per collection
c0, _ = call("GET", "/api/kgraph/colours")
assert c0 == {"types": {}, "collections": {}} and not (PROMPTS / "kgraph" / "colours.json").exists()
c1, _ = call("PATCH", "/api/kgraph/colours/types/tag", body={"light": "#AABBCC"})
assert c1["types"] == {"tag": {"light": "#aabbcc"}}
call("PATCH", "/api/kgraph/colours/types/tag", body={"dark": "red"}, expect=400)
call("PATCH", "/api/kgraph/colours/types/entity", body={"light": "#aabbcc"}, expect=404)
c2, _ = call("PATCH", "/api/kgraph/colours/collections/co-1", body={"light": "#112233", "dark": "#445566"})
assert c2["collections"]["co-1"] == {"light": "#112233", "dark": "#445566"}
call("PATCH", "/api/kgraph/colours/collections/bad%20id", body={"light": "#112233"}, expect=404)
c3, _ = call("DELETE", "/api/kgraph/colours/collections/co-1")
assert c3["collections"] == {}
c4, _ = call("DELETE", "/api/kgraph/colours/types/tag")
assert c4 == {"types": {}, "collections": {}} and not (PROMPTS / "kgraph" / "colours.json").exists()
call("PATCH", "/api/kgraph/colours/types/prompt", body={"dark": "#010203"})
c5, _ = call("POST", "/api/kgraph/colours/reset")
assert c5 == {"types": {}, "collections": {}}
step("colours: empty by default, per-type and per-collection light and dark, refusals (400 colour, 404 type or id), clear, reset")

print("\nall Lattice API checks passed")
