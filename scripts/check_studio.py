#!/usr/bin/env python3
"""Checks for the Prompt Studio storage in backend/promptstore.py. Plain asserts, standard library only.

    python3 scripts/check_studio.py

Everything runs in a temp directory; your real prompts are never touched.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-studio-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")   # config reads this at import; every call below passes its own root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import promptstore as ps   # noqa: E402

LIB = TMP / "prompts"
STUDIO = LIB / "studio"   # the real layout: Studio lives inside the prompts folder


def step(msg: str) -> None:
    print("ok  ", msg)


# --- a small Library to prove it never changes ---
now = time.time()
a = ps.write_prompt("library prompt one", now - 100, "sess-a", "/x/proj", root=LIB)
b = ps.write_prompt("library prompt two {{not_a_studio_var}}", now - 50, "sess-b", "/x/proj", root=LIB)
lib_before = [(o["id"], o["text"], o["edited"], o["meta"], o["agent"]) for o in ps.load_all(LIB)]
assert len(lib_before) == 2

# --- create ---
d = ps.create_studio("Hello {{name}}, about {{ topic }} and {{name}} again", "Greeter", ["a", "a", " b "], root=STUDIO)
pid = d["id"]
assert pid.startswith("ps-") and len(pid) == 15 and all(c in "0123456789abcdef" for c in pid[3:]), pid
assert d["kind"] == "studio" and d["schema_version"] == 1 and d["agent"] == ""
assert d["variables"] == ["name", "topic"], d["variables"]
assert ps.variables("{{ a }} {{a-b}} {{1x}} {{x_1}} {{größe}} {{ x y }} {{}}") == ["a", "a-b", "x_1"], ps.variables("{{ a }} {{a-b}} {{1x}} {{x_1}} {{größe}} {{ x y }} {{}}")
assert d["edited"] and len(d["revisions"]) == 1 and d["revisions"][0]["message"] == "Created"
m = d["meta"]
assert m["status"] == "draft" and m["title"] == "Greeter" and m["tags"] == ["a", "b"] and not m["starred"]
assert (m["purpose"], m["use_when"], m["target"], m["example"]) == ("", "", "", "")
assert "derived_from" not in d
step("create: id, schema_version, variables, Created version, Draft status")

try:
    ps.create_studio("   ", root=STUDIO)
    raise SystemExit("empty text must be refused")
except ValueError:
    pass
assert len(ps.load_all(STUDIO)) == 1
step("create: empty text is refused and writes nothing")

ids = {ps.create_studio(f"p{i}", root=STUDIO)["id"] for i in range(40)}
assert len(ids) == 40 and pid not in ids
for i in ids:
    ps.trash(i, STUDIO)
    ps.purge(i, STUDIO)
assert len(ps.load_all(STUDIO)) == 1 and not ps.load_trash(STUDIO)
step("ids: 40 created are all distinct; trash and purge clean up")

# --- Library untouched ---
assert [(o["id"], o["text"], o["edited"], o["meta"], o["agent"]) for o in ps.load_all(LIB)] == lib_before
assert pid not in {o["id"] for o in ps.load_all(LIB)}
step("Library: same 2 prompts after Studio prompts exist, none of them listed")

# --- versions ---
v1 = d["revisions"][0]["hash"]
d2 = ps.save_text(pid, "Second draft for {{who}}", "Rewrote it", STUDIO)
d3 = ps.save_text(pid, "Third draft for {{who}} and {{when}}", "Added when", STUDIO)
assert [r["message"] for r in d3["revisions"]] == ["Added when", "Rewrote it", "Created"]
assert d3["text"] == "Third draft for {{who}} and {{when}}" and d3["variables"] == ["who", "when"]
assert len(ps.save_text(pid, d3["text"], "same text", STUDIO)["revisions"]) == 3
step("versions: three saves, newest first, a save with unchanged text adds nothing")

old = ps.revision_text(pid, v1, STUDIO)
assert old["text"].startswith("Hello {{name}}")
d4 = ps.save_text(pid, old["text"], "Restored version " + v1, STUDIO)
assert d4["text"] == old["text"] and len(d4["revisions"]) == 4 and d4["revisions"][0]["message"].startswith("Restored")
step("rollback: an old version saved as a new one")

rows = ps.diff(pid, v1, "current", STUDIO)
assert rows and rows["rows"], "diff has rows"
step("diff: old version against current")

mid = d4["revisions"][2]["hash"]
d5 = ps.delete_revision(pid, mid, STUDIO)
assert len(d5["revisions"]) == 3 and mid not in {r["hash"] for r in d5["revisions"]}
assert ps.delete_revision(pid, d5["revisions"][0]["hash"], STUDIO) is False
assert ps.delete_revision(pid, "0000000", STUDIO) is None
step("delete a version: a middle one goes, the current one is refused, an unknown one is None")

# --- meta ---
mt = ps.update_meta(pid, {"status": "refined", "purpose": "greet", "use_when": "always", "target": "claude", "example": "hi",
                          "starred": True, "tags": ["x", "x", "y"], "note": "n", "nonsense": 1}, STUDIO)
assert mt["status"] == "refined" and mt["status_at"] > 0 and mt["purpose"] == "greet" and mt["starred"] and mt["tags"] == ["x", "y"]
assert "nonsense" not in mt
at = mt["status_at"]
mt = ps.update_meta(pid, {"status": "bogus", "note": "again"}, STUDIO)
assert mt["status"] == "refined" and mt["status_at"] == at and mt["note"] == "again"
step("meta: status and documentation fields, bad status ignored, status_at only moves on a change")

# --- promote ---
p = ps.promote_from_library(b, STUDIO, LIB)
assert p["derived_from"] == {"store": "library", "id": b} and p["text"].startswith("library prompt two")
assert p["variables"] == ["not_a_studio_var"] and p["meta"]["status"] == "draft" and len(p["revisions"]) == 1
assert ps.promote_from_library("nope", STUDIO, LIB) is None
assert [(o["id"], o["text"], o["edited"], o["meta"], o["agent"]) for o in ps.load_all(LIB)] == lib_before
assert not list(LIB.glob("*/*.md"))   # promoting never writes into the Library
step("promote: copy with derived_from, Library prompt unchanged")

# --- trash, restore, purge ---
assert ps.trash(p["id"], STUDIO) and ps.get(p["id"], STUDIO) is None
tr = ps.load_trash(STUDIO)
assert [o["id"] for o in tr] == [p["id"]] and list((STUDIO / ".trash").glob("*/*.versions.json"))
assert ps.restore(p["id"], STUDIO) is True and ps.get(p["id"], STUDIO)["meta"]["status"] == "draft"
assert ps.detail(p["id"], STUDIO)["revisions"] and not ps.load_trash(STUDIO)
step("trash and restore: all files move to studio/.trash and back")

assert ps.trash(p["id"], STUDIO) and ps.purge(p["id"], STUDIO) and not ps.load_trash(STUDIO)
assert not list(STUDIO.rglob(f"{p['id']}*"))
assert ps.create_studio("another", root=STUDIO)["id"] != p["id"]
step("purge: every file is gone")

# --- Assistant chat (pairs saved beside the prompt) ---
EX = {"model": {"provider": "ollama", "name": "gemma3:1b"}, "params": {"temperature": 0.4, "num_ctx": 4096}, "system": "S", "context": "C",
      "prompt": "make it shorter", "response": "Done.\n<<<PROMPT\nShort.\nPROMPT>>>", "proposal": {"text": "Short."}}
assert ps.read_chat(pid, STUDIO) == [] and ps.read_chat("ps-nope", STUDIO) is None and ps.read_chat(a, STUDIO) is None
n_prompts = len(ps.load_all(STUDIO))
e1 = ps.add_exchange(pid, EX, STUDIO)
e2 = ps.add_exchange(pid, {**EX, "proposal": None, "partial": True, "prompt": "and?"}, STUDIO)
assert e1["id"].startswith("e-") and len(e1["id"]) == 10 and e1["id"] != e2["id"] and e1["kind"] == "chat" and e1["ts"] > 0
assert e1["proposal"] == {"text": "Short.", "status": "open"} and e2["proposal"] is None and e2["partial"] is True
assert e1["curation"] == {"keep": None, "note": ""} and e1["system"] == "S" and e1["context"] == "C"
assert [e["id"] for e in ps.read_chat(pid, STUDIO)] == [e1["id"], e2["id"]]
assert ps.add_exchange("ps-nope", EX, STUDIO) is None and ps.add_exchange(a, EX, STUDIO) is None
assert len(ps.load_all(STUDIO)) == n_prompts and ps.get(pid, STUDIO)["meta"]["status"] == "refined"   # the chat file is not a prompt and changes nothing
step("chat: exchanges are appended oldest first with id, time, open proposal and empty curation; the file is not listed as a prompt")

assert ps.set_proposal_status(pid, e1["id"], "applied", STUDIO)["proposal"]["status"] == "applied"
assert ps.set_proposal_status(pid, e2["id"], "applied", STUDIO) is None and ps.set_proposal_status(pid, "e-nope", "applied", STUDIO) is None
try:
    ps.set_proposal_status(pid, e1["id"], "bogus", STUDIO)
    raise SystemExit("a bad proposal status must be refused")
except ValueError:
    pass
assert ps.set_curation(pid, e1["id"], keep=True, root=STUDIO)["curation"] == {"keep": True, "note": ""}
assert ps.set_curation(pid, e1["id"], note="good example", root=STUDIO)["curation"] == {"keep": True, "note": "good example"}
assert ps.set_curation(pid, e1["id"], keep=None, root=STUDIO)["curation"] == {"keep": None, "note": "good example"}
assert ps.set_curation(pid, "e-nope", keep=True, root=STUDIO) is None
saved = {e["id"]: e for e in ps.read_chat(pid, STUDIO)}
assert saved[e1["id"]]["proposal"]["status"] == "applied" and saved[e2["id"]]["curation"] == {"keep": None, "note": ""}
step("chat: proposal status and curation change one exchange and nothing else")

assert "assistant_history" not in ps.get(pid, STUDIO)["meta"] and "assistant_history" not in ps._clean_meta({"assistant_history": False}, True)
assert "assistant_history" not in ps.update_meta(pid, {"assistant_history": False}, STUDIO)   # the per-prompt switch is gone: the field is never stored
step("history: the per-prompt switch no longer exists (sidecars never carry it; an old value is ignored)")

# Properties: the user's own key/value pairs (all go into a Markdown export header). The documentation fields are properties with
# well-known names and stay in step both ways; the Library never gets the field.
m = ps.get(pid, STUDIO)["meta"]
assert m["properties"] == [{"key": k, "value": m[k]} for k in ("purpose", "target", "use_when", "example", "note") if m[k].strip()]   # built from the old fields
m = ps.update_meta(pid, {"properties": [{"key": "Purpose", "value": "greet"}, {"key": "owner", "value": "me"}, {"key": "When to use", "value": "always"},
                                         {"key": "purpose", "value": "dup"}, {"key": "  ", "value": "x"}, {"key": "Status", "value": "no"}, {"key": "note", "value": "n"}]}, STUDIO)
assert [(p["key"], p["value"]) for p in m["properties"]] == [("Purpose", "greet"), ("owner", "me"), ("When to use", "always"), ("note", "n")]   # repeats, empty and reserved names dropped
assert (m["purpose"], m["use_when"], m["note"], m["target"], m["example"]) == ("greet", "always", "n", "", "")   # the fields follow
m = ps.update_meta(pid, {"target": "claude", "purpose": ""}, STUDIO)   # a patch of the fields themselves updates, adds and removes their properties
assert [p["key"] for p in m["properties"]] == ["owner", "When to use", "note", "target"]
assert ps.check_properties([{"key": "a", "value": "1"}, {"key": "A", "value": "2"}]) and ps.check_properties([{"key": "tags", "value": ""}]) and ps.check_properties([{"key": "", "value": ""}])
assert ps.check_properties([{"key": "owner", "value": ""}]) == ""
assert "properties" not in ps.load_all(LIB)[0]["meta"] and "properties" not in ps._clean_meta({"properties": [{"key": "a", "value": "b"}]})
step("properties: built from the old fields, cleaned, kept in step with them, validated; Library never gets the field")

exchanges_before = ps.read_chat(pid, STUDIO)
assert ps.trash(pid, STUDIO) and ps.read_chat(pid, STUDIO) is None
assert list((STUDIO / ".trash").glob(f"*/{pid}.chat.json")) and not list(STUDIO.glob(f"*/{pid}.chat.json"))
assert ps.restore(pid, STUDIO) is True and ps.read_chat(pid, STUDIO) == exchanges_before and not list((STUDIO / ".trash").glob("*/*.chat.json"))
step("chat: follows its prompt into the trash and back")

gone = ps.create_studio("to be trashed {{v}}", "Gone", root=STUDIO)["id"]
ps.add_exchange(gone, EX, STUDIO)
ps.trash(gone, STUDIO)
assert [o["id"] for o in ps.load_trash(STUDIO)] == [gone]   # the chat file is not read as a trashed prompt

# --- export and re-import ---
   # a trashed prompt must survive the round trip too
exp = ps.export_studio(STUDIO)
assert len(exp["prompts"]) == 3 and sum(x["trashed"] for x in exp["prompts"]) == 1
assert sorted(x["id"] for x in exp["prompts"] if x.get("chat")) == sorted([pid, gone]) and exp["schema_version"] == 1   # chat is an optional key
STUDIO2 = TMP / "empty" / "studio"
assert ps.import_studio(exp, STUDIO2) == {"imported": 3, "skipped": 0}
assert ps.export_studio(STUDIO2) == exp, "export of the import differs from the export"
for o in ps.load_all(STUDIO):
    o2 = ps.get(o["id"], STUDIO2)
    assert o2["text"] == o["text"] and o2["meta"] == o["meta"] and ps.detail(o["id"], STUDIO2)["revisions"] == ps.detail(o["id"], STUDIO)["revisions"]
assert ps.import_studio(exp, STUDIO2) == {"imported": 0, "skipped": 3}
try:
    ps.import_studio({"kind": "something else"}, STUDIO2)
    raise SystemExit("a foreign file must be refused")
except ValueError:
    pass
assert ps.read_chat(pid, STUDIO2) == ps.read_chat(pid, STUDIO) and list((STUDIO2 / ".trash").glob(f"*/{gone}.chat.json"))
step("export and re-import: identical text, versions, meta and original; trash included; re-import skips; chat travels along")

old_export = {**exp, "prompts": [{k: v for k, v in x.items() if k != "chat"} for x in exp["prompts"]]}   # an export from before the Assistant
STUDIO3 = TMP / "empty3" / "studio"
assert ps.import_studio(old_export, STUDIO3) == {"imported": 3, "skipped": 0} and ps.read_chat(pid, STUDIO3) == []
step("import: an export without chat keys still imports")

assert ps.clear_chat(pid, STUDIO) == 2 and ps.read_chat(pid, STUDIO) == [] and not list(STUDIO.glob(f"*/{pid}.chat.json"))
assert ps.clear_chat(pid, STUDIO) == 0 and ps.clear_chat("ps-nope", STUDIO) is None
e3 = ps.add_exchange(pid, EX, STUDIO)
assert ps.delete_exchange(pid, e3["id"], STUDIO) and not ps.delete_exchange(pid, e3["id"], STUDIO) and ps.read_chat(pid, STUDIO) == []
step("chat: clear and delete one exchange")

ps.purge(gone, STUDIO)
assert not list(STUDIO.rglob(f"{gone}*"))
step("purge: a trashed prompt's chat file goes with it")

old = ps.create_studio("old and trashed", root=STUDIO)["id"]
ps.add_exchange(old, EX, STUDIO)
ps.trash(old, STUDIO)
mp = next((STUDIO / ".trash").glob(f"*/{old}.meta.json"))
mp.write_text(json.dumps({**json.loads(mp.read_text()), "deleted_at": time.time() - 40 * 86400}))
assert ps.purge_expired(30, STUDIO) == 1 and not list(STUDIO.rglob(f"{old}*"))
step("automatic purge: an expired trashed prompt takes its chat file with it")

assert [(o["id"], o["text"], o["edited"], o["meta"], o["agent"]) for o in ps.load_all(LIB)] == lib_before
step("Library: still unchanged at the end")

import shutil   # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
print("\nall Studio storage checks passed")
