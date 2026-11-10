#!/usr/bin/env python3
"""Checks for the /api/linkshell routes and the shared Trash. Plain asserts, standard library only.

Run it against a TEST server, never your real one: it creates, trashes and purges projects.

    T=$(mktemp -d)
    FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_SETTINGS_DIR=$(mktemp -d) FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$T BASE=http://127.0.0.1:8799 python3 scripts/check_linkshell_api.py

The prompts folder must have no Linkshell projects at the start (the script refuses to run otherwise) and must be the one the server uses.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])


def raw_call(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def call(method: str, path: str, body=None, expect: int = 200):
    code, raw, _ = raw_call(method, path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"})
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {raw[:200]!r}"
    return json.loads(raw) if raw else None


def step(msg: str) -> None:
    print("ok  ", msg)


assert not list((PROMPTS / "linkshell").glob("ls-*")) if (PROMPTS / "linkshell").exists() else True, "the test prompts folder already has Linkshell projects"
A = "/api/linkshell"


def settle():
    """Meilisearch indexes in the background after a write (like the Library); wait for it before asking. No-op for the substring fallback."""
    if call("GET", "/api/search/status")["indexes"]["linkshell"]["engine"] == "meilisearch":
        call("POST", "/api/search/rebuild?index=linkshell")

# --- create, list, open ---
assert call("GET", A)["total"] == 0
call("POST", A, {"name": "  "}, 400)
p = call("POST", A, {"name": "Personal website", "brief": "A one-page portfolio."})
pid = p["project"]["id"]
assert p["graph"]["rev"] == 1 and p["graph"]["blocks"][0]["type"] == "start"
start = p["graph"]["blocks"][0]["id"]
assert p["texts"][start] == "A one-page portfolio."
lst = call("GET", A)
assert lst["total"] == 1 and lst["items"][0]["id"] == pid and lst["items"][0]["brief"] == "A one-page portfolio." and lst["items"][0]["thumb"]["blocks"]
assert call("GET", f"{A}/{pid}")["project"]["name"] == "Personal website"
call("GET", f"{A}/ls-ffffffffffff", expect=404)
call("GET", f"{A}/..%2Fetc", expect=404)
step("create, list, open; blank name and unknown ids refused")

# --- patch ---
m = call("PATCH", f"{A}/{pid}", {"tags": ["web"], "star": True})
assert m["tags"] == ["web"] and m["star"] and "variables" not in m
call("PATCH", f"{A}/ls-ffffffffffff", {"star": True}, 404)
settle()
assert call("GET", f"{A}?show=starred")["total"] == 1 and call("GET", f"{A}?tag=web&tag=nope")["total"] == 0 and call("GET", f"{A}?q=portfolio")["total"] == 1
step("patch settings; list filters (star, AND tags, search)")

# --- graph autosave ---
def block(bid, typ, title, x=0, y=0, **kw):
    return {"id": bid, "type": typ, "title": title, "x": x, "y": y, "w": 190, "h": 88, "frame": "", "agent": "claude", "status": "todo", **kw}


g = copy.deepcopy(p["graph"])
g["blocks"] += [block("scaffold", "prompt", "Scaffold", 280, 80), block("hero", "prompt", "Hero", 520, 80), block("tokens", "spec", "Design tokens", 280, 200)]
g["links"] = [{"id": "l1", "from": start, "to": "scaffold", "kind": "order"}, {"id": "l2", "from": "scaffold", "to": "hero", "kind": "order"},
              {"id": "l3", "from": "tokens", "to": "scaffold", "kind": "context"}]
saved = call("PUT", f"{A}/{pid}/graph", {"graph": g, "rev": 1})["graph"]
assert saved["rev"] == 2
stale = call("PUT", f"{A}/{pid}/graph", {"graph": g, "rev": 1}, 409)
assert stale["rev"] == 2 and "another tab" in stale["detail"]
loop = copy.deepcopy(saved)
loop["links"].append({"id": "l9", "from": "hero", "to": "scaffold", "kind": "order"})
assert "loop" in call("PUT", f"{A}/{pid}/graph", {"graph": loop, "rev": 2}, 400)["detail"]
call("PUT", f"{A}/ls-ffffffffffff/graph", {"graph": g, "rev": 1}, 404)
call("PUT", f"{A}/{pid}/graph", {"graph": "nope", "rev": 2}, 422)
step("graph autosave: new rev, stale rev gives 409 with the current rev, order loop gives 400")

# --- text and versions ---
r = call("PUT", f"{A}/{pid}/blocks/scaffold/text", {"text": "Scaffold {{site}}."})
assert r["changed"] and r["version"]["message"] == "Created"
assert call("PUT", f"{A}/{pid}/blocks/scaffold/text", {"text": "Scaffold {{site}}.", "message": "same"}) == {"changed": False}
call("PUT", f"{A}/{pid}/blocks/scaffold/text", {"text": "Scaffold {{site}} in plain HTML.", "message": "More exact"})
revs = call("GET", f"{A}/{pid}/blocks/scaffold/revisions")["revisions"]
assert [v["message"] for v in revs] == ["More exact", "Created"] and revs[0]["current"]
assert call("GET", f"{A}/{pid}/blocks/scaffold/revisions/{revs[1]['id']}")["text"] == "Scaffold {{site}}."
rows = call("GET", f"{A}/{pid}/blocks/scaffold/diff?a={revs[1]['id']}")["rows"]
assert any(row["t"] in ("chg", "add", "del") for row in rows)
call("DELETE", f"{A}/{pid}/blocks/scaffold/revisions/{revs[0]['id']}", expect=400)
assert len(call("DELETE", f"{A}/{pid}/blocks/scaffold/revisions/{revs[1]['id']}")["revisions"]) == 1
call("PUT", f"{A}/{pid}/blocks/ghost/text", {"text": "x"}, 404)
call("PUT", f"{A}/{pid}/blocks/{start}/text", {"text": "A portfolio for {{site}}."})
assert call("GET", f"{A}/{pid}")["texts"]["scaffold"] == "Scaffold {{site}} in plain HTML."
step("block text: versions, no-op save, diff, current version cannot be deleted")

# --- assets ---
code, body, _ = raw_call("PUT", f"{A}/{pid}/assets?name=../Hero%20Image.png", b"\x89PNG-bytes", {"Content-Type": "application/octet-stream"})
assert code == 200
asset = json.loads(body)["asset"]
code, got, hdr = raw_call("GET", f"{A}/{pid}/assets/{asset}")
assert code == 200 and got == b"\x89PNG-bytes" and hdr.get("content-type") == "image/png" and "sandbox" in hdr.get("content-security-policy", "")
assert raw_call("GET", f"{A}/{pid}/assets/..%2Fproject.json")[0] == 404 and raw_call("GET", f"{A}/{pid}/assets/a-00000000-nope.png")[0] == 404
assert raw_call("PUT", f"{A}/ls-ffffffffffff/assets?name=x", b"x")[0] == 404
g = call("GET", f"{A}/{pid}")["graph"]
g["blocks"].append(block("shot", "reference", "Screenshot", 280, 300, asset=asset))
g["links"].append({"id": "l4", "from": "shot", "to": "scaffold", "kind": "context"})
g = call("PUT", f"{A}/{pid}/graph", {"graph": g, "rev": g["rev"]})["graph"]
step("assets: raw upload, safe name, served with a sandbox header, traversal refused")

# --- copy ---
c = call("GET", f"{A}/{pid}/blocks/scaffold/copy")
assert c["text"].startswith("Scaffold {{site}} in plain HTML.") and "## Design tokens" in c["text"] and c["references"][0].endswith(asset)
call("PUT", f"{A}/{pid}/blocks/scaffold/text", {"text": "Scaffold {{site}} using {{stack}}."})
c = call("GET", f"{A}/{pid}/blocks/scaffold/copy")
assert c["text"].startswith("Scaffold {{site}} using {{stack}}.") and "undefined" not in c   # nothing is filled, no variable list
call("POST", f"{A}/{pid}/blocks/scaffold/copy", {"values": {"site": "x"}}, expect=405)   # the fill-in route is gone
call("GET", f"{A}/{pid}/blocks/tokens/copy", expect=404)
step("copy: text pasted as written, spec and reference attached, no fill-in route")

# --- delete a block through the graph, restore ---
g2 = copy.deepcopy(g)
g2["blocks"] = [b for b in g2["blocks"] if b["id"] != "hero"]
g2["links"] = [l for l in g2["links"] if "hero" not in (l["from"], l["to"])]
g2 = call("PUT", f"{A}/{pid}/graph", {"graph": g2, "rev": g["rev"]})["graph"]
assert call("GET", f"{A}/{pid}")["removed"] == ["hero"]
back = call("POST", f"{A}/{pid}/blocks/hero/restore")["graph"]
assert "hero" in {b["id"] for b in back["blocks"]}
call("POST", f"{A}/{pid}/blocks/hero/restore", expect=404)
step("delete block via autosave, restore from .removed")

# --- to Studio ---
call("POST", f"{A}/{pid}/blocks/hero/to-studio", expect=400)   # no text yet
d = call("POST", f"{A}/{pid}/blocks/scaffold/to-studio")
assert d["id"].startswith("ps-") and d["derived_from"] == {"store": "linkshell", "id": pid, "block": "scaffold"}
call("POST", f"{A}/{pid}/blocks/{start}/to-studio", expect=400)
assert call("GET", f"/api/studio/{d['id']}")["text"] == "Scaffold {{site}} using {{stack}}."
call("DELETE", f"/api/studio/{d['id']}")
call("DELETE", f"/api/trash/{d['id']}")
step("to Studio: new Studio prompt with a plain reference back; only Prompt and Spec blocks with text")

# --- duplicate, export, import ---
dup = call("POST", A, {"duplicate_of": pid})
did = dup["project"]["id"]
assert did != pid and dup["project"]["name"] == "Personal website copy" and dup["texts"] == call("GET", f"{A}/{pid}")["texts"]
call("POST", A, {"duplicate_of": "ls-ffffffffffff"}, 404)
code, body, hdr = raw_call("GET", f"{A}/{pid}/export?format=json")
assert code == 200 and "attachment" in hdr.get("content-disposition", "")
ex = json.loads(body)
code, md, hdr = raw_call("GET", f"{A}/{pid}/export?format=md")
assert code == 200 and md.decode().startswith("# Personal website") and "### 1. Scaffold" in md.decode() and "text/markdown" in hdr["content-type"]
code, zbody, hdr = raw_call("GET", f"{A}/{pid}/export?format=zip")
assert code == 200 and hdr["content-type"] == "application/zip" and 'filename="personal-website.zip"' in hdr["content-disposition"] and zbody[:2] == b"PK"
call("GET", f"{A}/{pid}/export?format=pdf", expect=400)
imp = call("POST", f"{A}/import", ex)
assert imp["project"]["id"] not in (pid, did) and imp["texts"] == call("GET", f"{A}/{pid}")["texts"]
assert raw_call("GET", f"{A}/{imp['project']['id']}/assets/{asset}")[1] == b"\x89PNG-bytes"
call("POST", f"{A}/import", {"format": "nope"}, 400)
assert call("GET", A)["total"] == 3
step("duplicate, JSON and Markdown export, import as a new project")

# --- shared Trash ---
n0 = call("GET", "/api/trash/count")["count"]
assert call("DELETE", f"{A}/{did}")["trashed"] == did
call("DELETE", f"{A}/{did}", expect=404)
tr = call("GET", "/api/trash")
row = next(r for r in tr["items"] if r["id"] == did)
assert row["store"] == "linkshell" and row["title"] == "Personal website copy" and row["deleted_at"] > 0 and "block" in row["preview"]
assert call("GET", "/api/trash/count")["count"] == n0 + 1
assert "Restore" in call("GET", f"/api/trash/{did}")["text"]
assert call("GET", A)["total"] == 2
call("POST", f"/api/trash/{did}/restore")
assert call("GET", A)["total"] == 3 and call("GET", f"{A}/{did}")["project"]["name"] == "Personal website copy"
call("POST", f"/api/trash/{did}/restore", expect=404)
call("DELETE", f"{A}/{did}")
call("DELETE", f"/api/trash/{did}")
call("DELETE", f"/api/trash/{did}", expect=404)
call("GET", f"/api/trash/{did}", expect=404)
other = imp["project"]["id"]
call("DELETE", f"{A}/{other}")
assert call("DELETE", "/api/trash")["deleted"] >= 1
assert not any(r["store"] == "linkshell" for r in call("GET", "/api/trash")["items"])
step("shared Trash: Linkshell rows, restore, purge, empty; a restored project is back in the list")

# --- search: the `linkshell` index (Meilisearch when reachable, the substring fallback otherwise) ---
stat = call("GET", "/api/search/status")
assert "linkshell" in stat["indexes"]
live = stat["indexes"]["linkshell"]["engine"] == "meilisearch"
sp = call("POST", A, {"name": "Newsletter landing", "brief": "Signup page"})["project"]["id"]
sg = call("GET", f"{A}/{sp}")["graph"]
sg["blocks"].append(block("deploy1", "prompt", "Deployment checklist", 300, 80))
call("PUT", f"{A}/{sp}/graph", {"graph": sg, "rev": sg["rev"]})
call("PUT", f"{A}/{sp}/blocks/deploy1/text", {"text": "Run the zebra migration before release."})   # text saves reindex at once
settle()
hit = call("GET", f"{A}?q=zebra")
assert [i["id"] for i in hit["items"]] == [sp] and hit["engine"] in ("meilisearch", "substring")
assert [i["id"] for i in call("GET", f"{A}?q=newsletter")["items"]] == [sp]
assert call("GET", f"{A}?q=qqqnomatch")["total"] == 0
assert {i["id"] for i in call("GET", f"{A}?q=website")["items"]} == {pid}                       # a name matches
assert "hl" in call("GET", f"{A}?q=zebra")["items"][0] and "\ue000" in json.dumps(call("GET", f"{A}?q=zebra")["items"][0]["hl"], ensure_ascii=False) or not live
if live:   # typo tolerance and ranking are Meilisearch's; the fallback is exact
    assert [i["id"] for i in call("GET", f"{A}?q=zebre")["items"]] == [sp]
    assert call("POST", "/api/search/rebuild?index=linkshell")["indexed"] >= 2
call("POST", "/api/search/rebuild?index=nope", expect=400)
call("PATCH", f"{A}/{sp}", {"name": "Product launch page"})
settle()
assert [i["id"] for i in call("GET", f"{A}?q=launch")["items"]] == [sp] and call("GET", f"{A}?q=newsletter")["total"] == 0
call("DELETE", f"{A}/{sp}")
settle()
assert call("GET", f"{A}?q=zebra")["total"] == 0
call("DELETE", f"/api/trash/{sp}")
step(f"search ({'Meilisearch' if live else 'substring fallback'}): name, block title, block text, highlights, rename, delete; rebuild route")

# --- Studio, Library and search routes still answer ---
call("GET", "/api/studio")
call("GET", "/api/prompts")
step("Studio, Library and search routes still answer")

call("DELETE", f"{A}/{pid}")
call("DELETE", f"/api/trash/{pid}")
print("\nall Linkshell API checks passed")
