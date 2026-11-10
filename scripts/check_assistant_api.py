#!/usr/bin/env python3
"""Checks for the Studio Assistant routes (/api/assistant, /api/studio/{id}/assistant and /chat). Plain asserts, stdlib only.

Run it against a TEST server with its own prompts and settings folders, never your real ones. A fake Ollama (started
here) stands in for the model; the script points the test server at it through the Settings route.

    P=$(mktemp -d); S=$(mktemp -d)
    FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$P FLOWLYSTACK_SETTINGS_DIR=$S BASE=http://127.0.0.1:8799 python3 scripts/check_assistant_api.py
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])
assert not list(PROMPTS.rglob("*.json")), "the prompts folder must start empty"
assert not (Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"]) / "settings.json").exists(), "the settings folder must start empty"


def step(msg):
    print("ok  ", msg)


# ---------------------------------------------------------------- fake Ollama (the model is chosen by name)
SEEN, STATE = [], {"closed": 0}
PROPOSAL = ["Shorter.\n", "<<<PROMPT\n", "New text for {{who}}.\n", "PROMPT>>>"]


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version": self._json(200, {"version": "9.9.9"})
        elif self.path == "/api/tags": self._json(200, {"models": [{"name": n} for n in ("gemma3:1b", "plain", "nomic-embed-text:latest")]})
        else: self._json(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        SEEN.append(body)
        name = body["model"]
        if name == "missing":
            return self._json(404, {"error": "model 'missing' not found"})
        pieces = {"proposal": PROPOSAL, "same": ["<<<PROMPT\nSAME TEXT\nPROMPT>>>"], "empty": [], "boom": ["Part ", "ial"], "slow": [f"w{i} " for i in range(100)]}.get(name, ["Hi ", "there."])
        self.send_response(200); self.send_header("content-type", "application/x-ndjson"); self.end_headers()
        try:
            for p in pieces:
                self.wfile.write(json.dumps({"message": {"content": p}, "done": False}).encode() + b"\n"); self.wfile.flush()
                if name == "slow": time.sleep(0.05)
            if name == "boom":
                self.wfile.write(b'{"error":"the model crashed"}\n')
            else:
                self.wfile.write(b'{"message":{"content":""},"done":true}\n')
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            STATE["closed"] += 1


fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=fake.serve_forever, daemon=True).start()
FAKE = f"http://127.0.0.1:{fake.server_address[1]}"


# ---------------------------------------------------------------- helpers
def call(method, path, body=None, expect=200):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, raw, ctype, disp = r.status, r.read(), r.headers.get("content-type", ""), r.headers.get("content-disposition", "")
    except urllib.error.HTTPError as e:
        code, raw, ctype, disp = e.code, e.read(), "", ""
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {raw[:300]!r}"
    return (json.loads(raw) if raw and "json" in (ctype or "json") else raw.decode()), ctype, disp


def api(method, path, body=None, expect=200):
    return call(method, path, body, expect)[0]


def send(pid, message, text="On screen text.", model="plain", expect=200, **extra):
    """POST a message and read the whole NDJSON stream; returns the list of events. The prompt text goes along (include="on") unless a test says otherwise."""
    extra.setdefault("include", "on")
    req = urllib.request.Request(f"{BASE}/api/studio/{pid}/assistant", method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"message": message, "text": text, **({"model": {"provider": "ollama", "name": model}} if model else {}), **extra}).encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            assert r.status == expect and "x-ndjson" in r.headers["content-type"]
            return [json.loads(ln) for ln in r.read().decode().splitlines() if ln.strip()]
    except urllib.error.HTTPError as e:
        assert e.code == expect, (e.code, e.read()[:200])
        return []


def chat(pid):
    return api("GET", f"/api/studio/{pid}/chat")


# ---------------------------------------------------------------- setup
api("PUT", "/api/settings/connections", {"ollama": {"url": FAKE}})
pid = api("POST", "/api/studio", {"text": "Saved prompt text for {{who}}.", "title": "Assistant test"})["id"]
api("PATCH", f"/api/studio/{pid}", {"purpose": "greeting", "target": "Claude"})

# ---------------------------------------------------------------- providers
pv = api("GET", "/api/assistant/providers")
p0 = pv["providers"][0]
assert p0["id"] == "ollama" and p0["kind"] == "local" and p0["reachable"] is True and p0["version"] == "9.9.9" and p0["configured"] is True
assert p0["models"] == ["gemma3:1b", "plain"], p0["models"]   # the embedding model is not offered
assert pv["default"] == {"provider": "ollama", "model": "gemma3:1b"} and "key" not in json.dumps(pv).lower()
step("providers: Ollama reachable with its chat models, the embedding model left out, the default from Settings")

# ---------------------------------------------------------------- a normal send
ev = send(pid, "Say hi")
assert [e["t"] for e in ev] == ["delta", "delta", "done"] and "".join(e["text"] for e in ev[:2]) == "Hi there."
ex = ev[-1]["exchange"]
assert ev[-1]["saved"] is True and ev[-1]["trimmed"] == 0 and ex["response"] == "Hi there." and ex["prompt"] == "Say hi" and ex["proposal"] is None
assert ex["model"] == {"provider": "ollama", "name": "plain"} and ex["params"] == {"temperature": 0.4, "num_ctx": 4096} and ex["partial"] is False
sent = SEEN[-1]
assert sent["model"] == "plain" and sent["stream"] is True and sent["options"] == {"temperature": 0.4, "num_ctx": 4096}
assert [m["role"] for m in sent["messages"]] == ["system", "user", "user"] and sent["messages"][-1]["content"] == "Say hi"
assert "<<<PROMPT" not in sent["messages"][0]["content"] and sent["messages"][0]["content"] == ex["system"]
assert "On screen text." in sent["messages"][1]["content"] and "Saved prompt text" not in sent["messages"][1]["content"]   # the text on screen, not the saved one
assert "Purpose: greeting" in ex["context"] and "Target: Claude" in ex["context"] and ex["context"] == sent["messages"][1]["content"]
saved = chat(pid)
assert saved["saving"] is True and [e["id"] for e in saved["exchanges"]] == [ex["id"]]
assert list(PROMPTS.rglob(f"{pid}.chat.json"))
step("send: streamed pieces, a saved exchange with the exact system and context, text on screen and saved notes sent, settings honoured")

# ---------------------------------------------------------------- the prompt text goes along only when asked for (Auto / On / Off)
ev = send(pid, "Tell me a joke", include="auto")
assert ev[-1]["included"] is False and [m["role"] for m in SEEN[-1]["messages"]][:1] == ["system"] and "On screen text." not in json.dumps(SEEN[-1]["messages"][:-1][:2]) \
    and ev[-1]["exchange"]["context"] == ""
ev = send(pid, "Please polish the prompt", include="auto")
assert ev[-1]["included"] is True and "On screen text." in SEEN[-1]["messages"][1]["content"]
ev = send(pid, "rewrite it", include="off")
assert ev[-1]["included"] is False and "On screen text." not in json.dumps(SEEN[-1]["messages"])
ev = send(pid, "hello", include="on")
assert ev[-1]["included"] is True and "On screen text." in json.dumps(SEEN[-1]["messages"])
ev = send(pid, "go on", include="auto", after_included=True)
assert ev[-1]["included"] is True and ev[-1]["why"] == "follow_up"
ev = send(pid, "go on", include="auto", after_included=False)
assert ev[-1]["included"] is False and ev[-1]["why"] == "chat"
send(pid, "x", include="sometimes", expect=422)
api("DELETE", f"/api/studio/{pid}/chat")   # the later checks expect one saved exchange, "Say hi"
send(pid, "Say hi")
step("include: Auto sends the prompt text only for a message about the prompt, Off never, On always, a bad value refused")

ev = send(pid, "And again", model=None)   # no model given: the default from Settings
assert SEEN[-1]["model"] == "gemma3:1b" and ev[-1]["exchange"]["model"]["name"] == "gemma3:1b"
h = [m["content"] for m in SEEN[-1]["messages"]]
assert h[2:] == ["Say hi", "Hi there.", "And again"], h   # the earlier exchange comes back as history
step("send: no model given uses the default; earlier exchanges are sent as history")

# ---------------------------------------------------------------- proposals
ev = send(pid, "Shorten it", model="proposal", text="Old text for {{who}}.")
ex = ev[-1]["exchange"]
assert ex["proposal"] == {"text": "New text for {{who}}.", "status": "open"} and ex["response"].startswith("Shorter.")
assert send(pid, "Same?", model="same", text="SAME TEXT")[-1]["exchange"]["proposal"] is None   # equal to the text on screen: no proposal
step("proposal: a block becomes a proposal (open); one equal to the text on screen does not")

# ---------------------------------------------------------------- settings reach the model
api("PUT", "/api/settings/assistant", {"temperature": 0.9, "num_ctx": 2048, "instructions": "Be a pirate.", "context_turns": 1})
ev = send(pid, "Ahoy")
sent = SEEN[-1]
assert sent["options"] == {"temperature": 0.9, "num_ctx": 2048} and sent["messages"][0]["content"] == "Be a pirate."
assert ev[-1]["trimmed"] >= 1 and len([m for m in sent["messages"] if m["role"] == "assistant"]) == 1   # context_turns = 1
api("PUT", "/api/settings/assistant", {"temperature": None, "num_ctx": None, "instructions": None, "context_turns": None})
step("settings: temperature, context size, instructions and context turns change what the model is sent")

# ---------------------------------------------------------------- errors leave nothing behind
n = len(chat(pid)["exchanges"])
ev = send(pid, "Break", model="boom")
assert [e["t"] for e in ev] == ["delta", "delta", "error"] and ev[-1]["message"] == "the model crashed"
ev = send(pid, "Nothing", model="empty")
assert [e["t"] for e in ev] == ["error"] and "empty" in ev[0]["message"]
ev = send(pid, "Who?", model="missing")
assert [e["t"] for e in ev] == ["error"] and "not found" in ev[0]["message"]
send(pid, "x", model="plain", meta={"purpose": "override"})
assert "Purpose: override" in SEEN[-1]["messages"][1]["content"]
n += 1   # that last one was a good send
assert len(chat(pid)["exchanges"]) == n
req = urllib.request.Request(f"{BASE}/api/studio/{pid}/assistant", method="POST", headers={"Content-Type": "application/json"},
                             data=json.dumps({"message": "x", "text": "t", "model": {"provider": "nope", "name": "m"}}).encode())
assert json.loads(urllib.request.urlopen(req).read().decode().splitlines()[0])["t"] == "error"
api("PUT", "/api/settings/connections", {"ollama": {"url": "http://127.0.0.1:1"}})
ev = send(pid, "Anyone there?")
assert [e["t"] for e in ev] == ["error"] and "Cannot reach Ollama" in ev[0]["message"] and len(chat(pid)["exchanges"]) == n
p0 = api("GET", "/api/assistant/providers")["providers"][0]
assert p0["reachable"] is False and p0["models"] == [] and "Cannot reach" in p0["error"]
api("PUT", "/api/settings/connections", {"ollama": {"url": FAKE}})
step("errors: crash mid-stream, empty answer, missing model, unknown provider and an unreachable server are error events and save nothing")

api("POST", f"/api/studio/{pid}/assistant", {"message": "  ", "text": "t"}, 400)
api("POST", f"/api/studio/{pid}/assistant", {"text": "t"}, 422)
api("POST", "/api/studio/ps-nope/assistant", {"message": "x", "text": "t"}, 404)
for path in ("/api/studio/ps-nope/chat", "/api/studio/20260101-000000-x-abc/chat"):
    api("GET", path, None, 404)
api("DELETE", "/api/studio/ps-nope/chat", None, 404)
step("requests: empty message 400, missing field 422, unknown prompt 404 (the Library's ids too)")

# ---------------------------------------------------------------- Stop
before = len(chat(pid)["exchanges"])
req = urllib.request.Request(f"{BASE}/api/studio/{pid}/assistant", method="POST", headers={"Content-Type": "application/json"},
                             data=json.dumps({"message": "Count", "text": "t", "model": {"provider": "ollama", "name": "slow"}}).encode())
r = urllib.request.urlopen(req, timeout=30)
got = [json.loads(r.readline()) for _ in range(3)]
assert all(g["t"] == "delta" for g in got)
r.close()   # what the Stop button does
for _ in range(100):
    if len(chat(pid)["exchanges"]) > before and STATE["closed"]:
        break
    time.sleep(0.1)
last = chat(pid)["exchanges"][-1]
assert len(chat(pid)["exchanges"]) == before + 1 and last["partial"] is True and last["prompt"] == "Count" and last["response"].startswith("w0 w1 ")
assert len(last["response"]) < len("".join(f"w{i} " for i in range(100))) and STATE["closed"] >= 1, "the model call should have been closed"
step("Stop: closing the connection closes the model call and keeps what arrived as a partial exchange")

# ---------------------------------------------------------------- history switches
before = len(chat(pid)["exchanges"])
api("PUT", "/api/settings/assistant", {"history": False})
assert send(pid, "Secret 2")[-1]["saved"] is False and chat(pid)["saving"] is False
api("PUT", "/api/settings/assistant", {"history": None})
assert send(pid, "Kept")[-1]["saved"] is True and len(chat(pid)["exchanges"]) == before + 1
step("history: the global switch stops saving and nothing already saved is deleted")

# ---------------------------------------------------------------- patch, export, delete, clear
ex = [e for e in chat(pid)["exchanges"] if e["proposal"]][0]
r = api("PATCH", f"/api/studio/{pid}/chat/{ex['id']}", {"proposal_status": "applied", "keep": True, "note": "good one"})
assert r["proposal"]["status"] == "applied" and r["curation"] == {"keep": True, "note": "good one"}
assert api("PATCH", f"/api/studio/{pid}/chat/{ex['id']}", {"keep": None})["curation"] == {"keep": None, "note": "good one"}
assert api("PATCH", f"/api/studio/{pid}/chat/{ex['id']}", {"note": "x"})["curation"]["keep"] is None   # keep untouched when not sent
plain = [e for e in chat(pid)["exchanges"] if not e["proposal"]][0]
api("PATCH", f"/api/studio/{pid}/chat/{plain['id']}", {"proposal_status": "dismissed"}, 400)
api("PATCH", f"/api/studio/{pid}/chat/e-nope", {"keep": True}, 404)
api("PATCH", f"/api/studio/{pid}/chat/{ex['id']}", {"proposal_status": "bogus"}, 422)
api("PATCH", f"/api/studio/{pid}/chat/{ex['id']}", {"keep": True})
step("patch: proposal status and curation change one exchange; bad requests are refused")

md, ctype, disp = call("GET", f"/api/studio/{pid}/chat/export")
assert "markdown" in ctype and "assistant-test-conversation.md" in disp and md.startswith("---\nformat: flowlystack-pairs\n")
total = len(chat(pid)["exchanges"])
assert f"pairs: {total}" in md and md.count("<!-- pair ") == total and "keep=true" in md
kept, _, _ = call("GET", f"/api/studio/{pid}/chat/export?kept=true")
assert "pairs: 1\n" in kept and kept.count("<!-- pair ") == 1
js, ctype, disp = call("GET", f"/api/studio/{pid}/chat/export?format=json")
assert js["format"] == "flowlystack-pairs" and js["source_prompt"] == pid and len(js["pairs"]) == total and "json" in ctype and disp.endswith('.json"')
call("GET", f"/api/studio/{pid}/chat/export?format=xml", None, 422)
step("export: Markdown and JSON downloads, everything or only the pairs you kept")

assert api("DELETE", f"/api/studio/{pid}/chat/{plain['id']}") == {"deleted": plain["id"]}
api("DELETE", f"/api/studio/{pid}/chat/{plain['id']}", None, 404)
assert len(chat(pid)["exchanges"]) == total - 1
assert api("DELETE", f"/api/studio/{pid}/chat")["deleted"] == total - 1 and chat(pid)["exchanges"] == [] and not list(PROMPTS.rglob(f"{pid}.chat.json"))
step("delete: one exchange, then the whole conversation (the file goes too)")

# ---------------------------------------------------------------- it follows the prompt, diff
send(pid, "Before trash")
api("DELETE", f"/api/studio/{pid}")
assert list((PROMPTS / "studio" / ".trash").glob(f"*/{pid}.chat.json"))
api("GET", f"/api/studio/{pid}/chat", None, 404)
api("POST", f"/api/trash/{pid}/restore")
assert len(chat(pid)["exchanges"]) == 1
step("trash: the conversation moves with its prompt and comes back on restore")

d = api("POST", "/api/assistant/diff", {"a": "one\ntwo\nthree", "b": "one\n2\nthree"})["rows"]
assert [r["t"] for r in d] == ["eq", "chg", "eq"] and d[1]["a"]["segs"][0][0] == "two" and d[1]["b"]["segs"][0][0] == "2"
assert all(r["t"] == "eq" for r in api("POST", "/api/assistant/diff", {"a": "same", "b": "same"})["rows"])
api("POST", "/api/assistant/diff", {"a": "x"}, 422)
step("diff: rows for two texts without saving anything")

fake.shutdown()
print("\nall assistant API checks passed")
