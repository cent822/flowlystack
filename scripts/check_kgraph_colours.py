#!/usr/bin/env python3
"""Checks for Lattice's node colours, backend/kgraph_colours.py. Plain asserts, no server, standard library plus the project's own modules:

    python3 scripts/check_kgraph_colours.py

Everything runs in a temp directory; your real colours file is never touched.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-colours-check-"))
os.environ["FLOWLYSTACK_PROMPTS_DIR"] = str(TMP / "unused")
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP / "settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import kgraph_colours as kc  # noqa: E402

KG = TMP / "kgraph"
F = KG / "colours.json"


def step(msg: str) -> None:
    print("ok  ", msg)


def bad(fn, words, status=None):
    try:
        fn()
    except kc.Invalid as e:
        assert words.lower() in str(e).lower(), f"expected '{words}' in: {e}"
        if status:
            assert e.status == status, (e.status, status)
        return
    raise AssertionError(f"was accepted, expected a refusal containing '{words}'")


# defaults: nothing stored
assert kc.load(KG) == {"types": {}, "collections": {}} and not F.exists()
step("no file until something is changed; nothing stored means the built-in colours")

# a type: light only, then dark, case folded
d = kc.set_type("tag", {"light": "#AABBCC"}, KG)
assert d["types"] == {"tag": {"light": "#aabbcc"}} and F.exists()
d = kc.set_type("tag", {"dark": "#112233"}, KG)
assert d["types"]["tag"] == {"light": "#aabbcc", "dark": "#112233"}
bad(lambda: kc.set_type("tag", {"light": "red"}, KG), "#1a2b3c")
bad(lambda: kc.set_type("tag", {"dark": "#12345"}, KG), "#1a2b3c")
bad(lambda: kc.set_type("tag", {}, KG), "nothing")
bad(lambda: kc.set_type("tag", {"other": "#112233"}, KG), "nothing")
bad(lambda: kc.set_type("entity", {"light": "#112233"}, KG), "no such type", 404)
bad(lambda: kc.set_type("wizard", {"light": "#112233"}, KG), "no such type", 404)
assert kc.load(KG)["types"]["tag"]["light"] == "#aabbcc", "a refused change writes nothing"
step("type colours: light and dark apart, validated, unknown or entity type refused, a refusal writes nothing")

# collections
d = kc.set_collection("co-abc123", {"light": "#ff0000", "dark": "#00ff00"}, KG)
assert d["collections"] == {"co-abc123": {"light": "#ff0000", "dark": "#00ff00"}}
bad(lambda: kc.set_collection("../evil", {"light": "#ff0000"}, KG), "not a collection id", 404)
bad(lambda: kc.set_collection("x" * 65, {"light": "#ff0000"}, KG), "not a collection id", 404)
step("collection colours stored by id; odd ids refused")

# clear
d = kc.clear_collection("co-abc123", KG)
assert d["collections"] == {}
d = kc.clear_collection("co-nope", KG)   # clearing nothing is fine
d = kc.clear_type("tag", KG)
assert d == {"types": {}, "collections": {}} and not F.exists(), "the file goes when nothing is left"
bad(lambda: kc.clear_type("wizard", KG), "no such type", 404)
step("clear returns to defaults and removes the file when empty")

# hand-edited file: bad values are ignored, never an error
KG.mkdir(parents=True, exist_ok=True)
F.write_text(json.dumps({"schema": 1, "types": {"prompt": {"light": "#123456", "dark": "nope"}, "entity": {"light": "#123456"}, "tag": "x"},
                         "collections": {"ok-1": {"dark": "#abcdef"}, "../bad": {"dark": "#abcdef"}, "empty": {}}}))
d = kc.load(KG)
assert d == {"types": {"prompt": {"light": "#123456"}}, "collections": {"ok-1": {"dark": "#abcdef"}}}, d
F.write_text("{ not json")
assert kc.load(KG) == {"types": {}, "collections": {}}
step("a hand-edited or broken file loads what is valid and ignores the rest")

# reset
kc.set_type("prompt", {"light": "#010203"}, KG)
kc.set_collection("c1", {"light": "#010203"}, KG)
assert kc.reset(KG) == {"types": {}, "collections": {}} and not F.exists()
step("reset removes everything")

# limit
for i in range(kc.MAX_COLLECTIONS):
    kc.set_collection(f"c{i}", {"light": "#010203"}, KG)
bad(lambda: kc.set_collection("one-more", {"light": "#010203"}, KG), "at most", 409)
kc.set_collection("c0", {"dark": "#040506"}, KG)   # an existing one can still change
step("collection limit holds; existing ones still editable")

print("all colour checks passed")
