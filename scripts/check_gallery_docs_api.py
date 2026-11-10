#!/usr/bin/env python3
"""API checks for /api/gallery?source=documents. Plain asserts, standard library only. It needs a TEST server
with an empty temp prompts folder and its own empty settings folder, and it creates collections and documents there, so never point it at your real
one. Every variable goes on its own `env` line (zsh does not split a variable holding several), and FLOWLYSTACK_MEILI_URL must point nowhere:

    T=$(mktemp -d); S=$(mktemp -d)
    env FLOWLYSTACK_AUTH=off FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    env FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_SETTINGS_DIR=$S BASE=http://127.0.0.1:8799 python3 scripts/check_gallery_docs_api.py

Stop the server by the PID on port 8799 afterwards.
"""
from __future__ import annotations

import gzip
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])
SETTINGS = Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"])
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import promptstore as ps   # noqa: E402  (only its file writer: standard library)


def step(msg: str) -> None:
    print("ok  ", msg)


def call(method: str, path: str, body=None, raw: bytes | None = None, gzip_ok: bool = True):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Accept-Encoding": "gzip" if gzip_ok else "identity"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        out = r.read()
        enc = r.headers.get("Content-Encoding", "")
        return json.loads(gzip.decompress(out) if enc == "gzip" else out), r.headers


def status_of(method: str, path: str) -> int:
    try:
        return urllib.request.urlopen(urllib.request.Request(BASE + path, method=method), timeout=30).status
    except urllib.error.HTTPError as e:
        return e.code


def wait_docs(n: int, tries: int = 200, where=None):
    """Wait for a ready snapshot of n documents (and `where(snapshot)` true: the server looks for changes every 5 seconds)."""
    for _ in range(tries):
        d, _h = call("GET", "/api/gallery?source=documents")
        if d["status"]["state"] == "ready" and d["snapshot"] and d["snapshot"]["n"] == n and not d["status"]["stale"] and (where is None or where(d["snapshot"])):
            return d
        time.sleep(0.2)
    raise AssertionError(f"documents snapshot did not reach {n}: {d['status']}")


def wait_prompts(n: int, tries: int = 200):
    for _ in range(tries):
        d, _h = call("GET", "/api/gallery")
        if d["status"]["state"] == "ready" and d["snapshot"] and d["snapshot"]["n"] == n and not d["status"]["stale"]:
            return d
        time.sleep(0.2)
    raise AssertionError(f"prompts snapshot did not reach {n}: {d['status']}")


def upload(cid: str, name: str, data: bytes):
    return call("PUT", f"/api/collections/{cid}/documents?name={urllib.parse.quote(name)}", raw=data)[0]


assert not list(PROMPTS.glob("*/*.json")) and not (PROMPTS / "collections").exists(), "the prompts folder must be empty: use a temp folder"
d = wait_docs(0)
assert d["snapshot"]["rows"] == [] and d["snapshot"]["mode"] == "documents" and d["status"]["documents"] == 0 and d["status"]["error"] == ""
step("no documents: the Documents mode answers ready with no rows")

c0 = call("GET", "/api/gallery/counts")[0]
assert c0 == {"prompts": None, "documents": 0} or c0["documents"] == 0, c0
assert status_of("GET", "/api/gallery?source=nonsense") == 400 and status_of("POST", "/api/gallery/rebuild?source=nonsense") == 400
step("an unknown source is refused with 400 (never quietly answered with the prompts)")

stems = {
    "cooking": "recipe simmer garlic onion saucepan butter oven dough whisk season".split(),
    "travel": "flight airport luggage passport itinerary hotel museum train ticket beach".split(),
    "coding": "function python compile debug server database refactor commit endpoint array".split(),
}
topics = {t: [w + e for w in ws for e in ("", "ish", "ery", "ful")] for t, ws in stems.items()}
alpha = call("POST", "/api/collections", {"name": "Alpha"})[0]
beta = call("POST", "/api/collections", {"name": "Beta"})[0]
rnd = random.Random(3)
ids = []
for j in range(12):
    t = list(topics)[j % 3]
    md = f"# {t} notes {j}\n\n{' '.join(rnd.choices(topics[t], k=90))}\n\n- {' '.join(rnd.choices(topics[t], k=6))}\n".encode()
    ids.append(upload(alpha["id"] if j % 4 else beta["id"], f"{t}-{j}.md", md)["document"]["id"])
d = wait_docs(12)
s = d["snapshot"]
assert s["method"] in ("tfidf-svd", "embeddings") and s["clusters"] and s["tree"] and s["agents"] == ["markdown"]
assert {c["name"]: c["n"] for c in s["collections"]} == {"Alpha": 9, "Beta": 3}, s["collections"]
assert s["features"][0]["k"] == "w" and s["min_card"] == 15 and s["min_structure"] == 10 and all(r["x"] is not None for r in s["rows"])
assert d["status"]["documents"] == 12 and d["status"]["built_at"] > 0
assert s["use"] == {"history": False, "chats": 0, "exchanges": 0} and all(r["cited"] is None for r in s["rows"]) and s["nearest"] == {}   # no saved chats, no embedding model
step("documents uploaded to Collections are picked up on their own (12 rows, two collections, groups and map)")

_d, h = call("GET", "/api/gallery?source=documents")
assert h.get("Content-Encoding") == "gzip" and h.get("Cache-Control") == "no-store"
_d2, h2 = call("GET", "/api/gallery?source=documents", gzip_ok=False)
assert "Content-Encoding" not in h2 and _d2["snapshot"]["n"] == 12
step("gzip when accepted, plain JSON otherwise, never cached")

cn = call("GET", "/api/gallery/counts")[0]
assert cn["documents"] == 12 and cn["prompts"] in (None, 0), cn   # null until a prompts snapshot exists (0 once an empty one was built), and asking starts no build
step("counts for the switch: documents with text, prompts from the last prompts snapshot")

assert status_of("GET", "/api/gallery?source=documents&part=nonsense") == 400 and status_of("GET", "/api/gallery?part=passages") == 400 and status_of("GET", "/api/gallery?source=prompts&part=passages") == 400
for _ in range(100):
    pm_, _h = call("GET", "/api/gallery?source=documents&part=passages")
    if pm_["status"]["state"] != "building":
        break
    time.sleep(0.2)
assert pm_["status"]["state"] == "none" and pm_["status"]["reason"] == "no_model" and pm_["part"] is None, pm_["status"]   # the test server has no embedding model
step("the passage map: refused for other parts and for prompts; without an embedding model it answers 'none' with the reason")

up = upload(alpha["id"], "weird.xyz", b"\x00\x01 not a supported type")
assert up["document"]["status"] == "failed"
dup = upload(beta["id"], "copy.md", (PROMPTS / "collections" / "docs" / ids[1] / "file.md").read_bytes())
assert dup["duplicate"] is True
two = lambda sn: len([r for r in sn["rows"] if r["id"] == ids[1]][0]["cols"]) == 2   # noqa: E731
d = wait_docs(12, where=two)   # the duplicate joined Beta: one document, two collections
assert {r["id"] for r in d["snapshot"]["rows"]} == set(ids)
step("a failed file is not a row; the same bytes imported twice stay one document in two collections")

r, _h = call("POST", "/api/gallery/rebuild?source=documents")
assert r["status"]["state"] in ("building", "ready")
wait_docs(12)
r, _h = call("POST", "/api/gallery/rebuild?source=documents&map=full")
assert r["status"]["state"] in ("building", "ready")
assert wait_docs(12)["snapshot"]["map"]["kind"] in ("full", "none")
step("rebuild and rebuild with a full map answer at once and end ready")

extra = upload(alpha["id"], "extra.md", b"# extra\n\n" + " ".join(rnd.choices(topics["travel"], k=90)).encode())["document"]["id"]
wait_docs(13)
assert call("DELETE", f"/api/collections/{alpha['id']}/documents/{extra}")[0] is not None
d = wait_docs(12)
assert extra not in {r["id"] for r in d["snapshot"]["rows"]}
step("a new document shows up, and one removed from its last collection (Trash) leaves the Gallery")

t0 = time.time() - 40 * 3600
for i in range(14):
    ps.write_prompt(" ".join(random.Random(i).choices(sum(stems.values(), []), k=10)) + " today", t0 + i * 3600, session_id=f"s{i}", cwd="/work/demo", root=PROMPTS, extra={"agent": "claude"})
p = wait_prompts(14)
assert call("GET", "/api/gallery/counts")[0] == {"prompts": 14, "documents": 12}
assert p["snapshot"].get("mode") is None and p["status"]["prompts"] == 14
assert call("GET", "/api/gallery?source=prompts")[0]["snapshot"]["n"] == 14
assert wait_docs(12)["snapshot"]["n"] == 12
assert call("GET", "/api/gallery?source=documents")[0]["snapshot"]["rows"][0]["id"].startswith("kd-")
step("the prompts mode is unchanged and independent (default and source=prompts agree; documents still 12)")

g = SETTINGS / "gallery"
assert (g / "documents.json").is_file() and (g / "snapshot.json").is_file() and not list(g.glob("*.tmp"))
step("two separate cache files: snapshot.json (prompts) and documents.json (documents)")

print("\nall Documents Gallery API checks passed")
