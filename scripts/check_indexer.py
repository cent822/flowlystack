#!/usr/bin/env python3
"""Checks for the Collections indexer, keyword index and embedding prefixes (backend/rag/indexer.py, keyword.py, embedding.py).
Plain asserts. A fake embedding provider and a fake Meilisearch stand in for the services; everything lives in temp folders.

    .venv/bin/python scripts/check_indexer.py        # needs lancedb, so not the system python3
"""
import json
import os
import re
import sys
import tempfile
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-indexer-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused-prompts")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import collections as co   # noqa: E402
from backend import promptstore as ps   # noqa: E402
from backend.assistant.base import ProviderError   # noqa: E402
from backend.rag import embedding   # noqa: E402
from backend.rag.indexer import Indexer   # noqa: E402
from backend.rag.keyword import KeywordIndex, focus, safe_id   # noqa: E402


def step(msg: str) -> None:
    print("ok  ", msg)


# ---------------------------------------------------------------- fakes
DIMS = {"fake-a": 8, "fake-b": 12}


class FakeProvider:
    url = "http://127.0.0.1:1"

    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []
        self.fail_on_call = None      # the n-th call from now raises ProviderError
        self.hook = None              # called with (call number, texts) before answering

    def texts(self):
        return [t for _, ts in self.calls for t in ts]

    def embed(self, model, texts):
        n = len(self.calls) + 1
        if self.fail_on_call is not None and n >= self.fail_on_call:
            raise ProviderError("Cannot reach Ollama (test)")
        self.calls.append((model, list(texts)))
        if self.hook:
            self.hook(n, texts)
        d = DIMS[model]
        out = []
        for t in texts:
            v = [0.01] * d
            for w in re.findall(r"\w+", t.lower()):
                v[zlib.crc32(w.encode()) % d] += 1.0
            out.append(v)
        return out


class Meili(BaseHTTPRequestHandler):
    docs: dict = {}
    created = False
    settings: dict = {}
    down = False
    log: list = []

    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n)) if n else None

    @staticmethod
    def _ok(doc, flt):
        for part in [p for p in (flt or "").split(" AND ") if p]:
            m = re.match(r'(\w+) IN \[(.*)\]$', part)
            if m:
                if not set(json.loads("[" + m.group(2) + "]")) & set(doc.get(m.group(1), [])):
                    return False
                continue
            m = re.match(r'(\w+) = (".*")$', part)
            field, val = m.group(1), json.loads(m.group(2))
            cur = doc.get(field)
            if not (val in cur if isinstance(cur, list) else cur == val):
                return False
        return True

    def do_GET(self):
        if self.down: return self._send(500, {"message": "down"})
        p = self.path
        if p == "/indexes/collections": return self._send(200 if Meili.created else 404, {"uid": "collections"} if Meili.created else {"message": "nope", "code": "index_not_found"})
        if p.startswith("/tasks/"): return self._send(200, {"status": "succeeded"})
        if p.endswith("/settings"): return self._send(200, Meili.settings)
        if p.endswith("/stats"): return self._send(200, {"numberOfDocuments": len(Meili.docs)})
        self._send(404, {})

    def do_POST(self):
        if self.down: return self._send(500, {"message": "down"})
        body, p = self._body(), self.path
        Meili.log.append((p, body))
        if p == "/indexes": Meili.created = True; return self._send(202, {"taskUid": 1})
        if p.endswith("/documents"):
            for d in body: Meili.docs[d["id"]] = d
            return self._send(202, {"taskUid": 2})
        if p.endswith("/documents/delete"):
            for k in [k for k, d in Meili.docs.items() if self._ok(d, body["filter"])]: del Meili.docs[k]
            return self._send(202, {"taskUid": 3})
        if p.endswith("/search"):
            words = re.findall(r"\w+", body["q"].lower())
            def hay(d): return (d["title"] + " " + d["text"]).lower()
            hits = [d for d in Meili.docs.values() if self._ok(d, body.get("filter")) and all(w in hay(d) for w in words)]
            if not hits and body.get("matchingStrategy") in ("last", "frequency"):
                hits = [d for d in Meili.docs.values() if self._ok(d, body.get("filter")) and any(w in hay(d) for w in words)]
            return self._send(200, {"hits": [{k: d[k] for k in body["attributesToRetrieve"]} for d in hits[:body["limit"]]]})
        self._send(404, {})

    def do_PATCH(self):
        self._body()
        Meili.settings = {k: v for k, v in json.loads(json.dumps({})).items()}
        self._send(202, {"taskUid": 4})

    def do_DELETE(self):
        Meili.docs.clear()
        self._send(202, {"taskUid": 5})


def meili_reset():
    Meili.docs, Meili.created, Meili.settings, Meili.down, Meili.log = {}, False, {}, False, []


srv = ThreadingHTTPServer(("127.0.0.1", 0), Meili)
threading.Thread(target=srv.serve_forever, daemon=True).start()
MEILI = f"http://127.0.0.1:{srv.server_address[1]}"


# ---------------------------------------------------------------- world
def world(name, meili=MEILI, model="fake-a", auto=True, batch=16):
    base = TMP / name
    lib, studio, croot, data = base / "lib", base / "lib" / "studio", base / "collections", base / "data"
    prov = FakeProvider()
    state = {"model": model, "auto": auto}
    holder = {}
    kw = KeywordIndex(meili, None, scan=lambda: holder["ix"].iter_passages())
    ix = Indexer(data_dir=data, collections_root=croot, library_dir=lib, studio_dir=studio, provider=lambda: prov,
                 model=lambda: state["model"], auto=lambda: state["auto"], keyword=kw, batch=batch)
    holder["ix"] = ix
    return ix, prov, state, kw, (lib, studio, croot)


def big_md(topic, sections=3):
    return "\n\n".join(f"# {topic} part {i}\n\n" + (f"{topic} detail sentence {i}. " * 100) for i in range(sections)).encode()


# ================================================================ prefixes
assert embedding.passage_text("nomic-embed-text:latest", "x") == "search_document: x" and embedding.question_text("nomic-embed-text", "q") == "search_query: q"
assert embedding.passage_text("embeddinggemma-2:740m", "x").endswith("| text: x") and embedding.question_text("embeddinggemma:latest", "q").startswith("task: search result")
assert embedding.passage_text("gemma3:1b", "x") == "x" and embedding.question_text("", "q") == "q" and embedding.passage_text("nomic-embed-textual", "x") == "x"
step("embedding prefixes: nomic and EmbeddingGemma families get their task prefixes, every other model gets none")
assert safe_id("kd-ab12#3") == "kd-ab12_3" and safe_id("ps-1_x-Y") == "ps-1_x-Y"
step("passage ids are made safe for Meilisearch")

# ================================================================ first pass, no model
meili_reset()
ix, prov, state, kw, (lib, studio, croot) = world("w1", model="")
now = time.time()
p1 = ps.write_prompt("Deploy the staging server with the release script", now - 100, "s1", "/x", root=lib)
p2 = ps.write_prompt("Bake sourdough bread overnight", now - 50, "s2", "/x", root=lib)
ps.update_meta(p1, {"tags": ["ops"], "title": "Deploy"}, root=lib)
st = ps.create_studio("Write a poem about autumn leaves", "Autumn poem", ["poetry"], root=studio)
ps.update_meta(st["id"], {"purpose": "seasonal verse"}, root=studio)
col = co.create("Docs", root=croot)
guide = co.add_document(col["id"], "guide.md", big_md("Install"), croot)["document"]
bad = co.add_document(col["id"], "empty.txt", b"", croot)["document"]
want = ix.desired()
assert set(want) == {p1, p2, st["id"], guide["id"]} and bad["id"] not in want
assert want[p1]["kind"] == "library" and want[st["id"]]["kind"] == "studio" and want[guide["id"]]["collections"] == [col["id"]]
ps_ = want[st["id"]]["load"]()
assert ps_[0]["text"].startswith("Autumn poem\nTags: poetry\nPurpose: seasonal verse\n\nWrite a poem") and ps_[0]["id"] == f"{st['id']}#0" and ps_[0]["collections"] == ["prompts"]
assert want[guide["id"]]["load"]()[0]["id"] == f"{guide['id']}#0" and want[guide["id"]]["load"]()[0]["locator"].startswith("Install")
step("what should be indexed: saved prompts (title, tags, purpose, text), readable documents; failed files are left out")

r = ix.run_once()
assert r == {"keyword": 4, "vectors": 0} and prov.calls == []
s = ix.status()
assert s["state"] == "waiting_model" and s["keyword_pending"] == 0 and s["vector_pending"] == 4 and s["by_kind"] == {"document": 1, "library": 2, "studio": 1}
assert co.get_document(guide["id"], croot)["status"] == "waiting"
assert len(Meili.docs) == sum(len(i["load"]()) for i in want.values()) and kw.status()["engine"] == "meilisearch"
step("without an embedding model nothing is embedded, documents wait, and the keyword index is filled anyway")

# ================================================================ keyword search
def ids(hits): return [h["id"] for h in hits]
assert ids(kw.search("sourdough", k=5)) == [f"{p2}#0"]
assert ids(kw.search("deploy staging", collections=["prompts"])) == [f"{p1}#0"]
assert ids(kw.search("detail", collections=[col["id"]], k=50)) and all(i.startswith(guide["id"]) for i in ids(kw.search("detail", collections=[col["id"]], k=50)))
assert kw.search("detail", collections=["prompts"]) == [] and ids(kw.search("poem", tags=["poetry"])) == [f"{st['id']}#0"] and kw.search("poem", tags=["nope"]) == []
assert ids(kw.search("poem", source="studio")) == [f"{st['id']}#0"] and kw.search("poem", source="library") == []
assert ids(kw.search("bread poem staging pasta", k=10)) and kw.search("   ") == [] and kw.search("zzzz") == []
h = kw.search("sourdough")[0]
assert set(h) == {"id", "ref", "n", "rank"} and h["ref"] == p2 and h["n"] == 0 and h["rank"] == 1
step("keyword search through Meilisearch: words, collection / tag / source filters, shape of a hit, words dropped when none has them all")
assert ids(kw.search('tag "quoted" \\ back', tags=['a"b'])) == []   # quotes and backslashes cannot break the filter
assert any(isinstance(b, dict) and b.get("filter") == 'tags = "a\\"b"' for _, b in Meili.log)
step("quotes in a filter value are escaped")

# small words are taken out of a question before the keyword search; the meaning search is not touched
assert focus("how do I deploy with Docker compose") == "deploy Docker compose" and focus("where does the vector index live when running in a container") == "vector index live running container"
assert focus("don't checkpoint, after you see my response") == "checkpoint see response" and focus("I\u2019m not sure what\u2019s the ctl+Enter thing") == "sure ctl Enter thing"
assert focus("how to") == "how to" and focus("the") == "the" and focus("docker") == "docker" and focus('"deploy now" with docker') == '"deploy now" with docker'
Meili.log.clear()
assert ids(kw.search("how do I deploy staging please")) == [f"{p1}#0"]
sent = [b for pth, b in Meili.log if pth.endswith("/search")]
assert sent and sent[-1]["q"] == "deploy staging" and sent[-1]["matchingStrategy"] == "frequency", sent
step("a question loses its small words before the keyword search (and only the keyword search); quoted phrases and all-small-word queries are left alone")

Meili.down = True
fallback = kw.search("sourdough")
assert ids(fallback) == [f"{p2}#0"] and kw.status()["engine"] == "scan"
assert ids(kw.search("poem", tags=["poetry"], collections=["prompts"])) == [f"{st['id']}#0"]
assert kw.search("detail", collections=["prompts"]) == []
assert ids(kw.search("how do I find the sourdough please")) == [f"{p2}#0"]   # the scan answers a question too
Meili.down = False
kw.meili._down_until = 0   # (a failed call puts the service on hold for a few seconds; the test does not wait)
step("with Meilisearch down, the same searches are answered by scanning the passages")

none_ix, _, _, none_kw, _ = world("w1b", meili=None, model="")
ps.write_prompt("Only in the scan world", now, "s9", "/x", root=none_ix.library_dir)
assert not none_kw.configured and none_ix.run_once() == {"keyword": 0, "vectors": 0} and ids(none_kw.search("scan world")) and none_ix.status()["keyword_pending"] == 0
step("no Meilisearch configured: search scans and the indexer has no keyword work")

# ================================================================ embedding pass
state["model"] = "fake-a"
statuses = []
prov.hook = lambda n, texts: statuses.append(co.get_document(guide["id"], croot)["status"])
first_calls = len(prov.calls)
r = ix.run_once()
prov.hook = None
unique = {t for i in want.values() for t in (p["text"] for p in i["load"]())}
embedded = prov.texts()
assert r["vectors"] == 4 and len(embedded) == len(unique) + 1 and "indexing" in statuses   # +1: the vector-size probe
assert embedded[0] == "dimension probe" and all(t.startswith("") for t in embedded)
assert co.get_document(guide["id"], croot)["status"] == "ready"
s = ix.status()
assert s["state"] == "idle" and s["vector_pending"] == 0 and s["vectors"] == sum(i["count"] for i in want.values()) == ix._store.count()
step("model chosen: every source is embedded once, a document is 'indexing' while it works and 'ready' after, the vector size is probed first")

q = prov.embed("fake-a", [embedding.question_text("fake-a", "sourdough bread")])[0]
top = ix._store.query(q, 3)
assert top[0]["id"] == f"{p2}#0" and top[0]["source"] == "library" and top[0]["collections"] == ["prompts"]
assert {h["ref"] for h in ix._store.query(q, 50, {"collections": [col["id"]]})} == {guide["id"]}
assert {h["ref"] for h in ix._store.query(q, 50, {"source": "studio"})} == {st["id"]} and ix._store.query(q, 5, {"tags": ["ops"]})[0]["ref"] == p1
step("vector rows carry source, collections and tags so searches can be scoped")

n_calls = len(prov.calls)
assert not ix.due() and ix.run_once() == {"keyword": 0, "vectors": 0} and len(prov.calls) == n_calls
step("a second pass with nothing changed does nothing at all")

# ---- edits
ps.save_text(p2, "Bake rye bread with caraway seeds", "edit", root=lib)
assert ix.due()
before = len(prov.texts())
ix.run_once()
new = prov.texts()[before:]
assert len(new) == 1 and "rye bread" in new[0] and ix.status()["vector_pending"] == 0
q2 = prov.embed("fake-a", ["rye caraway"])[0]
assert ix._store.query(q2, 1)[0]["id"] == f"{p2}#0" and ids(kw.search("caraway")) == [f"{p2}#0"] and kw.search("sourdough") == []
step("an edited prompt is embedded again and replaced in both indexes; nothing else is touched")

col2 = co.create("Second", root=croot)
co.add_to(col2["id"], guide["id"], croot)
before = len(prov.texts())
ix.run_once()
assert len(prov.texts()) == before   # membership changed, text did not: no embedding
assert {h["ref"] for h in ix._store.query(q, 50, {"collections": [col2["id"]]})} == {guide["id"]}
assert ids(kw.search("detail", collections=[col2["id"]], k=3)) and co.get_document(guide["id"], croot)["status"] == "ready"
step("adding a document to another collection re-scopes it in both indexes without embedding anything")

ps.trash(p1, root=lib)
ix.run_once()
assert p1 not in {h["ref"] for h in ix._store.query(q, 100)} and kw.search("staging") == [] and p1 not in ix.copy.refs()
co.remove_from(col["id"], guide["id"], croot)
ix.run_once()
assert {h["ref"] for h in ix._store.query(q, 100, {"collections": [col["id"]]})} == set()   # still in "Second"
co.remove_from(col2["id"], guide["id"], croot)
ix.run_once()
assert guide["id"] not in {h["ref"] for h in ix._store.query(q, 100)} and guide["id"] not in ix.copy.refs() and not [d for d in Meili.docs.values() if d["ref"] == guide["id"]]
step("a trashed prompt and a document removed from its last collection leave both indexes and the bookkeeping")

# ---- a changed file under a 'ready' document
doc = co.add_document(col["id"], "notes.md", big_md("Backup", 2), croot)["document"]
ix.run_once()
assert co.get_document(doc["id"], croot)["status"] == "ready"
(croot / "docs" / doc["id"] / "file.md").write_bytes(big_md("Restore", 2))
co.read_document(doc["id"], croot)
assert co.get_document(doc["id"], croot)["status"] == "waiting"
ix.run_once()
assert co.get_document(doc["id"], croot)["status"] == "ready" and ids(kw.search("Restore", k=3)) and kw.search("Backup") == []
step("re-reading a changed file makes its passages stale and they are indexed again")

# ================================================================ failures
ix2, prov2, state2, kw2, (lib2, studio2, croot2) = world("w2", batch=2)
c2 = co.create("C", root=croot2)
d2 = co.add_document(c2["id"], "six.md", b"\n\n".join(f"# S{i}\n\n".encode() + (f"unique words for section {i} " * 90).encode() for i in range(6)), croot2)["document"]
assert d2["passages"] >= 6
total = d2["passages"]
prov2.fail_on_call = 3   # the probe is call 1, the first batch call 2, the second batch fails
ix2.run_once()
s = ix2.status()
assert s["state"] == "error" and "Cannot reach Ollama" in s["error"] and co.get_document(d2["id"], croot2)["status"] == "waiting"
assert len(prov2.texts()) == 3 and not ix2.due()   # backs off before trying again
ix2._retry_at = 0
prov2.fail_on_call = None
before = len(prov2.texts())
ix2.run_once()
assert len(prov2.texts()) - before == total - 2 and co.get_document(d2["id"], croot2)["status"] == "ready" and ix2.status()["state"] == "idle"
assert ix2._store.count() == total
step("Ollama failing half way: the document stays 'waiting', the pass backs off, and the retry embeds only what was missing")

ix3, prov3, state3, kw3, (lib3, studio3, croot3) = world("w3", batch=2)
c3 = co.create("C", root=croot3)
d3 = co.add_document(c3["id"], "six.md", b"\n\n".join(f"# S{i}\n\n".encode() + (f"other words for part {i} " * 90).encode() for i in range(6)), croot3)["document"]
prov3.hook = lambda n, texts: ix3.cancel() if n == 3 else None
ix3.run_once()
s = ix3.status()
assert s["state"] == "cancelled" and co.get_document(d3["id"], croot3)["status"] == "waiting" and not ix3.due()
assert ix3.run_once() == {"skipped": "cancelled"}
prov3.hook = None
n_before = len(prov3.texts())
ix3.resume()
ix3.run_once()
assert co.get_document(d3["id"], croot3)["status"] == "ready" and len(prov3.texts()) - n_before == d3["passages"] - 4   # two batches of two were finished before the stop
step("Cancel stops after the current batch and stays stopped; Resume finishes without repeating finished batches")

co.set_status(d3["id"], "indexing", root=croot3)
assert ix3.recover() == 1 and co.get_document(d3["id"], croot3)["status"] == "waiting"
ix3.run_once()
assert co.get_document(d3["id"], croot3)["status"] == "ready"
step("after a crash, documents left 'indexing' wait again and finish on the next pass")

ix3.auto = lambda: False
co.add_document(c3["id"], "late.md", b"# Late\n\nA late document.", croot3)
before = len(prov3.texts())
ix3.run_once()
assert len(prov3.texts()) == before and ix3.status()["state"] == "off" and not ix3.due()
ix3.run_once(force=True)
assert len(prov3.texts()) > before and ix3.status()["state"] == "idle"
step("with the auto-index switch off nothing is embedded until 'Index now' (force)")

class Boom(FakeProvider):
    def embed(self, model, texts):
        v = super().embed(model, texts)
        return [x[:3] for x in v] if len(self.calls) > 1 else v
ix4, _, _, _, (lib4, studio4, croot4) = world("w4")
boom = Boom()
ix4.provider = lambda: boom
c4 = co.create("C", root=croot4)
d4 = co.add_document(c4["id"], "x.md", b"# X\n\ntext", croot4)["document"]
ix4.run_once()
f = co.get_document(d4["id"], croot4)
assert f["status"] == "failed" and "numbers" in f["error"] and ix4.status()["failures"][0]["ref"] == d4["id"]
step("a document whose vectors have the wrong size fails with a reason instead of stopping the pass")

# ================================================================ model change
ix.run_once()
count_a = ix._store.count()
state["model"] = "fake-b"
ix.run_once()
s = ix.status()
assert s["state"] == "needs_rebuild" and s["needs_rebuild"] and "rebuild" in s["error"].lower() and not ix.due()
assert ix.copy.count("fake-a") > 0 and ix.copy.count("fake-b") <= 1   # only the size probe was embedded; the old index was not touched
state["model"] = "fake-a"
ix.run_once()
assert ix.status()["state"] == "idle" and ix._store.count() == count_a   # going back needs no rebuild
state["model"] = "fake-b"
ix.run_once()
ix.rebuild()
assert not ix.status()["needs_rebuild"] and co.get_document(doc["id"], croot)["status"] == "waiting"
prov.calls.clear()
ix.run_once()
assert co.get_document(doc["id"], croot)["status"] == "ready" and ix._store.dim == 12 and ix._store.count() == count_a and ix.status()["state"] == "idle"
assert {m for m, _ in prov.calls} == {"fake-b"}
state["model"] = "fake-a"
ix.run_once()
assert ix.status()["needs_rebuild"]
ix.rebuild()
prov.calls.clear()
ix.run_once()
assert prov.calls == [] and ix._store.dim == 8 and ix._store.count() == count_a   # every vector of the first model was still in the copy
step("a changed model is never applied silently; rebuild re-embeds with the new model, and going back to an earlier model re-embeds nothing")

# ================================================================ keyword service outage and rebuild
w5, prov5, st5, kw5, (lib5, studio5, croot5) = world("w5", model="")
a = ps.write_prompt("alpha prompt about gardens", now, "k1", "/x", root=lib5)
Meili.down = True
assert w5.run_once() == {"keyword": 0, "vectors": 0} and w5.status()["keyword_pending"] == 1
Meili.down = False
kw5.meili._down_until = 0
assert w5.run_once() == {"keyword": 1, "vectors": 0} and w5.status()["keyword_pending"] == 0 and ids(kw5.search("gardens")) == [f"{a}#0"]
Meili.docs.clear()   # the service lost its data
assert kw5.search("gardens") == [] and w5.run_once() == {"keyword": 0, "vectors": 0}
assert w5.rebuild_keyword() and w5.run_once()["keyword"] == 1 and ids(kw5.search("gardens")) == [f"{a}#0"] and kw5.count() == 1
step("a Meilisearch outage leaves the work pending and it is finished once the service is back; rebuild_keyword resends everything")

# ================================================================ prompts are opt-in for vectors; documents show their own progress
w6, prov6, st6, kw6, (lib6, studio6, croot6) = world("w6", meili=None, batch=2)
flag6 = {"on": False}
w6.prompts = lambda: flag6["on"]
now = time.time()
pa = ps.write_prompt("Water the tomato plants every morning", now - 10, "s6", "/x", root=lib6)
col6 = co.create("Notes", root=croot6)
d1 = co.add_document(col6["id"], "one.md", big_md("Alpha", 2), croot6)["document"]
d2 = co.add_document(col6["id"], "two.md", big_md("Beta", 2), croot6)["document"]
seen: list[dict] = []
prov6.hook = lambda n, texts: seen.append({k: list(v) for k, v in w6.status()["progress"]["docs"].items()})
r = w6.run_once()
assert r["vectors"] == 2 and all("Water the tomato" not in t for t in prov6.texts()), "a document import must embed only the documents"
s = w6.status()
assert s["prompts"] == {"enabled": False, "count": 1, "pending": 1} and s["vector_pending"] == 0 and s["state"] == "idle"
assert co.get_document(d1["id"], croot6)["status"] == "ready" and ps.get(pa, lib6) is not None
step("with prompt indexing off a pass embeds only the added documents, and the prompts stay out of the pending count")
assert seen and all(set(m) <= {d1["id"], d2["id"]} for m in seen) and any(m.get(d1["id"], [0, 0])[1] > 0 for m in seen)
first = [m for m in seen if m.get(d1["id"], [0, 0])[0] < m.get(d1["id"], [0, 1])[1]]
assert first, "a document's own [done, total] moves while it is embedded"
assert w6.status()["progress"]["docs_total"] == 2 and w6.status()["progress"]["docs_done"] == 2
step("each document reports its own [passages done, total] while it is embedded, and the pass counts documents separately from prompts")
flag6["on"] = True
s = w6.status()
assert s["prompts"]["enabled"] and s["vector_pending"] == 1
r = w6.run_once()
s = w6.status()
assert r["vectors"] == 1 and s["vector_pending"] == 0 and s["prompts"]["pending"] == 0 and s["progress"]["prompts_total"] == 1 and s["progress"]["prompts_done"] == 1 and s["progress"]["docs_total"] == 0
assert any("Water the tomato" in t for t in prov6.texts())
step("after the user switches prompts on, the next pass embeds them (and nothing else)")
w6.close()

ix.close(); w5.close()
srv.shutdown()
import shutil   # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("\nall indexer checks passed")
