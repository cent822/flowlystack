#!/usr/bin/env python3
"""Checks backend/samples.py (first-run sample content) against temp folders: offer rule, add, idempotence, remove to Trash, keeping a de-tagged
item, skipping a deleted one, no Library prompts, no network. Run with .venv/bin/python (it imports the app). Never touches the real prompts/."""
import json
import os
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp())
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "prompts")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
os.environ["FLOWLYSTACK_MEILI_URL"] = "http://127.0.0.1:1"
(TMP / "prompts").mkdir()
sys.path.insert(0, str(ROOT))

from backend import collections as co, linkshell as ls, promptstore, samples  # noqa: E402
from backend.config import PROMPTS_DIR  # noqa: E402
from backend.mcp import plan as planmod  # noqa: E402
from backend.promptstore import STUDIO_DIR  # noqa: E402

assert str(PROMPTS_DIR).startswith(str(TMP)), "the check must run on its own temp folder"


def reset():
    for p in PROMPTS_DIR.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()


def live():
    return {"studio": len(promptstore.load_all(STUDIO_DIR)), "linkshell": ls.list_projects(page_size=1)["total"],
            "collections": len(co.list_collections()["items"]), "documents": len(co.all_documents())}


# ---- the content itself ----
c = samples.content()
raw = json.dumps(c)
assert c["tag"] == "Sample" and len(c["studio"]) == 4 and len(c["collection"]["documents"]) == 3
for bad in (r"/Users/", r"[\w.+-]+@[\w-]+\.[\w.]+", r"C:\\", r"docs/[\w-]*plan", r"localhost"):
    assert not re.search(bad, raw, re.I), f"sample text contains {bad!r}"
# The owner's own private words live in a local rule file outside the repository (scripts/leak_check.py); no such file, no extra check.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import leak_check  # noqa: E402
for rx in leak_check.private_patterns(Path(__file__).resolve().parent.parent):
    assert not rx.search(raw), "sample text contains a private word from the local rule file (not printed here)"
data, st = planmod.build(c["linkshell"])   # the plan must be valid
assert st["prompts"] == 8 and st["phases"] == 3 and st["specs"] == 1, st
assert all(s["title"].strip() and s["text"].strip() for s in c["studio"])

# ---- an empty app is offered samples ----
reset()
s = samples.status()
assert s["state"] == "offered" and s["can_offer"] is True and s["will_add"] == {"studio": 4, "linkshell": 1, "collections": 1, "documents": 3}, s
assert not (PROMPTS_DIR / ".samples.json").exists(), "looking must not write anything"

# ---- adding sends nothing anywhere ----
real_connect = socket.socket.connect
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("sample content made a network call"))
try:
    r = samples.add()
finally:
    socket.socket.connect = real_connect
assert r["added"] is True and r["state"] == "added" and r["can_offer"] is False and r["present"] == {"studio": 4, "linkshell": 1, "collections": 1}, r
assert live() == {"studio": 4, "linkshell": 1, "collections": 1, "documents": 3}, live()
m = json.loads((PROMPTS_DIR / ".samples.json").read_text())
assert m["state"] == "added" and sorted(i["kind"] for i in m["items"]) == ["collection", "linkshell", "studio", "studio", "studio", "studio"]
for o in promptstore.load_all(STUDIO_DIR):
    assert o["meta"]["tags"] == ["Sample"], o["meta"]["tags"]
pj = ls.list_projects()["items"][0]
assert pj["tags"] == ["Sample"], pj["tags"]   # not also marked as made over MCP
assert co.list_collections()["items"][0]["tags"] == ["Sample"]
assert promptstore.load_all(PROMPTS_DIR) == [], "the Library must stay empty: samples are never captured prompts"

# ---- adding again changes nothing; the offer is gone; dismiss does not touch added samples ----
r = samples.add()
assert r["added"] is False and live() == {"studio": 4, "linkshell": 1, "collections": 1, "documents": 3}
assert samples.dismiss()["state"] == "added"

# ---- remove: exactly the samples go to the Trash ----
mine = [i["id"] for i in m["items"] if i["kind"] == "studio"]
promptstore.create_studio("my own prompt", "Mine", ["work"])
before = live()
r = samples.remove()
assert r["removed"] == {"studio": 4, "linkshell": 1, "collections": 1} and r["kept"] == 0 and r["missing"] == 0 and r["state"] == "removed", r
assert live() == {"studio": 1, "linkshell": 0, "collections": 0, "documents": 0}, (before, live())
assert [o["title"] for o in promptstore.load_all(STUDIO_DIR)] == ["Mine"]
assert all(promptstore.trash_get(i, STUDIO_DIR) for i in mine), "removed samples must be in the Trash, restorable"
assert promptstore.restore(mine[0], STUDIO_DIR) and live()["studio"] == 2   # Undo from the Trash works
assert json.loads((PROMPTS_DIR / ".samples.json").read_text()) == {"state": "removed", "items": []}
assert samples.status()["can_offer"] is False   # removed samples are not offered again, but can be added from Settings

# ---- add again from Settings after removing; keep a de-tagged item; skip a deleted one ----
reset()
samples.add()
m = json.loads((PROMPTS_DIR / ".samples.json").read_text())
studio = [i["id"] for i in m["items"] if i["kind"] == "studio"]
promptstore.update_meta(studio[0], {"tags": ["mine-now"]}, STUDIO_DIR)   # the user took it over by removing the Sample tag
promptstore.trash(studio[1], STUDIO_DIR)   # the user already deleted this one
r = samples.remove()
assert r["kept"] == 1 and r["missing"] == 1 and r["removed"]["studio"] == 2 and r["removed"]["linkshell"] == 1, r
assert [o["id"] for o in promptstore.load_all(STUDIO_DIR)] == [studio[0]]

# ---- the offer rule ----
reset()
promptstore.create_studio("already here", "x")
assert samples.status()["can_offer"] is False, "an app with content is never offered samples"
reset()
assert samples.status()["can_offer"] is True
assert samples.dismiss()["state"] == "dismissed" and samples.status()["can_offer"] is False
assert samples.add()["added"] is True   # "No thanks" does not block adding later from Settings
reset()
ls.create("A project")
assert samples.status()["can_offer"] is False
reset()
c1 = co.create("Mine")
co.add_document(c1["id"], "a.md", b"hello")
assert samples.status()["can_offer"] is False

# ---- a damaged manifest is treated as "not offered yet", never an error ----
reset()
(PROMPTS_DIR / ".samples.json").write_text("{not json")
assert samples.status()["state"] == "offered"
(PROMPTS_DIR / ".samples.json").write_text(json.dumps({"state": "added", "items": "nope"}))
assert samples.status()["state"] == "offered"

shutil.rmtree(TMP)
print("all sample-content checks passed")
