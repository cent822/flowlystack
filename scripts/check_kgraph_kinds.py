#!/usr/bin/env python3
"""Checks for Lattice's entity kinds, backend/kgraph_kinds.py and its use in backend/kgraph.py. Plain asserts, no server, standard
library plus the project's own modules, so `python3` is enough:

    python3 scripts/check_kgraph_kinds.py

Everything runs in a temp directory; your real prompts and kinds file are never touched.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-kinds-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import kgraph as kg  # noqa: E402
from backend import kgraph_kinds as kk  # noqa: E402
from backend import promptstore as ps  # noqa: E402

LIB, KG = TMP / "prompts", TMP / "kgraph"
ST = kg.Stores(LIB, TMP / "prompts" / "studio", TMP / "collections")


def step(msg: str) -> None:
    print("ok  ", msg)


def bad(fn, words, status=None):
    try:
        fn()
    except kk.Invalid as e:
        assert words.lower() in str(e).lower(), f"expected '{words}' in: {e}"
        if status:
            assert e.status == status, (e.status, status)
        return
    raise AssertionError(f"was accepted, expected a refusal containing '{words}'")


# ---------------------------------------------------------------- defaults
ks = kk.load(KG)
assert [k["slug"] for k in ks] == list(kk.DEFAULT_SLUGS) and len(ks) == 10
assert all(k["builtin"] and not k["deleted"] and k["light"].startswith("#") and k["dark"].startswith("#") for k in ks)
assert len({k["light"] for k in ks}) == 10 and len({k["dark"] for k in ks}) == 10, "every default has its own colour in both themes"
assert not (KG / "kinds.json").exists(), "no file until something is changed"
assert kk.resolve("technology", KG) == "technology" and kk.resolve("  TECHNOLOGY ", KG) == "technology" and kk.resolve("wizard", KG) is None
step("ten defaults with distinct colours, no file written, labels and slugs resolve")

# ---------------------------------------------------------------- rename and recolour
k = kk.update("technology", {"label": "Tool", "hint": "a command-line tool", "light": "#112233", "dark": "#AABBCC"}, KG)
assert k["label"] == "Tool" and k["slug"] == "technology" and k["light"] == "#112233" and k["dark"] == "#aabbcc"
assert kk.resolve("tool", KG) == "technology" and kk.resolve("technology", KG) == "technology", "label and slug both resolve after a rename"
bad(lambda: kk.update("person", {"label": "tool"}, KG), "already used", 409)
bad(lambda: kk.update("person", {"label": "Concept"}, KG), "already used", 409)
bad(lambda: kk.update("person", {"label": "x" * 25}, KG), "limit is 24")
bad(lambda: kk.update("person", {"label": "   "}, KG), "needs a name")
bad(lambda: kk.update("person", {"label": "a\x07b"}, KG), "control")
bad(lambda: kk.update("person", {"hint": "h" * 101}, KG), "limit is 100")
bad(lambda: kk.update("person", {"light": "red"}, KG), "#1a2b3c")
bad(lambda: kk.update("person", {"dark": "#12345"}, KG), "#1a2b3c")
bad(lambda: kk.update("person", {}, KG), "nothing")
bad(lambda: kk.update("nope", {"label": "x"}, KG), "no such kind", 404)
assert kk.get("person", KG)["label"] == "Person", "a refused change writes nothing"
bad(lambda: kk.update("person", {"label": "Technology"}, KG), "already used", 409)   # equals another active kind's slug: an agent could not tell them apart
step("rename, hint and colours: validated, slug never changes, label unique (also against slugs), a refused change writes nothing")

# ---------------------------------------------------------------- custom kinds
c = kk.add("Recipe", "a dish", "#ff0000", "#00ff00", KG)
assert c["slug"].startswith("ek-") and len(c["slug"]) == 11 and not c["builtin"] and c["label"] == "Recipe"
assert [k["slug"] for k in kk.load(KG)][-1] == c["slug"] and len(kk.load(KG)) == 11
assert kk.resolve("recipe", KG) == c["slug"] and kk.resolve(c["slug"], KG) == c["slug"]
bad(lambda: kk.add("recipe", "", "#000000", "#ffffff", KG), "already used", 409)
bad(lambda: kk.add("Tool", "", "#000000", "#ffffff", KG), "already used", 409)
bad(lambda: kk.add("X", "", "nope", "#ffffff", KG), "light colour")
c2 = kk.add("Ingredient", "", "#000000", "#ffffff", KG)
assert c2["slug"] != c["slug"]
assert "Recipe: a dish" in kk.describe(KG) and "Tool (technology): a command-line tool" in kk.describe(KG)
step("custom kinds: ek- slug, unique label, colours checked, listed for agents with label, slug (defaults) and hint")

# ---------------------------------------------------------------- the 30 limit
n = len(kk.active(KG))
for i in range(kk.MAX_KINDS - n):
    kk.add(f"Extra {i}", "", "#010101", "#fefefe", KG)
assert len(kk.active(KG)) == 30
bad(lambda: kk.add("One more", "", "#010101", "#fefefe", KG), "limit", 409)
kk.delete(c2["slug"], KG)
assert len(kk.active(KG)) == 29
kk.add("One more", "", "#010101", "#fefefe", KG)
bad(lambda: kk.restore(c2["slug"], KG), "limit", 409)   # full again: a deleted kind does not count, but cannot come back over the limit
kk.reset(KG)
assert len(kk.load(KG)) == 10 and not (KG / "kinds.json").exists()
step("30 active kinds at most (deleted ones do not count), restore cannot exceed it, reset empties the file")

# ---------------------------------------------------------------- delete, restore, entities keep their kind
kk.update("technology", {"label": "Tool"}, KG)
c = kk.add("Recipe", "a dish", "#ff0000", "#00ff00", KG)
bad(lambda: kk.delete("other", KG), "cannot be deleted", 409)
bad(lambda: kk.delete("nope", KG), "no such kind", 404)
pid = ps.write_prompt("Redis caches the soup recipe. Alice Chen likes it.", time.time() - 10, "s1", "", "hook", LIB, {"agent": "claude"})
r = kg.add_batch({"entities": [{"name": "Redis", "kind": "tool"}, {"name": "Soup", "kind": "Recipe"}, {"name": "Alice Chen", "kind": "person"}],
                  "edges": [{"type": "mentions", "to": "Redis", "item": pid, "quote": "Redis caches the soup recipe"},
                            {"type": "mentions", "to": "Soup", "item": pid, "quote": "the soup recipe"},
                            {"type": "mentions", "to": "Alice Chen", "item": pid, "quote": "Alice Chen likes it"}]},
                 by="t", root=KG, stores=ST)
ents = {e["name"]: e for e in kg.entities_index(KG)["entities"].values()}
assert ents["Redis"]["kind"] == "technology" and ents["Soup"]["kind"] == c["slug"] and ents["Alice Chen"]["kind"] == "person", "stored as slugs, resolved from labels"
assert ents["Redis"]["key"] == "redis|technology"
files = {p.name: p.read_bytes() for p in (KG / "batches").glob("*.json")}

kk.delete("technology", KG)
kk.delete(c["slug"], KG)
assert kk.resolve("tool", KG) is None and kk.resolve("technology", KG) is None and kk.resolve("recipe", KG) is None
assert {p.name: p.read_bytes() for p in (KG / "batches").glob("*.json")} == files, "deleting a kind never rewrites a batch file"
ents2 = {e["name"]: e for e in kg.entities_index(KG)["entities"].values()}
assert set(ents2) == {"Redis", "Soup", "Alice Chen"} and ents2["Redis"]["kind"] == "technology", "entities of a deleted kind still load, with their slug"
assert [k["slug"] for k in kk.load(KG) if k["deleted"]] == ["technology", c["slug"]]
try:
    kg.add_batch({"entities": [{"name": "Valkey", "kind": "tool"}], "edges": [{"type": "mentions", "to": "Valkey", "item": pid, "quote": "Redis caches"}]},
                 by="t", root=KG, stores=ST)
    raise AssertionError("a deleted kind was accepted")
except kg.Invalid as e:
    assert "Person" in str(e) and "Tool" not in str(e), str(e)
kk.restore("technology", KG)
kk.restore(c["slug"], KG)
assert kk.resolve("tool", KG) == "technology" and kk.get(c["slug"], KG)["label"] == "Recipe" and kk.get("technology", KG)["light"] == kk.DEFAULTS[3][3]
kk.delete(c["slug"], KG)
bad(lambda: kk.update(c["slug"], {"label": "x"}, KG), "restore it first", 409)   # a deleted kind cannot be edited
kk.add("Recipe", "", "#000000", "#ffffff", KG)   # the name of a deleted kind is free to use again
bad(lambda: kk.restore(c["slug"], KG), "rename it first", 409)
step("delete is soft (no batch file changes, entities still load, agents refused), restore returns the kind; a taken name blocks a restore with a clear message")

# ---------------------------------------------------------------- hand-edited or damaged file
(KG / "kinds.json").write_text("{not json")
assert len(kk.load(KG)) == 10, "a damaged file falls back to the defaults and does not raise"
(KG / "kinds.json").write_text(json.dumps({"schema": 1, "over": {"person": {"label": "x" * 99, "light": "bad"}, "zzz": {}}, "custom": [{"slug": "ek-zzzz", "label": "no"}, {"slug": "ek-0123abcd", "label": "Ok"}]}))
ks = kk.load(KG)
assert len(ks) == 11 and kk.get("person", KG)["label"] == "Person" and kk.get("person", KG)["light"] == kk.DEFAULTS[1][3]
assert kk.get("ek-0123abcd", KG)["label"] == "Ok" and kk.get("ek-zzzz", KG) is None
step("a damaged or hand-edited file never raises: bad values fall back, bad records are skipped")

# ---------------------------------------------------------------- slug shape
assert kk.valid_slug("person") and kk.valid_slug("ek-0123abcd") and not kk.valid_slug("ek-xyz") and not kk.valid_slug("Person") and not kk.valid_slug(None)
step("only well-formed slugs load")

print("\nall Lattice entity-kinds checks passed")
