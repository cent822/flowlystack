#!/usr/bin/env python3
"""Checks for the /api/studio routes and the shared Trash. Plain asserts, standard library only.

Run it against a TEST server, never your real one: it creates, trashes and purges prompts.

    T=$(mktemp -d)
    FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$T BASE=http://127.0.0.1:8799 python3 scripts/check_studio_api.py

The prompts folder must be empty at the start (the script refuses to run otherwise) and must be the same one the server uses.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import promptstore   # noqa: E402  (writes one Library prompt straight to the test folder)


def call(method: str, path: str, body=None, expect: int = 200):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {raw[:200]!r}"
    return json.loads(raw) if raw else None


def step(msg: str) -> None:
    print("ok  ", msg)


assert not list(PROMPTS.glob("*/*.json")), "the test prompts folder is not empty; use a fresh one"
lib = promptstore.write_prompt("a library prompt about deploys", time.time() - 60, "sess-1", "/x/site", root=PROMPTS)

# --- empty ---
r = call("GET", "/api/studio")
assert r["total"] == 0 and r["items"] == [] and [s["name"] for s in r["statuses"]] == ["draft", "refined", "final"]
st = call("GET", "/api/search/status")
assert set(st["indexes"]) == {"prompts", "studio", "linkshell", "collections"} and st["engine"] == "substring" and st["indexes"]["studio"]["engine"] == "substring"   # the service is unreachable here: fallback
step("empty list, statuses, and search status with an `indexes` object (old keys still there)")

# --- create ---
call("POST", "/api/studio", {"text": "  "}, expect=400)
call("POST", "/api/studio", {"from_library": "nope"}, expect=404)
a = call("POST", "/api/studio", {"text": "Write a landing page for {{product}} aimed at {{audience}}", "title": "Landing page", "tags": ["web", "copy"]})
b = call("POST", "/api/studio", {"text": "Summarise this meeting: {{notes}}", "tags": ["copy"]})
c = call("POST", "/api/studio", {"from_library": lib, "title": "Deploy helper"})
assert a["id"].startswith("ps-") and a["variables"] == ["product", "audience"] and a["meta"]["status"] == "draft"
assert c["derived_from"] == {"store": "library", "id": lib} and c["meta"]["title"] == "Deploy helper" and c["text"].startswith("a library prompt")
assert call("GET", f"/api/studio/{a['id']}")["revisions"][0]["message"] == "Created"
c2 = call("POST", "/api/studio", {"from_library": lib})
assert {i["id"] for i in call("GET", f"/api/studio?derived_from={lib}")["items"]} == {c["id"], c2["id"]}
assert call("GET", "/api/studio?derived_from=nope")["items"] == []
call("DELETE", f"/api/studio/{c2['id']}"); call("DELETE", f"/api/trash/{c2['id']}")
call("GET", "/api/studio/ps-000000000000", expect=404)
step("create: plain, from a Library prompt (link back kept, title override, derived_from filter), empty text 400, unknown source 404")

# --- meta ---
m = call("PATCH", f"/api/studio/{a['id']}", {"status": "refined", "purpose": "sell it", "use_when": "new product", "target": "claude",
                                           "example": "x", "starred": True, "note": "n"})
assert m["status"] == "refined" and m["purpose"] == "sell it" and m["starred"] and m["status_at"] > 0
call("PATCH", f"/api/studio/{a['id']}", {"status": "bogus"}, expect=422)
call("PATCH", "/api/studio/ps-000000000000", {"note": "x"}, expect=404)
call("PATCH", f"/api/studio/{b['id']}", {"status": "final"})
step("meta: status and documentation fields, bad status 422, unknown id 404")

# --- versions ---
v1 = call("GET", f"/api/studio/{a['id']}")["revisions"][0]["hash"]
d = call("PUT", f"/api/studio/{a['id']}/text", {"text": "Landing page for {{product}}", "message": "Shorter"})
assert [x["message"] for x in d["revisions"]] == ["Shorter", "Created"] and d["variables"] == ["product"]
assert call("GET", f"/api/studio/{a['id']}/revisions/{v1}")["text"].startswith("Write a landing page")
df = call("GET", f"/api/studio/{a['id']}/diff?a={v1}")
assert df["rows"] and df["a"]["short"] == v1
call("DELETE", f"/api/studio/{a['id']}/revisions/{d['revisions'][0]['hash']}", expect=400)
assert len(call("DELETE", f"/api/studio/{a['id']}/revisions/{v1}")["revisions"]) == 1
call("DELETE", f"/api/studio/{a['id']}/revisions/{v1}", expect=404)
call("PUT", "/api/studio/ps-000000000000/text", {"text": "x"}, expect=404)
step("versions: save, read, diff, delete (current refused, repeat 404)")

# --- list: search, filters, counts, sort, paging ---
r = call("GET", "/api/studio?q=meeting")
assert [i["id"] for i in r["items"]] == [b["id"]] and r["items"][0]["hl"]
assert r["total"] == 3 and r["matched"] == 1
r = call("GET", "/api/studio?tag=copy")
assert {i["id"] for i in r["items"]} == {a["id"], b["id"]}
r = call("GET", "/api/studio?tag=copy&tag=web")
assert [i["id"] for i in r["items"]] == [a["id"]]
tags = {t["name"]: t["n"] for t in r["tags"]}
assert tags == {"copy": 1, "web": 1}, tags   # counts are over what is left after the filters
r = call("GET", "/api/studio?status=final")
assert [i["id"] for i in r["items"]] == [b["id"]]
assert {s["name"]: s["n"] for s in r["statuses"]} == {"draft": 1, "refined": 1, "final": 1}   # each status, on top of the other filters
assert [i["id"] for i in call("GET", "/api/studio?starred=true")["items"]] == [a["id"]]
r = call("GET", "/api/studio?sort=title&desc=false")
assert [i["meta"]["status"] for i in r["items"]] and [i["title"].lower() for i in r["items"]] == sorted(i["title"].lower() for i in r["items"])
r = call("GET", "/api/studio?page_size=2&page=2")
assert r["pages"] == 2 and len(r["items"]) == 1 and r["matched"] == 3
row = next(i for i in call("GET", "/api/studio")["items"] if i["id"] == a["id"])
assert row["variables"] == 1 and "text" not in row and row["meta"]["purpose"] == "sell it"
step("list: search with highlights, tag AND with counts, status, starred, sort, paging, slim rows")

# --- the Library never sees Studio prompts ---
lr = call("GET", "/api/prompts")
assert lr["total"] == 1 and [i["id"] for i in lr["items"]] == [lib]
assert call("GET", f"/api/prompts/{lib}")["text"].startswith("a library prompt")
call("GET", f"/api/prompts/{a['id']}", expect=404)
step("Library: still one prompt, Studio ids are not found there")

# --- one Trash for both stores ---
call("DELETE", f"/api/studio/{a['id']}")
call("DELETE", f"/api/studio/{a['id']}", expect=404)
call("DELETE", f"/api/prompts/{lib}")
t = call("GET", "/api/trash")
assert t["count"] == 2 and {(i["id"], i["store"]) for i in t["items"]} == {(a["id"], "studio"), (lib, "library")}
assert call("GET", "/api/trash/count")["count"] == 2
assert call("GET", f"/api/trash/{a['id']}")["store"] == "studio" and call("GET", f"/api/trash/{lib}")["store"] == "library"
assert call("GET", "/api/studio")["total"] == 2
call("POST", f"/api/trash/{a['id']}/restore")
assert call("GET", "/api/studio")["total"] == 3 and call("GET", f"/api/studio/{a['id']}")["meta"]["status"] == "refined"
call("DELETE", f"/api/studio/{a['id']}")
call("DELETE", f"/api/trash/{a['id']}")
call("DELETE", f"/api/trash/{a['id']}", expect=404)
call("POST", f"/api/trash/{lib}/restore")
assert call("GET", "/api/trash")["count"] == 0 and call("GET", "/api/prompts")["total"] == 1
call("DELETE", f"/api/studio/{b['id']}")
call("DELETE", f"/api/prompts/{lib}")
assert call("DELETE", "/api/trash")["deleted"] == 2 and call("GET", "/api/trash/count")["count"] == 0
step("trash: both stores listed with `store`, restore and purge look in the right root, empty clears both")

# --- search maintenance ---
for q in ("", "?index=studio", "?index=all"):   # the test server points at a service that is not there: same 503 as before
    call("POST", "/api/search/rebuild" + q, expect=503)
call("POST", "/api/search/rebuild?index=nope", expect=400)
step("search rebuild: unreachable service gives 503 for prompts, studio and all, a bad index name 400")

print("\nall Studio API checks passed")
