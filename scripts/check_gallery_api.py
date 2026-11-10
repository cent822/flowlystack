#!/usr/bin/env python3
"""API checks for /api/gallery. Plain asserts, standard library only. It needs a TEST server with an empty
temp prompts folder and its own empty settings folder (the numbers below assume nothing else is in them), and it writes prompt files into that
folder, so never point it at your real one:

    T=$(mktemp -d); S=$(mktemp -d)
    FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$T BASE=http://127.0.0.1:8799 python3 scripts/check_gallery_api.py

Stop the server by the PID on port 8799 afterwards.
"""
import gzip
import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import promptstore as ps   # noqa: E402  (only its file writer: standard library)


def step(msg: str) -> None:
    print("ok  ", msg)


def call(method: str, path: str, gzip_ok: bool = True):
    req = urllib.request.Request(BASE + path, method=method, headers={"Accept-Encoding": "gzip" if gzip_ok else "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        enc = r.headers.get("Content-Encoding", "")
        return json.loads(gzip.decompress(raw) if enc == "gzip" else raw), r.headers   # headers: case-insensitive lookups


def wait_ready(n: int, tries: int = 150):
    for _ in range(tries):
        d, _h = call("GET", "/api/gallery")
        if d["status"]["state"] == "ready" and d["snapshot"] and d["snapshot"]["n"] == n and not d["status"]["stale"]:
            return d
        time.sleep(0.2)
    raise AssertionError(f"snapshot did not reach {n} prompts: {d['status']}")


assert not list(PROMPTS.glob("*/*.json")), "the prompts folder must be empty: use a temp folder"
d = wait_ready(0)
assert d["snapshot"]["rows"] == [] and d["status"]["prompts"] == 0 and d["status"]["error"] == ""
step("an empty library answers ready with no rows")

stems = "recipe simmer garlic onion flight airport hotel museum function python debug server".split()
t0 = time.time() - 40 * 3600
for i in range(14):
    ps.write_prompt(" ".join(random.Random(i).choices(stems, k=10)) + " today", t0 + i * 3600, session_id=f"s{i}", cwd="/work/demo", root=PROMPTS, extra={"agent": "claude"})
ps.create_studio("A studio prompt about hotels and flights", "Trip", ["travel"], root=PROMPTS / "studio")
d = wait_ready(14)
s = d["snapshot"]
assert s["life"]["studio"] == 1 and len(s["rows"]) == 14 and s["rows"][0]["a"] == "claude" and s["method"] in ("tfidf-svd", "embeddings")
assert d["status"]["built_at"] > 0 and d["status"]["prompts"] == 14
step("prompts written to the folder are picked up on their own (library 14, studio 1)")

_d, h = call("GET", "/api/gallery")
assert h.get("Content-Encoding") == "gzip" and h.get("Cache-Control") == "no-store"
_d2, h2 = call("GET", "/api/gallery", gzip_ok=False)
assert "Content-Encoding" not in h2 and _d2["snapshot"]["n"] == 14
step("the response is gzip when the browser accepts it and plain JSON otherwise; never cached")

r, _h = call("POST", "/api/gallery/rebuild")
assert r["status"]["state"] in ("building", "ready")
wait_ready(14)
r, _h = call("POST", "/api/gallery/rebuild?map=full")
assert r["status"]["state"] in ("building", "ready")
d = wait_ready(14)
assert d["snapshot"]["map"]["kind"] in ("full", "none")
step("rebuild and rebuild with a full map redraw answer at once and end ready")

ps.write_prompt("another hotel and flight question for the check", t0 + 99 * 3600, session_id="late", root=PROMPTS, extra={"agent": "claude"})
d = wait_ready(15)
assert d["snapshot"]["rows"][-1]["s"].startswith("another hotel")
step("a new prompt shows up after the next look (the snapshot rebuilds when the prompts change)")

print("\nall gallery API checks passed")
