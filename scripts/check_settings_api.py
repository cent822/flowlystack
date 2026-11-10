#!/usr/bin/env python3
"""Checks for the /api/settings routes. Plain asserts, standard library only.

Run it against a TEST server with its own settings folder, never your real one: it saves settings and keys.

    S=$(mktemp -d)
    FLOWLYSTACK_SETTINGS_DIR=$S FLOWLYSTACK_PROMPTS_DIR=$(mktemp -d) FLOWLYSTACK_MEILI_URL=http://127.0.0.1:1 RELOAD=0 PORT=8799 ./run.sh &
    FLOWLYSTACK_SETTINGS_DIR=$S BASE=http://127.0.0.1:8799 python3 scripts/check_settings_api.py
"""
import json
import os
import stat
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("BASE", "http://127.0.0.1:8799")
DIR = Path(os.environ["FLOWLYSTACK_SETTINGS_DIR"])
assert not (DIR / "settings.json").exists() and not (DIR / "secrets.json").exists(), "the settings folder must start empty"


def call(method, path, body=None, expect=200, raw=None):
    data = raw if raw is not None else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, text = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read()
    assert code == expect, f"{method} {path}: expected {expect}, got {code}: {text[:200]!r}"
    return text.decode(), (json.loads(text) if text else None)


def step(msg):
    print("ok  ", msg)


_, g = call("GET", "/api/settings")
assert g["schema_version"] == 1 and g["sections"]["assistant"]["temperature"] == 0.4 and set(g["sources"].values()) == {"default"}
assert "double quotes" in g["readonly"]["assistant.default_instructions"] and g["secrets"]["openai"] == {"set": False, "source": ""}
step("GET: effective values, sources, defaults, key status and the read-only format rules")

_, r = call("PUT", "/api/settings/assistant", {"temperature": 0.7, "default": {"model": "gemma3:270m"}})
assert r["temperature"] == 0.7 and r["default"]["model"] == "gemma3:270m" and r["num_ctx"] == 4096
_, g = call("GET", "/api/settings")
assert g["sections"]["assistant"]["temperature"] == 0.7 and g["sources"]["assistant.temperature"] == "settings"
assert json.loads((DIR / "settings.json").read_text())["values"]["assistant"]["temperature"] == 0.7
_, r = call("PUT", "/api/settings/assistant", {"temperature": None})
assert r["temperature"] == 0.4
step("PUT: a patch is saved and read back; null returns a value to its default")

call("PUT", "/api/settings/assistant", {"temperature": 9}, 400)
call("PUT", "/api/settings/assistant", {"nonsense": 1}, 400)
call("PUT", "/api/settings/connections", {"ollama": {"url": "ftp://x"}}, 400)
call("PUT", "/api/settings/nowhere", {"a": 1}, 404)
call("PUT", "/api/settings/secrets", {"a": 1}, 404)
call("PUT", "/api/settings/assistant", raw=b"not json", expect=422)
call("PUT", "/api/settings/assistant", [1, 2], 422)
call("PUT", "/api/settings/hotkeys", {"lsdone": "mod+alt+enter"}, 200)
call("PUT", "/api/settings/hotkeys", {"lsdone": "enter"}, 400)
call("PUT", "/api/settings/hotkeys", {"lsdone": None}, 200)
_, g = call("GET", "/api/settings")
assert g["sections"]["hotkeys"]["lsdone"] == "mod+enter" and g["sections"]["hotkeys"]["lscopy"] == "mod+shift+c"
assert g["sections"]["assistant"]["temperature"] == 0.4
step("PUT: bad values 400, unknown section 404, bad body 422, nothing saved by a refused request")

KEY = "sk-api-check-SECRET-987654321"  # leak-ok: fake test key
body, r = call("PUT", "/api/settings/secrets/openai", {"value": KEY})
assert r == {"set": True, "source": "file"} and KEY not in body
assert stat.S_IMODE((DIR / "secrets.json").stat().st_mode) == 0o600
text, g = call("GET", "/api/settings")
assert KEY not in text and g["secrets"]["openai"] == {"set": True, "source": "file"} and KEY not in (DIR / "settings.json").read_text()
call("PUT", "/api/settings/secrets/openai", {"value": "has spaces"}, 400)
call("PUT", "/api/settings/secrets/openai", {}, 400)
call("PUT", "/api/settings/secrets/bogus", {"value": "k"}, 404)
body, r = call("DELETE", "/api/settings/secrets/openai")
assert r == {"set": False, "source": ""} and KEY not in body and KEY not in (DIR / "secrets.json").read_text()
call("DELETE", "/api/settings/secrets/bogus", None, 404)
step("keys: set, never echoed or listed, bad ones refused, removable")

print("\nall settings API checks passed")
