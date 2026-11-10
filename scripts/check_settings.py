#!/usr/bin/env python3
"""Checks for backend/settings.py (the Settings page's storage). Plain asserts, standard library only.

    python3 scripts/check_settings.py

Everything runs in a temp folder; your real data/settings.json and data/secrets.json are never touched.
"""
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="flowlystack-settings-check-"))
os.environ["FLOWLYSTACK_SETTINGS_DIR"] = str(TMP)   # config reads this at import
for v in ("FLOWLYSTACK_OLLAMA_URL", "FLOWLYSTACK_OPENAI_KEY", "FLOWLYSTACK_ANTHROPIC_KEY"):
    os.environ.pop(v, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import settings as st   # noqa: E402
from backend.config import CONFIG    # noqa: E402

SETTINGS, SECRETS = TMP / "settings.json", TMP / "secrets.json"


def step(msg: str) -> None:
    print("ok  ", msg)


def refuses(fn, needle: str, status: int = 400):
    try:
        fn()
    except st.SettingsError as e:
        assert needle.lower() in str(e).lower() and e.status == status, (str(e), e.status)
        return
    raise AssertionError(f"expected a SettingsError containing {needle!r}")


# ---------------------------------------------------------------- defaults
snap = st.snapshot()
a = snap["sections"]["assistant"]
assert a == {"default": {"provider": "ollama", "model": "gemma3:1b"}, "instructions": "", "num_ctx": 4096, "context_turns": 6,
             "temperature": 0.4, "history": True}, a
assert snap["sections"]["connections"] == {"ollama": {"url": "http://127.0.0.1:11434"}}
assert snap["sections"]["knowledge"] == {"embedding_model": "", "auto_index": True, "history": True, "top_k": 6, "min_relevance": 0.0, "num_ctx": 8192, "instructions": "", "gallery_ignore_words": ""}, snap["sections"]["knowledge"]
assert set(snap["sources"].values()) == {"default"} and snap["defaults"] == snap["sections"]
assert snap["secrets"] == {"openai": {"set": False, "source": ""}, "anthropic": {"set": False, "source": ""}}
assert not SETTINGS.exists() and not SECRETS.exists()   # reading never writes
step("defaults: every value, its source, and no files written by reading")

# ---------------------------------------------------------------- saving
r = st.update("assistant", {"temperature": 0.8, "default": {"model": "gemma3:270m"}})
assert r["temperature"] == 0.8 and r["default"] == {"provider": "ollama", "model": "gemma3:270m"} and r["num_ctx"] == 4096
assert json.loads(SETTINGS.read_text()) == {"schema_version": 1, "values": {"assistant": {"temperature": 0.8, "default": {"model": "gemma3:270m"}}}}
assert st.snapshot()["sources"]["assistant.temperature"] == "settings" and st.snapshot()["sources"]["assistant.num_ctx"] == "default"
assert st.update("assistant", {"temperature": 1})["temperature"] == 1.0 and isinstance(st.get("assistant.temperature"), float)
assert st.update("assistant", {"history": False})["history"] is False and st.get("assistant.temperature") == 1.0   # a patch leaves the rest alone
assert not [p for p in TMP.iterdir() if p.name.endswith(".tmp")]
step("save: a patch changes only what it names, is stored with schema_version, and leaves no temp files")

st.update("assistant", {"instructions": "  Be a pirate.\n\nShort answers.  ", "default": {"model": "  gemma3:1b "}})
assert st.get("assistant.instructions") == "  Be a pirate.\n\nShort answers.  " and st.get("assistant.default.model") == "gemma3:1b"
assert st.update("connections", {"ollama": {"url": " http://localhost:11434/ "}})["ollama"]["url"] == "http://localhost:11434"
step("save: instructions keep their spacing, short fields and the address are trimmed")

# Enter as a shortcut key (Mark done is mod+enter): accepted, stored in the same form, bad forms refused
assert st.get("hotkeys.lsdone") == "mod+enter" and st.get("hotkeys.lscopy") == "mod+shift+c"
assert st.update("hotkeys", {"lsdone": " Mod+Shift+Enter "})["lsdone"] == "mod+shift+enter" and st.update("hotkeys", {"lsdone": "mod+enter"})["lsdone"] == "mod+enter"
st.update("hotkeys", {"lsdone": None})   # back to the default, so the later checks see an untouched file
for bad in ("enter", "shift+enter", "mod+return", "mod+enterx", "mod+enter+x", "mod+c", 5):
    try:
        st.update("hotkeys", {"lsdone": bad})
        raise AssertionError(f"should have been refused: {bad!r}")
    except st.SettingsError as e:
        assert e.status == 400, (bad, e.status)
step("hotkeys: Enter is a valid key (mod+enter), stored normalised; bare Enter, other names and browser keys refused")

# ---------------------------------------------------------------- validation
before = SETTINGS.read_text()
for bad in ({"temperature": 5}, {"temperature": "hot"}, {"temperature": True}, {"num_ctx": 100}, {"num_ctx": 4096.5}, {"num_ctx": True},
            {"context_turns": -1}, {"history": "yes"}, {"history": 1}, {"default": {"provider": "nope"}}, {"default": {"model": 5}},
            {"instructions": "x" * 4001}, {"default": "ollama"}):
    try:
        st.update("assistant", bad)
        raise AssertionError(f"should have been refused: {bad}")
    except st.SettingsError as e:
        assert e.status == 400, (bad, e.status)
refuses(lambda: st.update("assistant", {"bogus": 1}), "unknown setting: assistant.bogus")
refuses(lambda: st.update("assistant", {"default": {"colour": "red"}}), "unknown setting: assistant.default.colour")
refuses(lambda: st.update("nowhere", {"a": 1}), "unknown section", 404)
refuses(lambda: st.update("assistant", [1]), "expected an object")
for url in ("ftp://x", "localhost:11434", "http://", "http://u:p@host:1", "http://h:1?x=1", "", 5):
    try:
        st.update("connections", {"ollama": {"url": url}})
        raise AssertionError(f"url should have been refused: {url!r}")
    except st.SettingsError:
        pass
refuses(lambda: st.update("assistant", {"temperature": 0.1, "num_ctx": 1}), "num_ctx")
assert SETTINGS.read_text() == before and st.get("assistant.temperature") == 1.0   # all or nothing
step("validation: wrong types, ranges, unknown keys and sections, bad addresses; a refused patch saves nothing")

# ---------------------------------------------------------------- reset
r = st.update("assistant", {"temperature": None, "default": {"model": None}})
assert r["temperature"] == 0.4 and r["default"]["model"] == "gemma3:1b"
assert "temperature" not in json.loads(SETTINGS.read_text())["values"]["assistant"]
st.update("assistant", {"instructions": None, "history": None})
st.update("connections", {"ollama": {"url": None}})
assert json.loads(SETTINGS.read_text())["values"] == {}, SETTINGS.read_text()   # empty groups are pruned
assert set(st.snapshot()["sources"].values()) == {"default"}
step("null puts a value back to its default and empty groups are removed from the file")

# ---------------------------------------------------------------- precedence
CONFIG["assistant"] = {"temperature": 0.2, "num_ctx": 8192}
CONFIG["connections"] = {"ollama": {"url": "http://10.0.0.5:11434"}}
assert st.get("assistant.temperature") == 0.2 and st.snapshot()["sources"]["assistant.temperature"] == "config"
st.update("assistant", {"temperature": 0.9})
assert st.get("assistant.temperature") == 0.9 and st.get("assistant.num_ctx") == 8192   # settings.json beats the config file
os.environ["FLOWLYSTACK_OLLAMA_URL"] = "http://env-host:11434"
assert st.get("connections.ollama.url") == "http://env-host:11434" and st.snapshot()["sources"]["connections.ollama.url"] == "env"
refuses(lambda: st.update("connections", {"ollama": {"url": "http://other:1"}}), "FLOWLYSTACK_OLLAMA_URL", 409)
os.environ["FLOWLYSTACK_OLLAMA_URL"] = ""
assert st.get("connections.ollama.url") == "http://10.0.0.5:11434"   # an empty variable is no variable
os.environ["FLOWLYSTACK_OLLAMA_URL"] = "not a url"
assert st.get("connections.ollama.url") == "http://10.0.0.5:11434"   # an unusable one is skipped, not fatal
del os.environ["FLOWLYSTACK_OLLAMA_URL"]
step("precedence: environment, then settings.json, then flowlystack.config.json, then the default")

# ---------------------------------------------------------------- damaged files
SETTINGS.write_text('{"schema_version": 1, "values": {"assistant": {"temperature": "scorching", "num_ctx": 2048}}}')
assert st.get("assistant.temperature") == 0.2 and st.get("assistant.num_ctx") == 2048   # the bad one falls through to the config file
SETTINGS.write_text("{ not json")
assert st.get("assistant.temperature") == 0.2
assert st.update("assistant", {"history": False})["history"] is False   # saving over a damaged file works
SETTINGS.write_text('["a list"]')
assert st.snapshot()["sections"]["assistant"]["history"] is True
del CONFIG["assistant"], CONFIG["connections"]
step("damaged files: an unusable stored value or file is skipped, never fatal")

# ---------------------------------------------------------------- keys
KEY = "sk-test-123456789-SECRET"
assert st.set_secret("openai", f"  {KEY}  ") == {"set": True, "source": "file"}
assert st.get_secret("openai") == KEY and st.get_secret("anthropic") == ""
assert json.loads(SECRETS.read_text()) == {"schema_version": 1, "keys": {"openai": KEY}}
assert stat.S_IMODE(SECRETS.stat().st_mode) == 0o600, oct(SECRETS.stat().st_mode)
st.set_secret("openai", KEY + "2")
assert stat.S_IMODE(SECRETS.stat().st_mode) == 0o600 and st.get_secret("openai") == KEY + "2"   # still private after a rewrite
dump = json.dumps(st.snapshot())
assert KEY not in dump and "sk-" not in dump and KEY not in SETTINGS.read_text()
assert st.snapshot()["secrets"]["openai"] == {"set": True, "source": "file"}
os.environ["FLOWLYSTACK_OPENAI_KEY"] = "env-key"
assert st.get_secret("openai") == "env-key" and st.secret_status("openai") == {"set": True, "source": "env"}
del os.environ["FLOWLYSTACK_OPENAI_KEY"]
assert st.remove_secret("openai") == {"set": False, "source": ""} and st.get_secret("openai") == ""
assert st.remove_secret("openai") == {"set": False, "source": ""}   # removing twice is fine
for bad in ("", "   ", "two words", "line\nbreak", "x" * 501, None, 5):
    try:
        st.set_secret("openai", bad)
        raise AssertionError(f"key should have been refused: {bad!r}")
    except st.SettingsError:
        pass
refuses(lambda: st.set_secret("bogus", "k"), "unknown key", 404)
refuses(lambda: st.remove_secret("bogus"), "unknown key", 404)
try:
    st.get_secret("bogus")
    raise AssertionError("unknown key name")
except KeyError:
    pass
step("keys: stored apart with owner-only permissions, never in a snapshot or settings.json, environment wins, bad keys refused")

# ---------------------------------------------------------------- Collections (Knowledge) values
st.update("knowledge", {"embedding_model": " nomic-embed-text:latest ", "top_k": 8, "auto_index": False})
k = st.snapshot()["sections"]["knowledge"]
assert k["embedding_model"] == "nomic-embed-text:latest" and k["top_k"] == 8 and k["auto_index"] is False
for bad, why in [({"top_k": 0}, "between"), ({"top_k": 99}, "between"), ({"top_k": 2.5}, "whole"), ({"auto_index": "yes"}, "true or false"),
                 ({"num_ctx": 10}, "between"), ({"embedding_model": 5}, "text")]:
    refuses(lambda: st.update("knowledge", bad), why)
st.update("knowledge", {"embedding_model": None, "top_k": None, "auto_index": None})
assert st.snapshot()["sections"]["knowledge"]["embedding_model"] == "" and st.get("knowledge.top_k") == 6
step("knowledge values: saved, trimmed, validated, and null puts a value back to its default")

# ---------------------------------------------------------------- connections to other runtimes
assert st.snapshot()["runtimes"] == [] and st.runtimes() == []
a = st.add_runtime("lmstudio", " LM Studio ", "http://127.0.0.1:1234/v1/", "lm-key-123")
assert a["name"] == "LM Studio" and a["url"] == "http://127.0.0.1:1234/v1" and a["kind"] == "lmstudio" and a["key"] == {"set": True, "source": "file"}
assert st.RUNTIME_ID.match(a["id"]) and "lm-key-123" not in json.dumps(a)
b = st.add_runtime("custom", "Hugging Face", "https://router.huggingface.co/v1")
assert b["key"] == {"set": False, "source": ""} and b["id"] != a["id"]
snap = st.snapshot()
assert [r["id"] for r in snap["runtimes"]] == [a["id"], b["id"]] and snap["secrets"] == {"openai": {"set": False, "source": ""}, "anthropic": {"set": False, "source": ""}}
assert "lm-key-123" not in json.dumps(snap) and "lm-key-123" not in SETTINGS.read_text() and "runtimes" in json.loads(SETTINGS.read_text())["values"]
assert json.loads(SECRETS.read_text())["keys"][a["id"]] == "lm-key-123" and stat.S_IMODE(SECRETS.stat().st_mode) == 0o600
assert st.get_secret(a["id"]) == "lm-key-123" and st.secret_status(b["id"]) == {"set": False, "source": ""}
refuses(lambda: st.add_runtime("custom", "lm studio", "http://x:1/v1"), "already used")        # names are unique without case
refuses(lambda: st.add_runtime("custom", "Ollama", "http://x:1/v1"), "ollama")
refuses(lambda: st.add_runtime("custom", "  ", "http://x:1/v1"), "name")
refuses(lambda: st.add_runtime("custom", "x" * 61, "http://x:1/v1"), "at most 60")
refuses(lambda: st.add_runtime("custom", "Bad", "ftp://x"), "web address")
refuses(lambda: st.add_runtime("custom", "Bad", "http://u:p@x:1/v1"), "web address")
refuses(lambda: st.add_runtime("nonsense", "Bad", "http://x:1/v1"), "kind")
refuses(lambda: st.add_runtime("custom", "Bad", "http://x:1/v1", "two words"), "key")
step("connections: added with their key in secrets.json, names unique, bad names, addresses, kinds and keys refused")

e = st.edit_runtime(a["id"], name="LM Studio (desk)")
assert e["name"] == "LM Studio (desk)" and e["url"] == a["url"] and st.get_secret(a["id"]) == "lm-key-123"   # key left alone
assert st.edit_runtime(a["id"], key="new-key")["key"]["set"] and st.get_secret(a["id"]) == "new-key"
assert st.edit_runtime(a["id"], key=None)["key"] == {"set": False, "source": ""} and a["id"] not in json.loads(SECRETS.read_text())["keys"]
assert st.edit_runtime(b["id"], url="http://192.168.1.5:8000/v1")["url"] == "http://192.168.1.5:8000/v1"
refuses(lambda: st.edit_runtime(b["id"], name="lm studio (desk)"), "already used")
assert st.edit_runtime(b["id"], name="HUGGING FACE")["name"] == "HUGGING FACE"   # a connection may change its own name's case
refuses(lambda: st.edit_runtime("rt-00000000", name="x"), "unknown connection", 404)
step("edit: name, address, key replace and remove, own name allowed, unknown id is 404")

refuses(lambda: st.update("connections", {"runtimes": []}), "unknown setting")   # the list changes only through its own functions
refuses(lambda: st.update("assistant", {"default": {"provider": "rt-zzzzzzzz"}}), "saved connection")
refuses(lambda: st.update("assistant", {"default": {"provider": "openai"}}), "saved connection")
assert st.update("assistant", {"default": {"provider": a["id"], "model": "llama3"}})["default"] == {"provider": a["id"], "model": "llama3"}
step("the default model may name a connection; the list is not writable through the generic route")

st.set_secret(b["id"], "hf_abc")
assert st.set_secret(a["id"], "again")["set"]
r = st.remove_runtime(a["id"])
assert r == {"removed": a["id"], "default_reset": True}
assert [x["id"] for x in st.runtimes()] == [b["id"]] and a["id"] not in json.loads(SECRETS.read_text())["keys"]
assert st.get("assistant.default.provider") == "ollama" and st.get("assistant.default.model") == "gemma3:1b"
refuses(lambda: st.set_secret(a["id"], "k"), "unknown key", 404)   # a removed connection's key name is gone
assert st.remove_runtime(b["id"])["default_reset"] is False and st.runtimes() == [] and "runtimes" not in json.loads(SETTINGS.read_text())["values"]
assert json.loads(SECRETS.read_text())["keys"] == {} or b["id"] not in json.loads(SECRETS.read_text())["keys"]
for i in range(st.MAX_RUNTIMES):
    st.add_runtime("custom", f"R{i}", "http://127.0.0.1:1/v1")
refuses(lambda: st.add_runtime("custom", "One more", "http://127.0.0.1:1/v1"), "at most 20")
step("remove: key dropped, the default goes back to the built-in one when it named the connection, at most 20 connections")
# a hand-edited bad entry is skipped, never fatal
doc = json.loads(SETTINGS.read_text()); doc["values"]["runtimes"].append({"id": "bad", "kind": "x", "name": "", "url": "nope"}); SETTINGS.write_text(json.dumps(doc))
assert len(st.runtimes()) == st.MAX_RUNTIMES
step("a damaged entry in the list is skipped")

shutil.rmtree(TMP, ignore_errors=True)
print("\nall settings checks passed")
