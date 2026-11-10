#!/usr/bin/env python3
"""Checks for Collections storage, parsers and the chunker (backend/collections.py, backend/rag/parsers.py, chunking.py).
Plain asserts, temp folder only.

    .venv/bin/python scripts/check_collections.py        # needs pypdf, so not the system python3
"""
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-collections-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "prompts")   # config reads this at import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import collections as co   # noqa: E402
from backend.rag import chunking, parsers   # noqa: E402
from backend.rag.parsers import ParseError   # noqa: E402

ROOT = TMP / "collections"


def step(msg: str) -> None:
    print("ok  ", msg)


def raises(fn, exc, needle=""):
    try:
        fn()
    except exc as e:
        assert needle.lower() in str(e).lower(), f"{needle!r} not in {e}"
        return
    raise AssertionError(f"expected {exc.__name__}")


def make_pdf(pages: list[str]) -> bytes:
    """A small valid PDF with one line of text per page ('' = a page with no text, like a scan)."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for i, text in enumerate(pages):
        page_id = 4 + 2 * i
        kids.append(f"{page_id} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode() if text else b""
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>".encode())
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


# ================================================================ chunker
para = "Sentence number one is here. " * 8   # ~230 characters
long_text = "\n\n".join(f"Paragraph {i}. " + para for i in range(40))
pieces = chunking.split_text(long_text)
assert len(pieces) > 3 and all(len(p) <= chunking.MAX for p in pieces), [len(p) for p in pieces]
assert all(len(p) > chunking.MIN for p in pieces[:-1])
for a, b in zip(pieces, pieces[1:]):   # the start of each piece repeats the tail of the previous one
    assert b[:60] in a, (a[-80:], b[:80])
step("paragraphs are packed to about the target size; each cut repeats a short tail of the previous piece")

one = "word " * 3000   # one paragraph, no blank lines
cut = chunking.split_long(one)
assert len(cut) > 4 and all(len(c) <= chunking.TARGET for c in cut) and all(c.strip() for c in cut)
assert "".join(cut).replace(" ", "").startswith("word") and cut[1][:20] in cut[0]
assert chunking.split_long("") == [] and chunking.split_text("") == [] and chunking.split_text("  \n\n  ") == []
assert chunking.split_text("short") == ["short"] and chunking.split_long("x" * 5000)[0]   # no spaces at all still terminates
step("one huge paragraph is cut at spaces with overlap; empty, short and space-free text behave")

fenced = "Intro.\n\n```python\nline one\n\nline after a blank line\n```\n\nOutro."
assert chunking.blocks(fenced) == ["Intro.", "```python\nline one\n\nline after a blank line\n```", "Outro."]
step("a fenced code block with a blank line inside stays in one piece")

small = chunking.merge_small([("a", "x" * 100), ("b", "y" * 100), ("c", "z" * 3000), ("d", "w" * 50)])
assert [loc for loc, _ in small] == ["a", "c", "d"] and len(small[0][1]) == 202   # a+b merged; c is too big to join; d stands alone
step("small neighbours merge under the first one's locator, but never past the maximum size")

# ================================================================ parsers
md = b"""Intro text before any heading.

# Install

Run the installer.

```bash
# not a heading
make install
```

## Linux

Use apt.

## Mac

Use brew.
"""
r = parsers.parse("markdown", md)
locs = [p["locator"] for p in r["passages"]]
text = "\n".join(p["text"] for p in r["passages"])
assert locs == ["Beginning"] and r["units"] == 4 and "# not a heading" in text and "## Mac" in text, locs   # four tiny sections merge into one passage
assert [p["n"] for p in r["passages"]] == list(range(len(r["passages"])))
big = b"# Big\n\n" + b"\n\n".join(f"Para {i} ".encode() + b"text " * 120 for i in range(12)) + b"\n\n# Next\n\nTiny."
r = parsers.parse("markdown", big)
assert {p["locator"] for p in r["passages"]} == {"Big", "Next"} and len([p for p in r["passages"] if p["locator"] == "Big"]) > 1
nested = parsers.parse("markdown", b"# A\n\n" + b"a " * 400 + b"\n\n## B\n\n" + b"b " * 400 + b"\n\n# C\n\n" + b"c " * 400)
assert [p["locator"] for p in nested["passages"]] == ["A", "A › B", "C"], [p["locator"] for p in nested["passages"]]
step("Markdown: heading paths as locators, a heading inside a code fence is not a heading, long sections cut, numbering is 0..n")

t = parsers.parse("text", ("Hello wörld — 你好.\n\n" * 3).encode("utf-8-sig"))
assert "wörld" in t["passages"][0]["text"] and "﻿" not in t["passages"][0]["text"]
for kind, data, why in [("text", b"", "empty"), ("text", b"   \n\n ", "no text"), ("text", b"\xff\xfe\x00\x00abc", "binary"),
                        ("text", b"caf\xe9 au lait", "UTF-8"), ("markdown", b"\n\n", "no text")]:
    raises(lambda: parsers.parse(kind, data), ParseError, why)
raises(lambda: parsers.parse("docx", b"x"), ParseError, "not supported")
step("text: UTF-8 with BOM and Unicode read; empty, blank, binary and non-UTF-8 files fail with a reason")

js = json.dumps([{"title": "A", "tags": ["x", "y"], "meta": {"n": 1, "ok": True, "none": None}, "items": [{"k": 1}, {"k": 2}]}, "plain", 7, {}, []])
r = parsers.parse("json", js.encode())
by = {p["locator"]: p["text"] for p in r["passages"]}
assert by["record 1"] == "title: A\ntags: x, y\nmeta.n: 1\nmeta.ok: true\nmeta.none: null\nitems[0].k: 1\nitems[1].k: 2", by["record 1"]
assert by["record 2"] == "plain" and by["record 3"] == "7" and "record 4" not in by and "record 5" not in by and r["units"] == 5
obj = parsers.parse("json", b'{"a": {"b": [1, 2]}}')
assert obj["passages"][0]["locator"] == "JSON" and '"b": [' in obj["passages"][0]["text"]
raises(lambda: parsers.parse("json", b"{nope"), ParseError, "not valid JSON")
raises(lambda: parsers.parse("json", b"[]"), ParseError, "no records")
step("JSON: an array is one passage per record as key: value lines; any other JSON is pretty-printed; bad JSON and [] fail")

jl = b'{"q": "one"}\n\nnot json\n{"q": "two", "a": [1, 2]}\n[1, 2]\n'
r = parsers.parse("jsonl", jl)
assert [p["locator"] for p in r["passages"]] == ["line 1", "line 4", "line 5"] and r["passages"][1]["text"] == "q: two\na: 1, 2"
assert r["warnings"] == ["1 line not valid JSON and skipped (first: line 3)"] and r["units"] == 3
raises(lambda: parsers.parse("jsonl", b"nope\nnope\n"), ParseError, "line 1")
raises(lambda: parsers.parse("jsonl", b"\n\n"), ParseError, "no records")
rec = parsers.parse("jsonl", json.dumps({"body": "word " * 2000}).encode())
assert len(rec["passages"]) > 2 and {p["locator"] for p in rec["passages"]} == {"line 1"}
step("JSONL: bad lines are skipped with a warning, all bad fails, a huge record is cut")

pdf = parsers.parse("pdf", make_pdf(["First page text", "Second page text"]))
assert pdf["units"] == 2 and "First page text" in pdf["passages"][0]["text"]
assert pdf["passages"][0]["locator"] == "p. 1–2" and "Second page text" in pdf["passages"][0]["text"]   # two tiny pages merge into one range
many = parsers.parse("pdf", make_pdf([f"Page {i} " + "filler text " * 90 for i in range(1, 6)]))
assert [p["locator"] for p in many["passages"]][0] == "p. 1" and len(many["passages"]) >= 4
step("PDF: text per page with 'p. N' locators; tiny neighbouring pages merge into 'p. N–M'")

raises(lambda: parsers.parse("pdf", make_pdf(["", ""])), ParseError, "scanned")
raises(lambda: parsers.parse("pdf", b"%PDF-1.4 this is not really a pdf"), ParseError, "could not be read")
raises(lambda: parsers.parse("pdf", b"hello"), ParseError, "could not be read")
from pypdf import PdfReader, PdfWriter   # noqa: E402
w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["Secret"]))))
w.encrypt("hunter2", algorithm="RC4-128")
buf = io.BytesIO(); w.write(buf)
raises(lambda: parsers.parse("pdf", buf.getvalue()), ParseError, "password")
w = PdfWriter(clone_from=PdfReader(io.BytesIO(make_pdf(["Open to everyone"]))))
w.encrypt("", owner_password="owner", algorithm="RC4-128")   # only an owner password: readable without a password
buf = io.BytesIO(); w.write(buf)
assert "Open to everyone" in parsers.parse("pdf", buf.getvalue())["passages"][0]["text"]
step("PDF: scanned, damaged and password-protected files fail with a reason; an owner-password-only PDF is readable")

# ================================================================ storage
c1 = co.create("  Product   docs ", "About the product", ["a", "b", "a", " "], root=ROOT)
assert c1["id"].startswith("col-") and len(c1["id"]) == 16 and c1["name"] == "Product docs" and c1["tags"] == ["a", "b"] and c1["documents"] == []
raises(lambda: co.create("   ", root=ROOT), co.Invalid, "empty")
raises(lambda: co.create("x" * 121, root=ROOT), co.Invalid, "120")
assert co.get("../etc", ROOT) is None and co.get("col-zzzzzzzzzzzz", ROOT) is None and co.update("nope", ROOT, name="x") is None
u = co.update(c1["id"], ROOT, name="Product documentation", star=True, tags=["z"], bogus=1)
assert u["name"] == "Product documentation" and u["star"] and u["tags"] == ["z"] and "bogus" not in u and u["updated_at"] >= c1["updated_at"]
raises(lambda: co.update(c1["id"], ROOT, name=""), co.Invalid, "empty")
assert co.get(c1["id"], ROOT)["name"] == "Product documentation"
step("create and edit: names and tags are cleaned, bad names refused, ids that are not col-… never touch the disk")

r = co.add_document(c1["id"], "guide.md", b"# Guide\n\nHello there.\n", ROOT)
d1 = r["document"]
assert not r["duplicate"] and d1["id"].startswith("kd-") and d1["type"] == "markdown" and d1["status"] == "waiting" and d1["passages"] == 1
assert d1["collections"] == [c1["id"]] and co.passages(d1["id"], ROOT)[0]["locator"] == "Guide"
assert co.file_path(d1["id"], ROOT).read_bytes() == b"# Guide\n\nHello there.\n" and co.file_path(d1["id"], ROOT).name == "file.md"
step("a document is copied in, parsed to passages.json and waits for the indexer")

bad = co.add_document(c1["id"], "scan.pdf", make_pdf([""]), ROOT)["document"]
odd = co.add_document(c1["id"], "notes.docx", b"PK\x03\x04", ROOT)["document"]
empty = co.add_document(c1["id"], "empty.txt", b"", ROOT)["document"]
ok2 = co.add_document(c1["id"], "data.jsonl", b'{"a": 1}\n', ROOT)["document"]
assert [x["status"] for x in (bad, odd, empty, ok2)] == ["failed", "failed", "failed", "waiting"]
assert "scanned" in bad["error"] and "not supported" in odd["error"] and odd["type"] == "unknown" and "empty" in empty["error"]
assert [x["name"] for x in co.documents(c1["id"], ROOT)] == ["guide.md", "scan.pdf", "notes.docx", "empty.txt", "data.jsonl"]
step("failed files are kept, listed with their reason, and never stop the others")

dup = co.add_document(c1["id"], "same-guide-again.md", b"# Guide\n\nHello there.\n", ROOT)
assert dup["duplicate"] and dup["document"]["id"] == d1["id"] and len(co.documents(c1["id"], ROOT)) == 5
c2 = co.create("Other", root=ROOT)
dup2 = co.add_document(c2["id"], "guide.md", b"# Guide\n\nHello there.\n", ROOT)
assert dup2["duplicate"] and dup2["document"]["id"] == d1["id"] and sorted(co.get_document(d1["id"], ROOT)["collections"]) == sorted([c1["id"], c2["id"]])
assert len(list((ROOT / "docs").glob("kd-*"))) == 5
step("the same bytes are stored once and can belong to several collections")

evil = co.add_document(c2["id"], "../../../etc/passwd.md", b"# x\n\nbody", ROOT)["document"]
assert evil["name"] == "passwd.md" and co.file_path(evil["id"], ROOT).parent == ROOT / "docs" / evil["id"]
ctrl = co.add_document(c2["id"], "we\x00ird\nname.txt", b"hi", ROOT)["document"]
assert ctrl["name"] == "weirdname.txt" and co.add_document(c2["id"], "", b"zz", ROOT)["document"]["name"] == "untitled"
assert not any(p.name.endswith(".tmp") for p in ROOT.rglob("*"))
step("path tricks and control characters in a file name cannot leave the document's folder; no temp files remain")

s1 = co.summary(c1["id"], ROOT)
assert s1["documents"] == 5 and s1["status"] == "preparing" and s1["failed"] == 3 and s1["passages"] == 0 and s1["progress"] == 0
co.set_status(d1["id"], "ready", root=ROOT)
co.set_status(ok2["id"], "indexing", root=ROOT)
s1 = co.summary(c1["id"], ROOT)
assert s1["status"] == "preparing" and s1["passages"] == 1 and abs(s1["progress"] - 0.5) < 1e-9
co.set_status(ok2["id"], "ready", root=ROOT)
s1 = co.summary(c1["id"], ROOT)
assert s1["status"] == "ready" and s1["passages"] == 2 and s1["progress"] == 1.0
only_bad = co.create("Bad only", root=ROOT)
co.add_document(only_bad["id"], "x.docx", b"1", ROOT)
assert co.summary(only_bad["id"], ROOT)["status"] == "failed" and co.summary(co.create("Nothing", root=ROOT)["id"], ROOT)["status"] == "empty"
raises(lambda: co.set_status(d1["id"], "bogus", root=ROOT), co.Invalid, "status")
assert not co.set_status("kd-000000000000", "ready", root=ROOT)
step("collection status: empty, preparing with progress, ready, failed")

(ROOT / "docs" / d1["id"] / "passages.json").write_text("garbage")
assert co.passages(d1["id"], ROOT) == []
again = co.read_document(d1["id"], ROOT)
assert again["status"] == "waiting" and co.passages(d1["id"], ROOT)[0]["text"].startswith("# Guide")
(ROOT / "docs" / d1["id"] / "file.md").write_bytes(b"\xff\xfe")
assert co.read_document(d1["id"], ROOT)["status"] == "failed"
(ROOT / "docs" / d1["id"] / "file.md").write_bytes(b"# Guide\n\nHello there.\n")
assert co.read_document(d1["id"], ROOT)["status"] == "waiting" and co.read_document("kd-000000000000", ROOT) is None
(ROOT / "docs" / d1["id"] / "file.md").unlink()
assert co.read_document(d1["id"], ROOT)["status"] == "failed"
(ROOT / "docs" / d1["id"] / "file.md").write_bytes(b"# Guide\n\nHello there.\n")
co.read_document(d1["id"], ROOT); co.set_status(d1["id"], "ready", root=ROOT)
step("re-reading a document rebuilds passages.json; a damaged cache, bad bytes or a missing file end as 'failed', not a crash")

# ---- list
ids = {n: co.create(n, d, t, root=ROOT)["id"] for n, d, t in [("Zebra", "stripes", ["animals", "x"]), ("apple", "fruit", ["food"]), ("Mango", "fruit tree", ["food", "x"])]}
co.update(ids["apple"], ROOT, star=True)
co.add_document(ids["Mango"], "m.txt", b"mango text", ROOT); co.add_document(ids["Mango"], "m2.txt", b"mango two", ROOT)
names = lambda r: [i["name"] for i in r["items"]]
assert names(co.list_collections(ROOT, sort="name", desc=False))[:3] == ["apple", "Bad only", "Mango"]
assert names(co.list_collections(ROOT, sort="documents"))[0] == "Product documentation"
assert names(co.list_collections(ROOT, q="fruit", sort="name", desc=False)) == ["apple", "Mango"] and names(co.list_collections(ROOT, q="fruit tree")) == ["Mango"]
assert sorted(names(co.list_collections(ROOT, show="starred"))) == ["Product documentation", "apple"]
assert sorted(names(co.list_collections(ROOT, show="preparing"))) == ["Mango", "Other"] and names(co.list_collections(ROOT, show="ready")) == ["Product documentation"]
r = co.list_collections(ROOT, tags=["food"], sort="name", desc=False)
assert names(r) == ["apple", "Mango"] and r["tags"]["x"] == 1 and r["tags"]["food"] == 2 and r["tags"]["animals"] == 0
assert co.list_collections(ROOT, tags=["nope"])["total"] == 0 and co.list_collections(ROOT, page=2, page_size=2)["items"] and co.list_collections(ROOT, page_size=2)["total"] == 7
assert names(co.list_collections(ROOT, only=[ids["Mango"], ids["apple"]], sort="relevance")) == ["Mango", "apple"]
step("list: search, Show filter, sorts, tag filters with counts, paging, search-engine order")

# ---- membership, remove, trash
shared = d1["id"]   # in Product docs and Other
assert co.remove_from(c2["id"], shared, ROOT) == {"trashed": False} and co.get_document(shared, ROOT)["collections"] == [c1["id"]]
raises(lambda: co.remove_from(c2["id"], shared, ROOT), co.Invalid, "not in this collection")
raises(lambda: co.add_to(c2["id"], "kd-000000000000", ROOT), co.Invalid, "Unknown")
assert co.add_to(c2["id"], shared, ROOT) and co.add_to(c2["id"], shared, ROOT) and co.get(c2["id"], ROOT)["documents"].count(shared) == 1
lone = ok2["id"]
assert co.remove_from(c1["id"], lone, ROOT) == {"trashed": True} and co.get_document(lone, ROOT) is None
assert [r["id"] for r in co.load_trash(ROOT)] == [lone] and co.load_trash(ROOT)[0]["kind"] == "document"
assert co.restore(lone, ROOT) and co.get_document(lone, ROOT)["collections"] == [c1["id"]] and co.load_trash(ROOT) == []
assert not co.restore(lone, ROOT)
step("removing a document from one collection keeps it; from its last collection trashes it, and Restore puts it back")

assert co.trash_document(lone, ROOT) and co.get_document(lone, ROOT) is None and co.get(c1["id"], ROOT)["documents"].count(lone) == 0
assert co.trash_collection(c1["id"], ROOT) is True and co.get(c1["id"], ROOT) is None
assert co.get_document(shared, ROOT) is not None   # still in "Other"
tr = co.load_trash(ROOT)
kinds = sorted((r["kind"], r["name"]) for r in tr)
assert kinds == [("collection", "Product documentation"), ("document", "data.jsonl")], kinds   # docs that went with the collection are not listed alone
assert not co.restore_document(lone, ROOT)   # its collection is in the trash: restoring it alone would make an invisible document
assert co.restore(c1["id"], ROOT)
assert len(co.documents(c1["id"], ROOT)) == 4 and co.get(c1["id"], ROOT).get("deleted_at") is None
assert co.restore_document(lone, ROOT) and len(co.documents(c1["id"], ROOT)) == 5
step("trashing a collection takes the documents no other collection holds, lists only itself, and Restore brings everything back")

new = co.create("Fresh", root=ROOT)["id"]
assert new not in (c1["id"], c2["id"])
co.trash_collection(new, ROOT); old_ids = co._taken_ids(ROOT)
assert new in old_ids and co.create("x", root=ROOT)["id"] != new
assert co.trash_collection(c2["id"], ROOT)
c2_docs = [p.name for p in (ROOT / ".trash" / "docs").glob("kd-*") if json.loads((p / "doc.json").read_text()).get("deleted_with") == c2["id"]]
assert len(c2_docs) == 3 and shared in [d["id"] for d in co.all_documents(ROOT)]   # three documents belonged only to "Other"; the shared one stays
assert co.purge(c2["id"], ROOT) and co.restore(c2["id"], ROOT) is False and co.purge(c2["id"], ROOT) is False
assert not list((ROOT / ".trash").glob(f"*/{c2['id']}")) and not any((ROOT / ".trash" / "docs" / d).exists() for d in c2_docs)
step("a trashed id stays taken; purging a collection removes it for good")

# ---- indexer view
co_ids = {d["id"]: d["collections"] for d in co.all_documents(ROOT)}
assert shared in co_ids and co_ids[shared] == [c1["id"]] and all(cs for cs in co_ids.values())
step("all_documents lists live documents with the collections they belong to (the indexer's view)")

# ---- trash housekeeping
t1 = co.create("Old one", root=ROOT)["id"]
co.trash_collection(t1, ROOT)
cj = next((ROOT / ".trash").glob(f"*/{t1}/collection.json"))
j = json.loads(cj.read_text()); j["deleted_at"] = time.time() - 40 * 86400; cj.write_text(json.dumps(j))
assert co.purge_expired(0, ROOT) == 0 and co.purge_expired(30, ROOT) == 1 and co.purge_expired(30, ROOT) == 0
t2 = co.create("Empty me", root=ROOT)["id"]
co.add_document(t2, "e.txt", b"to be emptied", ROOT)
co.trash_collection(t2, ROOT)
n = co.empty_trash(ROOT)
assert n >= 1 and co.load_trash(ROOT) == [] and not list((ROOT / ".trash" / "docs").glob("kd-*")) and not list((ROOT / ".trash").glob("*/col-*"))
step("automatic purge honours the retention (0 = never) and Empty trash removes collections with their documents")

# ---- saved conversations
from backend.rag import chatexport   # noqa: E402

cs = co.create("Chats", root=ROOT)["id"]
assert co.list_chats(cs, ROOT) == [] and co.get_chat(cs, "ch-00000000", ROOT) is None and co.list_chats("col-000000000000", ROOT) == []
raises(lambda: co.create_chat("col-000000000000", root=ROOT), co.Invalid, "Unknown")
ch1 = co.create_chat(cs, [cs, "prompts"], root=ROOT)
assert ch1["id"].startswith("ch-") and len(ch1["id"]) == 11 and ch1["title"] == "" and ch1["scope"] == [cs, "prompts"] and ch1["exchanges"] == []
assert co.list_chats(cs, ROOT) == []   # an empty conversation is not listed
ex = {"prompt": "  What   about\n billing and invoices and all the other long words that go on and on and on?  ", "response": "Monthly [1].", "system": "sys", "context": "ctx",
      "model": {"provider": "ollama", "name": "gemma3:1b"}, "params": {"temperature": 0.7, "num_ctx": 8192}, "partial": False, "searched": True, "mode": "hybrid",
      "note": "", "included": ["kd-1#0"], "retrieved": [{"id": "kd-1#0", "name": "guide.md", "locator": "Billing", "score": 0.9, "cite": 1, "text": "Invoices ```fenced``` here"}]}
c = co.add_exchange(cs, ch1["id"], ex, [cs], ROOT)
assert len(c["exchanges"]) == 1 and c["exchanges"][0]["id"].startswith("ex-") and c["title"].startswith("What about billing") and len(c["title"]) <= 60 and c["title"].endswith("…")
c = co.add_exchange(cs, ch1["id"], {**ex, "prompt": "second"}, root=ROOT)
assert len(c["exchanges"]) == 2 and c["title"].startswith("What about") and c["scope"] == [cs] and c["updated_at"] >= c["ts"]
assert [r["id"] for r in co.list_chats(cs, ROOT)] == [ch1["id"]] and co.list_chats(cs, ROOT)[0]["exchanges"] == 2
assert co.add_exchange(cs, "ch-00000000", ex, root=ROOT) is None and co.add_exchange(cs, "../x", ex, root=ROOT) is None
assert co.rename_chat(cs, ch1["id"], " Billing   chat ", ROOT)["title"] == "Billing chat"
raises(lambda: co.rename_chat(cs, ch1["id"], "  ", ROOT), co.Invalid, "empty")
assert co.pin_chat(cs, ch1["id"], True, ROOT)["pinned"] is True and co.get_chat(cs, ch1["id"], ROOT)["title"] == "Billing chat"
assert [r["pinned"] for r in co.list_chats(cs, ROOT) if r["id"] == ch1["id"]] == [True] and co.pin_chat(cs, "ch-00000000", True, ROOT) is None
assert co.pin_chat(cs, ch1["id"], False, ROOT)["pinned"] is False
ch2 = co.create_chat(cs, root=ROOT)
co.add_exchange(cs, ch2["id"], ex, root=ROOT)
assert [r["id"] for r in co.list_chats(cs, ROOT)] == [ch2["id"], ch1["id"]]   # most recently used first
step("chats: stored per collection, titled from the first question, listed newest first, empty ones hidden, bad ids refused")

md = chatexport.export_markdown(cs, "Chats", co.get_chat(cs, ch1["id"], ROOT), now=0)
assert md.startswith("---\nformat: flowlystack-collection-chat\n") and md.count("<!-- pair ") == 2 and md.count("<!-- /pair -->") == 2 and "pairs: 2" in md
assert "[1] guide.md · Billing · score 90 · sent · kd-1#0" in md and "````text\nInvoices ```fenced``` here" not in md and "### Sources" in md
js_ = chatexport.export_json(cs, "Chats", co.get_chat(cs, ch1["id"], ROOT), now=0)
assert js_["format"] == "flowlystack-collection-chat" and len(js_["chat"]["exchanges"]) == 2 and js_["collection"] == cs
step("export: Markdown with fenced blocks and a Sources block per pair, JSON with the stored conversation")

assert co.delete_chat(cs, ch2["id"], ROOT) and not co.delete_chat(cs, ch2["id"], ROOT) and co.get_chat(cs, ch2["id"], ROOT) is None
bi = co.create_chat("prompts", root=ROOT)
co.add_exchange("prompts", bi["id"], ex, root=ROOT)
assert [r["id"] for r in co.list_chats("prompts", ROOT)] == [bi["id"]] and "prompts" not in co._collection_ids(ROOT) and co.get("prompts", ROOT) is None
step("My prompts keeps its conversations beside the collections, not as a collection")

co.trash_collection(cs, ROOT)
assert co.list_chats(cs, ROOT) == [] and co.get_chat(cs, ch1["id"], ROOT) is None
assert co.restore(cs, ROOT) and [r["id"] for r in co.list_chats(cs, ROOT)] == [ch1["id"]] and len(co.get_chat(cs, ch1["id"], ROOT)["exchanges"]) == 2
co.trash_collection(cs, ROOT)
assert co.purge(cs, ROOT) and not list(ROOT.glob(f".trash/*/{cs}")) and not list(ROOT.rglob(f"{ch1['id']}.json"))
step("conversations follow their collection through Trash, Restore and purge")

# ---- concurrency
cc = co.create("Parallel", root=ROOT)["id"]
errs = []
def work(i):
    try:
        co.add_document(cc, f"p{i}.txt", f"parallel document number {i}".encode(), ROOT)
    except Exception as e:   # noqa: BLE001
        errs.append(e)
ts = [threading.Thread(target=work, args=(i,)) for i in range(12)]
[t.start() for t in ts]; [t.join() for t in ts]
assert not errs and len(co.documents(cc, ROOT)) == 12 and len({d["id"] for d in co.documents(cc, ROOT)}) == 12
assert not any(p.name.endswith(".tmp") for p in ROOT.rglob("*"))
step("12 uploads at once: every document lands in the collection, ids are unique, no temp files remain")

# ---- view and edit ----
ec = co.create("Edit check", root=ROOT)["id"]
ec2 = co.create("Edit check two", root=ROOT)["id"]
md = co.add_document(ec, "notes.md", b"# Title\n\nFirst paragraph about apples.\n", ROOT)["document"]
co.add_to(ec2, md["id"], ROOT)
r = co.read_text(md["id"], ROOT)
assert r["editable"] and r["text"].startswith("# Title") and r["sha256"] == md["sha256"] and sorted(r["collections"]) == sorted([ec, ec2])
assert co.read_text("kd-000000000000", ROOT) is None
step("read_text: text, sha, editable and the collections that share the document")
old_sha = r["sha256"]
w = co.write_text(md["id"], "# Title\n\nSecond paragraph about pears.\n\n## More\n\nA third one.\n", old_sha, ROOT)
assert w["sha256"] != old_sha and "pears" in w["text"] and w["status"] == "waiting" and w["passages"] >= 1
assert "pears" in co.file_path(md["id"], ROOT).read_text() and "apples" not in " ".join(p["text"] for p in co.passages(md["id"], ROOT))
assert co.get_document(md["id"], ROOT)["size"] == len(w["text"].encode())
step("write_text: the stored file, size, sha and passages are replaced; the document waits for the indexer")
raises(lambda: co.write_text(md["id"], "stale", old_sha, ROOT), co.Conflict, "changed")
assert "pears" in co.read_text(md["id"], ROOT)["text"]
step("a save from an old copy is refused (Conflict) and changes nothing")
raises(lambda: co.write_text(md["id"], "x" * (co.EDIT_MAX + 1), w["sha256"], ROOT), co.Invalid, "MB")
step("a text over the size cap is refused")
before = co.get_document(md["id"], ROOT)
rn = co.rename_document(md["id"], "  New   name.md ", ROOT)
assert rn["name"] == "New name.md" and rn["renamed"] is True and rn["sha256"] == before["sha256"] and rn["type"] == before["type"] and rn["passages"] == before["passages"]
assert co.read_text(md["id"], ROOT)["name"] == "New name.md" and co.file_path(md["id"], ROOT).read_text() == w["text"]
raises(lambda: co.rename_document(md["id"], "   ", ROOT), co.Invalid, "empty")
raises(lambda: co.rename_document(md["id"], "x" * 121, ROOT), co.Invalid, "120")
assert co.rename_document("kd-000000000000", "x", ROOT) is None
step("rename_document: only the display name changes (text, sha, type kept); empty and over-long names are refused; an unknown id is None")
js = co.add_document(ec, "data.json", b'{"a": 1}', ROOT)["document"]
bad = co.write_text(js["id"], '{"a": ', js["sha256"], ROOT)
assert bad["status"] == "failed" and bad["error"] and bad["text"] == '{"a": '
ok = co.write_text(js["id"], '{"a": 2}', bad["sha256"], ROOT)
assert ok["status"] == "waiting" and ok["error"] == "" and ok["editable"]
step("broken JSON is saved and the document fails with the reason; saving valid JSON recovers it")
pdf = co.add_document(ec, "paper.pdf", make_pdf(["Hello from a pdf page"]), ROOT)["document"]
rp = co.read_text(pdf["id"], ROOT)
assert not rp["editable"] and "pdf" in rp["reason"].lower() and "Hello" in rp["text"]
raises(lambda: co.write_text(pdf["id"], "nope", pdf["sha256"], ROOT), co.Invalid, "cannot be edited")
step("a PDF reads as its indexed text, is read-only, and a save is refused")
co.remove_from(ec, md["id"], ROOT)
co.remove_from(ec2, md["id"], ROOT)
assert co.read_text(md["id"], ROOT) is None
step("a trashed document has no text to read")

import shutil   # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("\nall collections checks passed")
