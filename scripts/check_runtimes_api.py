#!/usr/bin/env python3
"""Checks for connections to other runtimes: /api/settings/runtimes, /api/assistant/providers and a send through a connection.
Plain asserts, standard library only. A fake OpenAI-compatible server (scripts/fake_openai.py, started here) stands in for the runtime.

Run it against a TEST server with its own prompts AND settings folders (both empty), never your real ones:

    P=$(mktemp -d); S=$(mktemp -d)
    FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_SETTINGS_DIR=$S BASE=http://127.0.0.1:8799 python3 scripts/check_runtimes_api.py
"""
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_openai import FakeOpenAI   # noqa: E402

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS, SETTINGS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"]), Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"])
assert not list(PROMPTS.rglob("*.json")), "the prompts folder must start empty"
assert not (SETTINGS / "settings.json").exists(), "the settings folder must start empty"
KEY = "sk-runtime-check-SECRET-123"  # leak-ok: fake test key


def step(msg):
    print("ok  ", msg)


def api(method, path, body=None, expect=200):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {raw[:300]!r}"
    return json.loads(raw) if raw else None


def send(pid, message, provider, model):
    req = urllib.request.Request(f"{BASE}/api/studio/{pid}/assistant", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"message": message, "text": "Saved text.", "include": "on", "model": {"provider": provider, "name": model}}).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return [json.loads(ln) for ln in r.read().decode().splitlines() if ln.strip()]


fake = FakeOpenAI(key=KEY)
pid = api("POST", "/api/studio", {"text": "Saved prompt text.", "title": "Runtime test"})["id"]

# ---------------------------------------------------------------- add
a = api("POST", "/api/settings/runtimes", {"kind": "lmstudio", "name": "LM Studio", "url": fake.url, "key": KEY})
assert a["name"] == "LM Studio" and a["key"] == {"set": True, "source": "file"} and a["id"].startswith("rt-") and KEY not in json.dumps(a)
snap = api("GET", "/api/settings")
assert [r["id"] for r in snap["runtimes"]] == [a["id"]] and KEY not in json.dumps(snap)
assert KEY not in (SETTINGS / "settings.json").read_text() and stat.S_IMODE((SETTINGS / "secrets.json").stat().st_mode) == 0o600
api("POST", "/api/settings/runtimes", {"kind": "lmstudio", "name": "lm studio", "url": fake.url}, 400)
api("POST", "/api/settings/runtimes", {"kind": "nope", "name": "x", "url": fake.url}, 400)
api("PUT", "/api/settings/connections", {"runtimes": []}, 400)
step("add: id made by the server, key stored apart and never returned, duplicate name and bad kind refused")

# ---------------------------------------------------------------- providers
pv = api("GET", "/api/assistant/providers")
ids = [p["id"] for p in pv["providers"]]
assert ids == ["ollama", a["id"]], ids
p = pv["providers"][1]
assert p["label"] == "LM Studio" and p["kind"] == "local" and p["reachable"] is True and p["configured"] is True
assert p["models"] == ["ok", "err-obj", "err-text", "err-detail", "nodone", "empty", "slow"], p["models"]   # the embedding model is left out
assert KEY not in json.dumps(pv)
step("providers: the connection is listed after Ollama with its name, Local badge and chat models; no key in the answer")

# ---------------------------------------------------------------- a send through the connection
ev = send(pid, "Say hi", a["id"], "ok")
assert [e["t"] for e in ev] == ["delta", "delta", "done"] and "".join(e["text"] for e in ev[:2]) == "Hello there", ev
ex = ev[-1]["exchange"]
assert ex["model"] == {"provider": a["id"], "name": "ok"} and ex["response"] == "Hello there"
assert fake.seen[-1][2] == "Bearer " + KEY and "num_ctx" not in fake.last_body
chat = api("GET", f"/api/studio/{pid}/chat")["exchanges"]
assert len(chat) == 1 and chat[0]["model"]["provider"] == a["id"]
ev = send(pid, "Fail", a["id"], "err-obj")
assert [e["t"] for e in ev] == ["error"] and "LM Studio" in ev[0]["message"] and "not loaded" in ev[0]["message"]
ev = send(pid, "Nothing", a["id"], "empty")
assert [e["t"] for e in ev] == ["error"] and "empty" in ev[0]["message"]
assert len(api("GET", f"/api/studio/{pid}/chat")["exchanges"]) == 1   # an error leaves no exchange
step("send: streamed through the connection with the key as a header, saved with the connection id, errors name the connection")

# ---------------------------------------------------------------- the Collections chat uses the same connections
req = urllib.request.Request(f"{BASE}/api/collections/prompts/chat", method="POST", headers={"Content-Type": "application/json"},
                             data=json.dumps({"message": "Say hi", "retrieval": "off", "model": {"provider": a["id"], "name": "ok"}}).encode())
with urllib.request.urlopen(req, timeout=60) as r:
    cev = [json.loads(ln) for ln in r.read().decode().splitlines() if ln.strip()]
assert cev[-1]["t"] == "done" and "".join(e.get("text", "") for e in cev if e["t"] == "delta") == "Hello there", cev
assert cev[-1]["model"] == {"provider": a["id"], "name": "ok"} and fake.seen[-1][2] == "Bearer " + KEY
step("Collections chat: answers through the connection (retrieval off, so nothing else is contacted)")

# ---------------------------------------------------------------- no key anywhere on disk or in an export
for ext in ("md", "json"):
    req = urllib.request.Request(f"{BASE}/api/studio/{pid}/chat/export?format={ext}")
    assert KEY not in urllib.request.urlopen(req).read().decode()
for f in PROMPTS.rglob("*"):
    if f.is_file():
        assert KEY.encode() not in f.read_bytes(), f
for f in SETTINGS.iterdir():
    if f.name != "secrets.json":
        assert KEY.encode() not in f.read_bytes(), f
step("the key is in secrets.json only: not in prompt files, chat files, exports, settings.json or any answer")

# ---------------------------------------------------------------- a wrong key, then edit
b = api("POST", "/api/settings/runtimes", {"kind": "custom", "name": "Locked", "url": fake.url, "key": "wrong"})
p = [x for x in api("GET", "/api/assistant/providers")["providers"] if x["id"] == b["id"]][0]
assert p["reachable"] is False and "refused the key" in p["error"]
api("PUT", f"/api/settings/runtimes/{b['id']}", {"key": KEY})
assert [x for x in api("GET", "/api/assistant/providers")["providers"] if x["id"] == b["id"]][0]["reachable"] is True
api("PUT", f"/api/settings/runtimes/{b['id']}", {"name": "Locked 2"})
assert api("GET", "/api/settings")["runtimes"][1]["key"]["set"] is True   # a rename keeps the key
api("PUT", f"/api/settings/runtimes/{b['id']}", {"key": None})
assert api("GET", "/api/settings")["runtimes"][1]["key"]["set"] is False
api("PUT", "/api/settings/runtimes/rt-00000000", {"name": "x"}, 404)
step("edit: a wrong key shows 'refused the key', replacing it fixes it, a rename keeps it, null removes it")

# ---------------------------------------------------------------- a dead address does not slow the list
d = api("POST", "/api/settings/runtimes", {"kind": "custom", "name": "Dead", "url": "http://127.0.0.1:1/v1"})
e = api("POST", "/api/settings/runtimes", {"kind": "custom", "name": "Dead 2", "url": "http://10.255.255.1:9/v1"})   # does not answer: waits for the timeout
t0 = time.time()
pv = api("GET", "/api/assistant/providers")
took = time.time() - t0
assert took < 8, took   # in parallel: about one timeout, not one per dead address
dead = {x["id"]: x for x in pv["providers"]}
assert dead[d["id"]]["reachable"] is False and "Cannot reach Dead" in dead[d["id"]]["error"] and dead[a["id"]]["reachable"] is True
step(f"providers: dead addresses are reported without holding up the others ({took:.1f}s)")

# ---------------------------------------------------------------- remove, default reset
api("PUT", "/api/settings/assistant", {"default": {"provider": a["id"], "model": "ok"}})
r = api("DELETE", f"/api/settings/runtimes/{a['id']}")
assert r == {"removed": a["id"], "default_reset": True}
assert api("GET", "/api/settings")["sections"]["assistant"]["default"] == {"provider": "ollama", "model": "gemma3:1b"}
assert a["id"] not in json.loads((SETTINGS / "secrets.json").read_text())["keys"]
ev = send(pid, "Gone", a["id"], "ok")
assert [e["t"] for e in ev] == ["error"] and "not configured" in ev[0]["message"]
api("DELETE", f"/api/settings/runtimes/{a['id']}", expect=404)
for rid in (b["id"], d["id"], e["id"]):
    api("DELETE", f"/api/settings/runtimes/{rid}")
assert api("GET", "/api/settings")["runtimes"] == []
step("remove: key dropped, default put back, a send to the removed connection says it is not configured")

fake.close()
print("\nall runtime API checks passed")
