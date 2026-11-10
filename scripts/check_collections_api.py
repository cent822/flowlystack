#!/usr/bin/env python3
"""Checks for the /api/collections routes, hybrid search, the indexing loop and the shared Trash. Plain asserts, standard library only.

Run it against a TEST server, never your real one: it creates, trashes and purges collections, documents and Studio prompts. The server
needs an empty prompts folder, its own settings folder (it changes the Ollama address and the embedding model) and Meilisearch pointed
nowhere. A fake Ollama is started by this script, so no real model is contacted.

    T=$(mktemp -d); S=$(mktemp -d)
    FLOWLYSTACK_PROMPTS_DIR=$T FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_ALIAS_DIR=$(mktemp -d) FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_PROMPTS_DIR=$T BASE=http://127.0.0.1:8799 python3 scripts/check_collections_api.py

Stop the server by the process id on port 8799 afterwards (never a broad pkill).
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
PROMPTS = Path(os.environ["FLOWLYSTACK_PROMPTS_DIR"])
A = "/api/collections"


def raw_call(method: str, path: str, data: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def call(method: str, path: str, body=None, expect: int = 200):
    code, raw = raw_call(method, path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json"})
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {raw[:300]!r}"
    return json.loads(raw) if raw else None


def upload(cid: str, name: str, data: bytes, expect: int = 200):
    from urllib.parse import quote
    code, raw = raw_call("PUT", f"{A}/{cid}/documents?name={quote(name)}", data, {"Content-Type": "application/octet-stream"})
    assert code == expect, f"upload {name}: expected {expect}, got {code}: {raw[:300]!r}"
    return json.loads(raw)


def step(msg: str) -> None:
    print("ok  ", msg)


def wait_for(pred, what, timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {what}: {call('GET', A + '/index')}")


assert not (PROMPTS / "collections").exists() or not list((PROMPTS / "collections").glob("col-*")), "the test prompts folder already has collections"


# ---------------------------------------------------------------- fake Ollama
class Fake(BaseHTTPRequestHandler):
    embeds = 0
    chats: list = []       # every POST /api/chat body the fake received
    fail_chat = False
    propose = False        # answer with a <<<PROMPT block

    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/api/version": return self._send(200, {"version": "0.40.12"})
        if self.path == "/api/tags": return self._send(200, {"models": [{"name": n} for n in ("embeddinggemma:latest", "nomic-embed-text:latest", "gemma3:1b")]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/api/chat":
            Fake.chats.append(body)
            if Fake.fail_chat: return self._send(404, {"error": "model 'nope' not found"})
            self.send_response(200); self.send_header("content-type", "application/x-ndjson"); self.end_headers()
            for piece in (("Here is a rewrite:\n<<<PROMPT\nSummarise the billing report in three bullets.\n", "PROMPT>>>") if Fake.propose else ("Billing is ", "monthly [1].")):
                self.wfile.write((json.dumps({"message": {"content": piece}, "done": False}) + "\n").encode()); self.wfile.flush()
            self.wfile.write((json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
            return
        if self.path != "/api/embed": return self._send(404, {"error": "not found"})
        Fake.embeds += len(body["input"])
        out = []
        for t in body["input"]:
            v = [0.01] * 8
            for w in re.findall(r"\w+", t.lower()):
                v[zlib.crc32(w.encode()) % 8] += 1.0
            out.append(v)
        self._send(200, {"embeddings": out})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
call("PUT", "/api/settings/connections", {"ollama": {"url": f"http://127.0.0.1:{srv.server_address[1]}"}})
call("PUT", "/api/settings/knowledge", {"embedding_model": None, "auto_index": True})

# ================================================================ setup card, My prompts
s = call("GET", A + "/setup")
assert s["steps"] == {"ollama": True, "model_installed": True, "model_chosen": False} and s["models"] == ["embeddinggemma:latest", "nomic-embed-text:latest"]
assert s["pull_command"] == "ollama pull embeddinggemma" and s["chosen"] == "" and s["ollama"]["kind"] == "local" and s["all_models"] is None
assert "gemma3:1b" in call("GET", A + "/setup?show_all=true")["all_models"]
step("setup card: Ollama reachable, embedding models found by name, the pull command, 'show all' lists everything")

lst = call("GET", A)
assert lst["items"][0]["id"] == "prompts" and lst["items"][0]["builtin"] and lst["items"][0]["name"] == "My prompts" and lst["total"] == 0
assert call("GET", A + "/prompts")["builtin"] and call("GET", A + "/prompts/documents")["builtin"]
call("DELETE", A + "/prompts", None, 400)
call("PATCH", A + "/prompts", {"description": "x"}, 400)
call("PATCH", A + "/prompts", {"tags": ["x"]}, 400)
call("PATCH", A + "/prompts", {"name": "  "}, 400)
upload("prompts", "x.md", b"# x", 400)
call("POST", A + "/prompts/documents/kd-000000000000/add-to", {"collection": "prompts"}, 400)
step("My prompts is the first row of the list and cannot be deleted, uploaded to or given a description or tags")
r = call("PATCH", A + "/prompts", {"name": "  Knowledge   base ", "star": True})
assert r["name"] == "Knowledge base" and r["star"] is True and r["builtin"]
assert call("GET", A)["items"][0]["name"] == "Knowledge base" and call("GET", A + "/prompts")["star"] is True
assert [i["id"] for i in call("GET", A + "?q=knowledge")["items"]] == ["prompts"]
call("PATCH", A + "/prompts", {"star": False})
r = call("PATCH", A + "/prompts", {"name": "My prompts"})
assert r["name"] == "My prompts" and r["star"] is False
step("My prompts can be renamed and starred (kept in builtin.json); an empty name is refused; the list, search and the single read follow")

# ================================================================ collections
call("POST", A, {"name": "   "}, 400)
c = call("POST", A, {"name": "Product docs", "description": "About the product", "tags": ["a", "b"]})
cid = c["id"]
assert cid.startswith("col-") and c["status"] == "empty" and c["documents"] == 0
assert [i["id"] for i in call("GET", A)["items"]] == ["prompts", cid] and call("GET", A)["total"] == 1
assert [i["id"] for i in call("GET", A + "?q=product")["items"]] == [cid] and [i["id"] for i in call("GET", A + "?q=my+prompts")["items"]] == ["prompts"]
assert [i["id"] for i in call("GET", A + "?tag=a")["items"]] == [cid] and call("GET", A + "?tag=zzz")["items"] == []
p = call("PATCH", f"{A}/{cid}", {"name": "Product documentation", "star": True, "tags": ["b"]})
assert p["name"] == "Product documentation" and p["star"] and p["tags"] == ["b"]
call("PATCH", f"{A}/{cid}", {"name": ""}, 400)
call("GET", f"{A}/col-000000000000", expect=404); call("PATCH", f"{A}/col-000000000000", {"name": "x"}, 404); call("DELETE", f"{A}/col-000000000000", expect=404)
call("GET", f"{A}/col-000000000000/documents", expect=404)
step("create, list, search by name and tag, edit and star a collection; unknown ids are 404, bad names 400")

# ================================================================ documents
GUIDE = ("# Install\n\n" + "To install the product run the installer and follow the wizard steps. " * 60 + "\n\n# Billing\n\n" + "Invoices are sent monthly by email to the account owner. " * 60).encode()
r = upload(cid, "guide.md", GUIDE)
doc = r["document"]
assert not r["duplicate"] and doc["type"] == "markdown" and doc["passages"] >= 2 and doc["collections"] == [cid]
row = call("GET", f"{A}/{cid}")
assert row["status"] == "waiting_model" and row["documents"] == 1   # no embedding model chosen: documents wait for one
bad = upload(cid, "scan.docx", b"PK\x03\x04")["document"]
empty = upload(cid, "empty.txt", b"")["document"]
assert bad["status"] == "failed" and "not supported" in bad["error"] and empty["status"] == "failed" and "empty" in empty["error"]
assert upload(cid, "again.md", GUIDE)["duplicate"]
docs = call("GET", f"{A}/{cid}/documents")["items"]
assert [d["name"] for d in docs] == ["empty.txt", "scan.docx", "guide.md"] and docs[-1]["status"] == "waiting"   # newest first
step("upload: a file is read into passages, unreadable files are kept as 'failed' with the reason, the same bytes are not stored twice, no model = 'waiting_model'")

# ---- keyword-only search (no model yet; Meilisearch is pointed nowhere so the scan answers)
res = call("POST", A + "/search", {"query": "invoices monthly email"})
assert res["mode"] == "keyword" and "No embedding model" in res["note"] and res["passages"][0]["ref"] == doc["id"]
top = res["passages"][0]
assert set(top) >= {"id", "ref", "n", "source", "name", "locator", "text", "score", "vector_score", "keyword_rank", "collections", "tags"}
assert top["source"] == "document" and top["name"] == "guide.md" and top["locator"] == "Billing" and top["vector_score"] is None and "Invoices" in top["text"]
assert call("POST", A + "/search", {"query": "   "}) == {"passages": [], "mode": "keyword", "note": ""}
assert call("POST", A + "/search", {"query": "invoices", "scope": ["prompts"]})["passages"] == []
assert len(call("POST", A + "/search", {"query": "the", "k": 1})["passages"]) == 1
step("search without a model is keyword-only, says so, and honours scope and k")

# ================================================================ choose the model, index in the background
st = call("PUT", "/api/settings/knowledge", {"embedding_model": "embeddinggemma:latest"})
wait_for(lambda: [d for d in call("GET", f"{A}/{cid}/documents")["items"] if d["id"] == doc["id"]][0]["status"] == "ready", "the document to be indexed")
ix = call("GET", A + "/index")
assert ix["model"] == "embeddinggemma:latest" and ix["state"] == "idle" and ix["vector_pending"] == 0 and ix["vectors"] >= 2 and ix["by_kind"]["document"] == 1
assert Fake.embeds >= 2 and call("GET", f"{A}/{cid}")["status"] == "ready" and call("GET", f"{A}/{cid}")["passages"] == doc["passages"]
step("choosing a model starts indexing by itself: the document becomes ready and the vectors are counted")

n = Fake.embeds
time.sleep(6.5)   # the loop wakes every 5 s: with nothing changed it must stay quiet
assert Fake.embeds == n
step("with nothing changed the loop embeds nothing")

# ---- My prompts: vectors by default (like documents); "Turn off auto-indexing" switches that off, "Turn on auto-indexing" on again
call("POST", A + "/index/prompts", {"enabled": False})
sp = call("POST", "/api/studio", {"text": "Summarise the quarterly billing report for the finance team", "title": "Billing summary", "tags": ["finance"]})
sid = sp["id"]
n = Fake.embeds
time.sleep(1.5)
ix = call("GET", A + "/index")
assert ix["prompts"] == {"enabled": False, "count": 1, "pending": 1} and ix["vector_pending"] == 0 and Fake.embeds == n
assert call("GET", A + "/prompts")["status"] == "keyword"
assert sid in {p["ref"] for p in call("POST", A + "/search", {"query": "quarterly billing report finance", "scope": ["prompts"]})["passages"]}
step("with indexing stopped, a new prompt is searched by keyword only: nothing is embedded and My prompts says 'keyword'")
r = call("POST", A + "/index/prompts", {"enabled": True})
assert r["prompts"]["enabled"] is True
assert json.loads((Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"]) / "index-prompts.json").read_text()) == {"enabled": True} if os.environ.get("FLOWLYSTACK_SETTINGS_DIR") else True
wait_for(lambda: call("GET", A + "/index")["by_kind"]["studio"] == 1 and call("GET", A + "/index")["vector_pending"] == 0 and call("GET", A + "/index")["state"] == "idle", "the prompt to be indexed")
assert call("GET", A + "/prompts")["prompts"] == 1 and call("GET", A + "/prompts")["status"] == "ready"
res = call("POST", A + "/search", {"query": "quarterly billing report finance"})
assert res["mode"] == "hybrid" and res["note"] == "" and res["passages"][0]["ref"] == sid and res["passages"][0]["source"] == "studio" and res["passages"][0]["name"] == "Billing summary"
assert res["passages"][0]["vector_score"] is not None and res["passages"][0]["keyword_rank"] is not None and 0 < res["passages"][0]["score"] <= 1
assert {p["ref"] for p in call("POST", A + "/search", {"query": "billing", "scope": [cid]})["passages"]} == {doc["id"]}
assert {p["ref"] for p in call("POST", A + "/search", {"query": "billing", "scope": ["prompts"]})["passages"]} == {sid}
assert {p["ref"] for p in call("POST", A + "/search", {"query": "billing", "scope": ["prompts", cid]})["passages"]} == {sid, doc["id"]}
assert [p["ref"] for p in call("POST", A + "/search", {"query": "billing", "tags": ["finance"]})["passages"]] == [sid]
assert [p["ref"] for p in call("POST", A + "/search", {"query": "billing", "source": "document"})["passages"]] == [doc["id"]] * len(call("POST", A + "/search", {"query": "billing", "source": "document"})["passages"])
step("Studio prompts join 'My prompts'; hybrid search finds them; scope, tag and source filters work")

# ================================================================ chat
def ask(cid_, **body):
    code, raw = raw_call("POST", f"{A}/{cid_}/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    assert code == 200, (code, raw[:300])
    return [json.loads(l) for l in raw.decode().splitlines() if l.strip()]


call("POST", f"{A}/{cid}/chat", {"message": "   "}, 400)
call("POST", f"{A}/col-000000000000/chat", {"message": "hi"}, 404)
ev = ask(cid, message="When are invoices sent?", model={"provider": "ollama", "name": "gemma3:1b"})
assert [e["t"] for e in ev] == ["sources", "delta", "delta", "done"], ev
src, done = ev[0], ev[-1]
assert src["searched"] and src["mode"] == "hybrid" and src["passages"][0]["ref"] == doc["id"] and src["passages"][0]["cite"] == 1 and src["passages"][0]["name"] == "guide.md"
assert "".join(e["text"] for e in ev if e["t"] == "delta") == "Billing is monthly [1]."
sent = Fake.chats[-1]["messages"]
assert sent[0]["role"] == "system" and "reference material" in sent[0]["content"] and "Invoices" not in sent[0]["content"]   # document text never reaches the system message
assert sent[1]["role"] == "user" and sent[1]["content"].startswith("Passages from my files") and "[1] guide.md · Billing" in sent[1]["content"] and "Invoices are sent monthly" in sent[1]["content"]
assert sent[-1] == {"role": "user", "content": "When are invoices sent?"} and Fake.chats[-1]["options"]["num_ctx"] == 8192
assert done["included"][0] == src["passages"][0]["id"] and done["dropped"] == 0 and done["searched"] and done["context"] == sent[1]["content"] and done["system"] == sent[0]["content"]
step("chat: the sources arrive first, the answer streams, the passages go in a separate numbered reference message, never the system message")

ev = ask(cid, message="hello!")   # small talk: Auto does not search
assert ev[0]["t"] == "sources" and not ev[0]["searched"] and ev[0]["passages"] == [] and "Passages from my files" not in json.dumps(Fake.chats[-1]["messages"])
assert Fake.chats[-1]["model"] == "gemma3:1b"   # the Assistant's default model when none is named
ev = ask(cid, message="hello!", retrieval="on")
assert ev[0]["searched"] and ev[0]["passages"]
ev = ask(cid, message="when are invoices sent?", retrieval="off")
assert not ev[0]["searched"] and "Passages from my files" not in json.dumps(Fake.chats[-1]["messages"])
step("retrieval switch: Auto skips small talk only, On always searches, Off never does")

call("PUT", "/api/settings/knowledge", {"min_relevance": 1})   # Auto leaves out every passage that only matched by meaning
ev = ask(cid, message="xqzv unrelated wording here")
assert ev[0]["searched"] and ev[0]["why"] == "question" and ev[0]["cutoff"] == 1 and ev[0]["below"] >= 1 and ev[0]["best"] is not None
assert all(p["cite"] is None and p["below"] for p in ev[0]["passages"]) and "Passages from my files" not in json.dumps(Fake.chats[-1]["messages"])
assert ev[-1]["included"] == [] and ev[-1]["below"] == ev[0]["below"]
ev = ask(cid, message="xqzv unrelated wording here", retrieval="on")   # On ignores the cutoff
assert ev[0]["cutoff"] == 0 and ev[0]["passages"] and all(p["cite"] for p in ev[0]["passages"])
call("PUT", "/api/settings/knowledge", {"min_relevance": None})
ev = ask(cid, message="xqzv unrelated wording here")
assert ev[0]["cutoff"] == 0 and ev[0]["below"] == 0 and ev[0]["passages"]
step("relevance cutoff: Auto leaves out passages below it and says why; On ignores it; 0 turns it off")

ev = ask("prompts", message="quarterly billing report", scope=["prompts", cid])
assert {p["ref"] for p in ev[0]["passages"]} == {sid, doc["id"]} and sorted(p["cite"] for p in ev[0]["passages"]) == list(range(1, len(ev[0]["passages"]) + 1))
ev = ask(cid, message="billing", scope=["prompts"])
assert {p["ref"] for p in ev[0]["passages"]} == {sid}
step("scope: a list of collections, My prompts included")

hist = [{"prompt": "earlier question", "response": "earlier answer"}]
ask(cid, message="and monthly?", history=hist, retrieval="off")
m = Fake.chats[-1]["messages"]
assert [x["role"] for x in m] == ["system", "user", "assistant", "user"] and m[1]["content"] == "earlier question" and m[2]["content"] == "earlier answer"
call("PUT", "/api/settings/knowledge", {"num_ctx": 512, "top_k": 3})
ev = ask(cid, message="installer wizard steps invoices", scope=[cid, "prompts"])
assert len(Fake.chats[-1]["messages"][1]["content"]) <= 1400 and ev[-1]["dropped"] + ev[-1]["cut"] >= 1 and Fake.chats[-1]["options"]["num_ctx"] == 512 and len(ev[0]["passages"]) <= 3
call("PUT", "/api/settings/knowledge", {"num_ctx": None, "top_k": None})
step("earlier exchanges are sent; num_ctx and passages per answer come from Settings and the request is trimmed to fit")

Fake.fail_chat = True
ev = ask(cid, message="invoices", retrieval="on")
assert ev[-1]["t"] == "error" and "not found" in ev[-1]["message"]
Fake.fail_chat = False
step("a model error comes back as an error event")


# ---- saved conversations
before = call("GET", f"{A}/{cid}/chats")
assert before["history"] and before["items"], "the asks above each saved a conversation"
n0 = len(before["items"])
ev = ask(cid, message="When are invoices sent?", retrieval="on", model={"provider": "ollama", "name": "gemma3:1b"})
chat_id = ev[0]["chat"]["id"]
assert chat_id.startswith("ch-") and ev[-1]["t"] == "done" and ev[-1]["chat"]["id"] == chat_id and ev[-1]["chat"]["title"] == "When are invoices sent?"
ch = call("GET", f"{A}/{cid}/chats/{chat_id}")
x = ch["exchanges"][0]
assert len(ch["exchanges"]) == 1 and x["prompt"] == "When are invoices sent?" and x["response"] == "Billing is monthly [1]." and not x["partial"] and x["searched"]
assert x["system"] == ev[-1]["system"] and x["context"] == ev[-1]["context"] and x["model"]["name"] == "gemma3:1b" and x["included"] == ev[-1]["included"]
assert x["retrieved"][0]["cite"] == 1 and "Invoices" in x["retrieved"][0]["text"] and x["retrieved"][0]["score"] > 0 and ch["scope"] == [cid]
ev2 = ask(cid, message="and monthly?", chat=chat_id, retrieval="off", history=[{"prompt": x["prompt"], "response": x["response"]}])
assert ev2[0]["chat"]["id"] == chat_id and len(call("GET", f"{A}/{cid}/chats/{chat_id}")["exchanges"]) == 2 and len(call("GET", f"{A}/{cid}/chats")["items"]) == n0 + 1
ev3 = ask(cid, message="invoices?", chat="ch-deadbeef", retrieval="on")   # a conversation that no longer exists starts a new one
assert ev3[0]["chat"]["id"] not in (chat_id, "ch-deadbeef") and len(call("GET", f"{A}/{cid}/chats")["items"]) == n0 + 2
step("chat: each question is saved with the exact text sent and the passages found; a follow-up joins the conversation; a missing one starts a new one")

Fake.fail_chat = True
n1 = len(call("GET", f"{A}/{cid}/chats")["items"])
ask(cid, message="invoices", retrieval="on")
assert len(call("GET", f"{A}/{cid}/chats")["items"]) == n1
Fake.fail_chat = False
step("a failed answer saves nothing and leaves no empty conversation behind")

Fake.propose = True
ev = ask(cid, message="rewrite the billing prompt", retrieval="off")
pe = ev[-1]
assert pe["t"] == "done" and pe["proposal"] == {"text": "Summarise the billing report in three bullets.", "status": "open"} and pe["exchange"].startswith("ex-")
Fake.propose = False
pch = pe["chat"]["id"]
sx = call("GET", f"{A}/{cid}/chats/{pch}")["exchanges"][0]
assert sx["proposal"]["status"] == "open" and "<<<PROMPT" in sx["response"]
assert call("PATCH", f"{A}/{cid}/chats/{pch}/exchanges/{pe['exchange']}", {"proposal_status": "dismissed"})["proposal"]["status"] == "dismissed"
call("PATCH", f"{A}/{cid}/chats/{pch}/exchanges/{pe['exchange']}", {"proposal_status": "nope"}, 422)
call("PATCH", f"{A}/{cid}/chats/{pch}/exchanges/ex-00000000", {"proposal_status": "applied"}, 404)
plain = call("GET", f"{A}/{cid}/chats/{chat_id}")["exchanges"][0]["id"]
call("PATCH", f"{A}/{cid}/chats/{chat_id}/exchanges/{plain}", {"proposal_status": "applied"}, 400)   # a plain answer has no proposal
code, md = raw_call("GET", f"{A}/{cid}/chats/{pch}/export?format=md")
assert b"### Proposed edit (dismissed)" in md and b"three bullets" in md
call("DELETE", f"{A}/{cid}/chats/{pch}")
step("a <<<PROMPT block is saved as a proposed edit (open, then dismissed or used), reported in done, kept in the export; plain answers have none")

call("PUT", "/api/settings/knowledge", {"history": False})
ev = ask(cid, message="invoices please", retrieval="on")
assert ev[0]["chat"] is None and ev[-1]["chat"] is None and len(call("GET", f"{A}/{cid}/chats")["items"]) == n0 + 2 and not call("GET", f"{A}/{cid}/chats")["history"]
call("PUT", "/api/settings/knowledge", {"history": True})
step("history off: the answer streams, nothing is stored, and the list says history is off")

assert call("PATCH", f"{A}/{cid}/chats/{chat_id}", {"title": "Billing questions"})["title"] == "Billing questions"
assert call("PATCH", f"{A}/{cid}/chats/{chat_id}", {"pinned": True})["pinned"] is True and [r["pinned"] for r in call("GET", f"{A}/{cid}/chats")["items"] if r["id"] == chat_id] == [True]
assert call("PATCH", f"{A}/{cid}/chats/{chat_id}", {"pinned": False})["pinned"] is False and call("PATCH", f"{A}/{cid}/chats/{chat_id}", {}, 400) is not None
call("PATCH", f"{A}/{cid}/chats/{chat_id}", {"title": " "}, 400); call("PATCH", f"{A}/{cid}/chats/ch-deadbeef", {"title": "x"}, 404)
code, md = raw_call("GET", f"{A}/{cid}/chats/{chat_id}/export?format=md")
assert code == 200 and b"format: flowlystack-collection-chat" in md and md.count(b"<!-- pair ") == 2 and b"[1] guide.md" in md
code, raw = raw_call("GET", f"{A}/{cid}/chats/{chat_id}/export?format=json")
assert code == 200 and json.loads(raw)["chat"]["title"] == "Billing questions" and len(json.loads(raw)["chat"]["exchanges"]) == 2
call("GET", f"{A}/{cid}/chats/{chat_id}/export?format=xml", expect=422); call("GET", f"{A}/col-000000000000/chats", expect=404); call("GET", f"{A}/{cid}/chats/ch-deadbeef", expect=404)
step("rename, Markdown and JSON export, and the 404 and 422 cases")

pc = ask("prompts", message="quarterly billing report", retrieval="on")
pid_ = pc[0]["chat"]["id"]
assert pid_ in [r["id"] for r in call("GET", f"{A}/prompts/chats")["items"]] and call("GET", f"{A}/prompts/chats/{pid_}")["exchanges"][0]["prompt"] == "quarterly billing report"
call("DELETE", f"{A}/prompts/chats/{pid_}"); call("DELETE", f"{A}/prompts/chats/{pid_}", expect=404)
assert pid_ not in [r["id"] for r in call("GET", f"{A}/prompts/chats")["items"]]
call("DELETE", f"{A}/{cid}/chats/{ev3[0]['chat']['id']}")
assert len(call("GET", f"{A}/{cid}/chats")["items"]) == n0 + 1
step("My prompts has conversations too; a conversation can be deleted")

call("PUT", f"/api/studio/{sid}/text", {"text": "Draft the onboarding checklist for new hires", "message": "rewrite"})
wait_for(lambda: call("POST", A + "/search", {"query": "onboarding checklist"})["passages"] and call("GET", A + "/index")["state"] == "idle", "the edit to be indexed")
top = call("POST", A + "/search", {"query": "onboarding checklist"})["passages"][0]
assert top["ref"] == sid and "onboarding" in top["text"] and "quarterly" not in top["text"]
step("an edited prompt is searchable by its new text")

call("DELETE", f"/api/studio/{sid}")
wait_for(lambda: call("GET", A + "/index")["by_kind"]["studio"] == 0 and sid not in {p["ref"] for p in call("POST", A + "/search", {"query": "onboarding checklist"})["passages"]}, "the trashed prompt to leave the index")
step("a trashed prompt leaves the index")

# ================================================================ membership
c2 = call("POST", A, {"name": "Second"})["id"]
call("POST", f"{A}/{cid}/documents/{doc['id']}/add-to", {"collection": c2})
call("POST", f"{A}/{cid}/documents/{doc['id']}/add-to", {"collection": "col-000000000000"}, 400)
call("POST", f"{A}/{c2}/documents/{bad['id']}/add-to", {"collection": cid}, 404)
assert sorted(call("GET", f"{A}/{c2}/documents")["items"][0]["collections"]) == sorted([cid, c2])
wait_for(lambda: {p["ref"] for p in call("POST", A + "/search", {"query": "billing", "scope": [c2]})["passages"]} == {doc["id"]}, "the document to join the second collection")
r = call("DELETE", f"{A}/{c2}/documents/{doc['id']}")
assert r == {"trashed": False, "id": doc["id"]}
call("DELETE", f"{A}/{c2}/documents/{doc['id']}", expect=404)
wait_for(lambda: call("POST", A + "/search", {"query": "billing", "scope": [c2]})["passages"] == [], "the document to leave the second collection")
assert call("POST", A + "/search", {"query": "billing", "scope": [cid]})["passages"]
step("a document can join and leave a second collection; searches follow")

# ================================================================ view and edit a document
t0 = call("GET", f"{A}/docs/{doc['id']}/text")
assert t0["editable"] and t0["text"] and t0["sha256"] == doc["sha256"] and cid in t0["collections"]
call("GET", f"{A}/docs/kd-000000000000/text", expect=404)
ps = call("GET", f"{A}/docs/{doc['id']}/passages")["items"]
assert ps and all("text" in p and "n" in p for p in ps)
call("GET", f"{A}/docs/kd-000000000000/passages", expect=404)
t1 = call("PUT", f"{A}/docs/{doc['id']}/text", {"text": t0["text"] + "\n\nA new paragraph about zeppelins and dirigibles.\n", "base_sha": t0["sha256"]})
assert t1["sha256"] != t0["sha256"] and "zeppelins" in t1["text"]
call("PUT", f"{A}/docs/{doc['id']}/text", {"text": "old copy", "base_sha": t0["sha256"]}, expect=409)
call("PUT", f"{A}/docs/kd-000000000000/text", {"text": "x", "base_sha": "x"}, expect=404)
call("PUT", f"{A}/docs/{doc['id']}/text", {"text": "x"}, expect=422)
wait_for(lambda: any(doc["id"] == p["ref"] for p in call("POST", A + "/search", {"query": "zeppelins", "scope": [cid]})["passages"]), "the edited text to be searchable")
step("view and edit: text and passages read, a save replaces the file and is searchable, a stale save is a 409, unknown ids 404")

# ================================================================ reindex, index controls
re_ = call("POST", f"{A}/docs/{doc['id']}/reindex")
assert re_["id"] == doc["id"] and re_["status"] in ("waiting", "indexing", "ready")
call("POST", f"{A}/docs/kd-000000000000/reindex", expect=404)
wait_for(lambda: call("GET", A + "/index")["state"] == "idle", "idle")
cx = call("POST", A + "/index/cancel")
assert cx["state"] == "cancelled"
call("PUT", "/api/settings/knowledge", {"auto_index": False})
res = call("POST", A + "/index/resume")
wait_for(lambda: call("GET", A + "/index")["state"] in ("idle", "off"), "resume")
step("reindex, cancel and resume answer with the index status")
call("PUT", "/api/settings/knowledge", {"auto_index": True})

# ---- a changed model is never applied silently
call("PUT", "/api/settings/knowledge", {"embedding_model": "nomic-embed-text:latest"})
ix = call("GET", A + "/index")
assert ix["state"] == "needs_rebuild" and "rebuild" in ix["error"].lower()
res = call("POST", A + "/search", {"query": "billing invoices"})
assert res["mode"] == "keyword" and "keyword" in res["note"] and res["passages"]   # keyword search still answers
call("POST", A + "/index/rebuild")
wait_for(lambda: call("GET", A + "/index")["state"] == "idle" and [d for d in call("GET", f"{A}/{cid}/documents")["items"] if d["id"] == doc["id"]][0]["status"] == "ready" and call("GET", A + "/index")["model"] == "nomic-embed-text:latest", "the rebuild")
assert call("POST", A + "/search", {"query": "billing invoices"})["mode"] == "hybrid"
step("a changed model waits for 'rebuild' (keyword search keeps working), then everything is indexed again with the new model")

# ================================================================ search status
ss = call("GET", "/api/search/status")
assert ss["indexes"]["collections"]["configured"] == "meilisearch" and ss["indexes"]["collections"]["engine"] == "scan"
call("POST", "/api/search/rebuild?index=collections", expect=503)
call("POST", "/api/search/rebuild?index=nope", expect=400)
step("search status lists the collections index (scan fallback while Meilisearch is unreachable); rebuilding it says so when the service is down")

# ================================================================ Trash
call("DELETE", f"{A}/{cid}/documents/{doc['id']}")   # its last collection: the document goes to the Trash
t = call("GET", "/api/trash")
rows = [x for x in t["items"] if x["store"] == "collections"]
assert [(x["kind"], x["title"]) for x in rows] == [("document", "guide.md")] and rows[0]["id"] == doc["id"] and rows[0]["purge_at"]
assert call("GET", "/api/trash/count")["count"] == t["count"]
d = call("GET", f"/api/trash/{doc['id']}")
assert d["store"] == "collections" and "guide.md" in d["text"]
call("POST", f"/api/trash/{doc['id']}/restore")
assert "guide.md" in [x["name"] for x in call("GET", f"{A}/{cid}/documents")["items"]]
step("a document removed from its last collection is listed in the shared Trash and Restore puts it back")

call("DELETE", f"{A}/{cid}")
t = call("GET", "/api/trash")
rows = {x["id"]: x for x in t["items"] if x["store"] == "collections"}
assert rows[cid]["kind"] == "collection" and rows[cid]["preview"] == "3 documents" and set(rows) == {cid}
call("GET", f"{A}/{cid}/chats", expect=404)   # its documents went with it and are not listed alone
call("GET", f"{A}/{cid}", expect=404)
wait_for(lambda: call("POST", A + "/search", {"query": "billing invoices"})["passages"] == [], "the trashed collection to leave the index")
call("POST", f"/api/trash/{cid}/restore")
call("POST", f"/api/trash/{cid}/restore", expect=404)
assert call("GET", f"{A}/{cid}")["documents"] == 3
assert call("GET", f"{A}/{cid}/chats/{chat_id}")["title"] == "Billing questions"   # its saved conversations came back with it
wait_for(lambda: call("POST", A + "/search", {"query": "billing invoices"})["passages"], "the restored collection to be searchable again")
step("trashing a collection hides it and its documents from lists and search; Restore brings all of it back")

call("DELETE", f"{A}/{cid}")
call("DELETE", f"/api/trash/{cid}")
call("DELETE", f"/api/trash/{cid}", expect=404)
assert not [x for x in call("GET", "/api/trash")["items"] if x["store"] == "collections"]
call("DELETE", f"{A}/{c2}")
assert call("DELETE", "/api/trash")["deleted"] >= 1 and call("GET", "/api/trash")["count"] == 0
assert not list((PROMPTS / "collections" / ".trash" / "docs").glob("kd-*")) and not list((PROMPTS / "collections" / ".trash").glob("*/col-*"))
step("purging and Empty trash remove collections and their documents for good")

srv.shutdown()
print("\nall collections API checks passed")
