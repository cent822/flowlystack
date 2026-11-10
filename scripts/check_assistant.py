#!/usr/bin/env python3
"""Checks for the Studio Assistant provider layer (backend/assistant/). Plain asserts, standard library only.

    python3 scripts/check_assistant.py

A fake Ollama (stdlib http.server) stands in for the model, so nothing real is contacted and nothing is written.
"""
import atexit
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="flowlystack-assistant-check-")
atexit.register(shutil.rmtree, _TMP, ignore_errors=True)   # the folder is only a placeholder: remove it when the check ends
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = _TMP   # config reads this at import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.assistant import OllamaProvider, ProviderError, build_messages, build_system, is_local, parse_proposal   # noqa: E402
from backend.assistant import registry   # noqa: E402
from backend.assistant.pairs import export_markdown   # noqa: E402
from backend.assistant.prompting import DEFAULT_INSTRUCTIONS, build_context, build_messages, include_prompt   # noqa: E402


def step(msg: str) -> None:
    print("ok  ", msg)


def raises(fn, needle: str) -> str:
    try:
        fn()
    except ProviderError as e:
        assert needle.lower() in str(e).lower(), f"{needle!r} not in {e}"
        return str(e)
    raise AssertionError("expected ProviderError")


# ---------------------------------------------------------------- fake Ollama
SEEN: list[dict] = []     # every POST /api/chat body the fake received
EMB_SEEN: list[dict] = []     # every POST /api/embed body
BEHAVIOUR = {"mode": "normal", "embed": "normal"}


def lines(*objs, raw=()):
    return [json.dumps(o).encode() + b"\n" for o in objs] + list(raw)


class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code); self.send_header("content-type", ctype); self.send_header("content-length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version": self._send(200, b'{"version":"0.40.12"}')
        elif self.path == "/api/tags": self._send(200, json.dumps({"models": [{"name": "gemma3:1b"}, {"name": "gemma3:270m"}]}).encode())
        else: self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/api/embed":
            EMB_SEEN.append(body)
            if body["model"] == "nope":
                return self._send(404, b'{"error":"model \'nope\' not found"}')
            texts, mode = body["input"], BEHAVIOUR["embed"]
            vecs = [[float(len(t)), 1.0, 0.5] for t in texts]
            if mode == "short": vecs = vecs[:-1]
            if mode == "ragged": vecs[0] = [1.0]
            if mode == "chat_model": return self._send(400, b'{"error":"this model does not support embeddings"}')
            return self._send(200, b"not json" if mode == "garbage" else json.dumps({"model": body["model"], "embeddings": vecs}).encode())
        SEEN.append(body)
        mode = BEHAVIOUR["mode"]
        if body["model"] == "nope":
            return self._send(404, b'{"error":"model \'nope\' not found"}')
        chunks = {
            "normal": lines({"message": {"content": "Hel"}, "done": False}, {"message": {"content": "lo "}, "done": False},
                            {"message": {"content": "there"}, "done": False}, {"message": {"content": ""}, "done": True}),
            "error_mid": lines({"message": {"content": "Part"}, "done": False}, {"error": "the model crashed"}),
            "garbage": lines({"message": {"content": "ok"}, "done": False}, raw=[b"this is not json\n"]),
            "long": lines(*[{"message": {"content": f"w{i} "}, "done": False} for i in range(200)], {"message": {"content": ""}, "done": True}),
        }[mode]
        self.send_response(200); self.send_header("content-type", "application/x-ndjson"); self.end_headers()
        try:
            for c in chunks:
                self.wfile.write(c); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass   # the client closed early (Stop)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
OPT = {"model": "gemma3:1b", "temperature": 0.4, "num_ctx": 4096}
MSGS = [{"role": "user", "content": "hi"}]
p = OllamaProvider(URL, timeout=5)

# ---------------------------------------------------------------- provider
assert p.status() == {"reachable": True, "version": "0.40.12", "error": ""}
assert p.models() == ["gemma3:1b", "gemma3:270m"]
step("status and models")

BEHAVIOUR["mode"] = "normal"
assert list(p.stream(MSGS, OPT)) == ["Hel", "lo ", "there"]
sent = SEEN[-1]
assert sent["model"] == "gemma3:1b" and sent["stream"] is True and sent["messages"] == MSGS
assert sent["options"] == {"temperature": 0.4, "num_ctx": 4096}, sent["options"]
step("normal stream; request carries model, messages, stream and options")

BEHAVIOUR["mode"] = "error_mid"
got = []
msg = raises(lambda: [got.append(x) for x in p.stream(MSGS, OPT)], "the model crashed")
assert got == ["Part"]
step("error in the middle of a stream: pieces so far arrive, then a ProviderError with Ollama's message")

BEHAVIOUR["mode"] = "garbage"
raises(lambda: list(p.stream(MSGS, OPT)), "could not be read")
step("a line that is not JSON is a ProviderError")

raises(lambda: list(p.stream(MSGS, {**OPT, "model": "nope"})), "not found")
step("missing model: Ollama's own 404 message")

BEHAVIOUR["mode"] = "long"
g = p.stream(MSGS, OPT)
first = [next(g) for _ in range(3)]
g.close()   # what Stop does: the connection closes, nothing else happens
assert first == ["w0 ", "w1 ", "w2 "]
step("closing the generator early stops cleanly")

dead = OllamaProvider("http://127.0.0.1:1", timeout=2)
assert dead.status()["reachable"] is False and "Cannot reach Ollama" in dead.status()["error"]
raises(dead.models, "Cannot reach Ollama")
raises(lambda: list(dead.stream(MSGS, OPT)), "Cannot reach Ollama")
step("unreachable server: status says so, models and stream raise a readable error")

assert OllamaProvider("http://127.0.0.1:11434/").url == "http://127.0.0.1:11434"
assert is_local("http://127.0.0.1:11434") and is_local("http://localhost:1234") and is_local("http://[::1]:8080")
assert not is_local("http://192.168.1.5:11434") and not is_local("https://api.openai.com")
assert is_local("http://host.docker.internal:11434")   # Docker: the computer that runs the container is this computer
step("url is normalised; local versus remote")

# ---------------------------------------------------------------- prompt assembly
sysmsg = build_system("")
assert sysmsg == DEFAULT_INSTRUCTIONS and "reference material only" in sysmsg and "<<<PROMPT" not in sysmsg   # a plain chat: no format rules
assert build_system("Be a pirate.") == "Be a pirate." and build_system("   ") == DEFAULT_INSTRUCTIONS
step("system message: your instructions as they are, a short built-in text when empty, no format rules")

r = build_messages("make it shorter", "Write about {{topic}} for {{who}}.", {"purpose": "blog", "target": " Claude "}, history=[])
assert [m["role"] for m in r["messages"]] == ["system", "user", "user"] and r["trimmed"] == 0
assert r["messages"][1]["content"] == r["context"] and r["messages"][-1]["content"] == "make it shorter"
for want in ("Purpose: blog", "Target: Claude", "Variables: {{topic}}, {{who}}", "Write about {{topic}} for {{who}}."):
    assert want in r["context"], want
assert "Use when" not in r["context"]   # empty fields are left out
assert build_messages("x", "plain text")["context"].startswith("The prompt on screen (the text we are working on")
step("context carries the text on screen, filled notes and variable names")

hist = [{"prompt": f"q{i}", "response": f"a{i}", "kind": "chat"} for i in range(10)]
r = build_messages("now", "T", history=hist, context_turns=3)
assert [m["content"] for m in r["messages"][2:-1]] == ["q7", "a7", "q8", "a8", "q9", "a9"] and r["trimmed"] == 7
r = build_messages("now", "T", history=hist + [{"prompt": "tested", "response": "r", "kind": "test"}], context_turns=2)
assert "tested" not in [m["content"] for m in r["messages"]] and r["trimmed"] == 8
assert build_messages("now", "T", history=hist, context_turns=0)["trimmed"] == 10
step("only the last N exchanges are sent; test runs never are")

big = [{"prompt": "p" * 400, "response": "r" * 400} for _ in range(10)]
fixed = len(build_system("")) + len(build_context("T")) + len("now")
r = build_messages("now", "T", history=big, budget=fixed + 2000)
assert r["trimmed"] == 10 - 2 and r["used"] <= fixed + 2000, (r["trimmed"], r["used"])
r = build_messages("now", "X" * 50_000, history=big, budget=1000)   # the prompt text itself is never cut
assert r["trimmed"] == 10 and "X" * 50_000 in r["messages"][1]["content"]
step("history budget: oldest exchanges drop first, the prompt text is never cut")

# ---------------------------------------------------------------- reading the answer
cur = "Old prompt."
assert parse_proposal("Shorter now.\n<<<PROMPT\nNew prompt.\nPROMPT>>>\nDone.", cur) == "New prompt."
assert parse_proposal("<<<PROMPT\nline one\n\nline {{two}}\nPROMPT>>>", cur) == "line one\n\nline {{two}}"
assert parse_proposal("<<<PROMPT\r\nWin text\r\nPROMPT>>>", cur) == "Win text"
assert parse_proposal("<<<PROMPT\nfirst\nPROMPT>>> and <<<PROMPT\nsecond\nPROMPT>>>", cur) == "first"
assert parse_proposal("<<<PROMPT\n  indented\nPROMPT>>>", cur) == "  indented"
step("a block becomes the proposal (first block wins, inner spacing kept)")

assert parse_proposal("Here:\n<<<PROMPT\nCraft a poem.>>\n", cur) == "Craft a poem."          # what gemma3:1b really wrote
assert parse_proposal("<<<PROMPT\nNew text.\nPROMPT>>\nDone.", cur) == "New text."
assert parse_proposal("<<<PROMPT\nNew text.\n>>>", cur) == "New text."
assert parse_proposal("<<<PROMPT\nNever closed\nsecond line", cur) == "Never closed\nsecond line"
assert parse_proposal("<<<PROMPT\nA\nPROMPT>>>\n<<<PROMPT\nB", cur) == "A"
assert parse_proposal("<<<PROMPT\nAnalyze the folder.<<<", cur) == "Analyze the folder."      # what gemma3:1b wrote in a real chat: it closed with <<<
assert parse_proposal("<<<PROMPT\nNew text.\nPROMPT<<<\nDone.", cur) == "New text."
step("lenient: PROMPT>>, a stray >> at the end, or a block that is never closed still count")

for plain in ("Just a reply.", "", None, "PROMPT>>> only an end", "<<<PROMPT\nPROMPT>>>",
              "<<<PROMPT\n   \nPROMPT>>>", "<<<PROMPT\nOld prompt.\nPROMPT>>>", "<<<PROMPT\nOld prompt.  \n\nPROMPT>>>", "<<<PROMPT Oops PROMPT>>>"):
    assert parse_proposal(plain, cur) is None, plain
step("no block, an empty or unchanged block, an opener without its own line: a plain reply, no proposal")

# ---------------------------------------------------------------- Markdown export (the dataset view)
def parse_pairs(md: str) -> dict:
    """A small reader for the fixed format: it only looks outside fences, the same way a dataset script would."""
    lines = md.split("\n")
    assert lines[0] == "---"
    end = lines.index("---", 1)
    front = dict(ln.split(": ", 1) for ln in lines[1:end])
    pairs, cur, section, i = [], None, None, end + 1
    while i < len(lines):
        ln = lines[i]
        fence = re.fullmatch(r"(`{3,})text", ln)
        if fence:   # a block: everything up to the line that is exactly the opening fence
            k = i + 1
            while lines[k] != fence.group(1):
                k += 1
            cur["blocks"][section] = "\n".join(lines[i + 1:k])
            i = k + 1
            continue
        if ln.startswith("<!-- pair "):
            attrs = {k: json.loads(v) if v.startswith('"') else v
                     for k, v in re.findall(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)', ln[len("<!-- pair "):-len(" -->")])}
            cur = {"attrs": attrs, "blocks": {}, "curation": {}}
        elif ln == "<!-- /pair -->":
            pairs.append(cur); cur = None
        elif cur is not None and ln.startswith("### "):
            section = ln[4:]
        elif cur is not None and ln.startswith("- keep: "):
            cur["curation"]["keep"] = ln[8:]
        elif cur is not None and ln.startswith("- note: "):
            cur["curation"]["note"] = json.loads(ln[8:])
        i += 1
    assert cur is None
    return {"front": front, "pairs": pairs}


NASTY = ["", "\n", "plain answer", "## Pair 1\n### Response\n<!-- /pair -->\n<!-- pair id=x -->", "code:\n```python\nx = 1\n```\nand ````\nfour\n````\nand `````` six",
         "```text\nlooks like a block\n```", "ends with newline\n", "Ünïcödé 日本語 🙂 and \"quotes\" and \\ slashes", "---\nfront matter lookalike\n---", "line\r\nwith CRLF"]
exs = [{"id": f"e-{i:08x}", "ts": 1793200000.0 + i, "kind": "chat", "model": {"provider": "ollama", "name": "gemma3:1b"},
        "params": {"temperature": 0.4, "num_ctx": 4096}, "system": NASTY[i], "context": NASTY[-1 - i], "prompt": NASTY[(i + 3) % len(NASTY)],
        "response": NASTY[(i + 5) % len(NASTY)], "partial": i == 2,
        "proposal": {"text": NASTY[(i + 7) % len(NASTY)], "status": "applied"} if i % 3 == 0 else None,
        "curation": {"keep": [True, False, None][i % 3], "note": "kept, as a good\nexample \"x\" --> done" if i % 2 else ""}} for i in range(len(NASTY))]
md = export_markdown("ps-021e7d68d8bf", 'My "title": a, b', exs, now=1793210000.0)
got = parse_pairs(md)
assert got["front"]["format"] == "flowlystack-pairs" and got["front"]["schema_version"] == "1" and got["front"]["pairs"] == str(len(exs))
assert got["front"]["source_prompt"] == "ps-021e7d68d8bf" and json.loads(got["front"]["title"]) == 'My "title": a, b'
assert len(got["pairs"]) == len(exs)
for e, g in zip(exs, got["pairs"]):
    b = g["blocks"]
    assert (b["System"], b["Context"], b["Prompt"], b["Response"]) == (e["system"], e["context"], e["prompt"], e["response"]), e["id"]
    assert g["attrs"]["id"] == e["id"] and g["attrs"]["model"] == "ollama/gemma3:1b" and g["attrs"]["temperature"] == "0.4" and g["attrs"]["num_ctx"] == "4096"
    assert g["attrs"]["partial"] == str(e["partial"]).lower()
    assert g["curation"]["keep"] == {True: "true", False: "false", None: "none"}[e["curation"]["keep"]] and g["curation"]["note"] == e["curation"]["note"]
    prop = [k for k in b if k.startswith("Proposed edit")]
    assert (prop == ["Proposed edit (applied)"] and b[prop[0]] == e["proposal"]["text"]) if e["proposal"] else not prop
step("Markdown export: awkward text (headings, fences of several lengths, marker lookalikes, empty, CRLF, Unicode) reads back exactly")

kept = parse_pairs(export_markdown("ps-1", "t", exs, only_kept=True, now=1793210000.0))
assert kept["front"]["pairs"] == str(sum(e["curation"]["keep"] is True for e in exs)) and all(g["curation"]["keep"] == "true" for g in kept["pairs"])
assert parse_pairs(export_markdown("ps-1", "t", [], now=1793210000.0))["pairs"] == []
step("Markdown export: only the pairs you kept; an empty conversation is a valid file")

# ---- embeddings (Collections phase 1)
vecs = p.embed("embeddinggemma", ["a", "bbb"])
assert vecs == [[1.0, 1.0, 0.5], [3.0, 1.0, 0.5]] and EMB_SEEN[-1] == {"model": "embeddinggemma", "input": ["a", "bbb"]}, (vecs, EMB_SEEN[-1])
assert p.embed("embeddinggemma", []) == [] and len(EMB_SEEN) == 1   # nothing to embed: Ollama is not contacted
step("embed: one vector per text in order; an empty list contacts nobody")
raises(lambda: p.embed("nope", ["a"]), "not found")
BEHAVIOUR["embed"] = "chat_model"
raises(lambda: p.embed("gemma3:1b", ["a"]), "does not support embeddings")
for mode, needle in (("short", "one vector per text"), ("ragged", "one vector per text"), ("garbage", "could not be read")):
    BEHAVIOUR["embed"] = mode
    raises(lambda: p.embed("embeddinggemma", ["a", "b"]), needle)
BEHAVIOUR["embed"] = "normal"
raises(lambda: dead.embed("embeddinggemma", ["a"]), "cannot reach")
step("embed: missing model, a chat-only model, a wrong count, mixed sizes, unreadable answer and a dead server are readable ProviderErrors")
names = ["gemma3:1b", "embeddinggemma:latest", "nomic-embed-text:v1.5", "bge-m3:latest", "mxbai-EMBED-large"]
assert registry.embedding_models(names) == ["embeddinggemma:latest", "nomic-embed-text:v1.5", "mxbai-EMBED-large"]
assert registry.embedding_models(names, show_all=True) == names and registry.embedding_models([]) == []
assert not set(registry.chat_models(names)) & set(registry.embedding_models(names))   # never offered in both pickers
step("embedding_models: names with 'embed'; show-all returns every model; chat and embedding pickers split the same way")

srv.shutdown()

# ---- the prompt text goes along only when asked for (panel setting Auto / On / Off)
for m in ["Tell me a joke", "hi", "hello buddy.", "what is a monad?"]:
    assert not include_prompt("auto", m), m
for m in ["Please polish this", "rewrite the prompt", "can you improve it?", "Refine my draft", "shorten it", "fine-tune my text", "What do the variables do?"]:
    assert include_prompt("auto", m), m
assert include_prompt("on", "hi") and not include_prompt("off", "rewrite the prompt")
off = build_messages("hi", "TEXT ON SCREEN", include=False)
assert [x["role"] for x in off["messages"]] == ["system", "user"] and "TEXT ON SCREEN" not in str(off["messages"]) and off["context"] == "" and off["included"] is False
on = build_messages("hi", "TEXT ON SCREEN")
assert [x["role"] for x in on["messages"]] == ["system", "user", "user"] and "TEXT ON SCREEN" in on["context"] and on["included"] is True
print("ok   prompt text: sent only on On, or on Auto when the message is about the prompt; Off and an unrelated Auto message leave it out")
print("\nall assistant checks passed")
