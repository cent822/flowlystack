"""Settings saved from the Settings page. Standard library only.

Values live in `data/settings.json` (`{"schema_version": 1, "values": {...}}`), API keys apart in `data/secrets.json`
(owner-only permissions). Both are gitignored and written atomically. For every value the order is: environment
variable, then settings.json, then flowlystack.config.json (hand-edited), then the built-in default. A stored value that
no longer validates (hand-edited file) is skipped, never fatal.

Everything goes through this module and `settings_api.py`, so a user id can be added later without touching callers.
A key is never returned, logged or copied anywhere else: `GET` only says whether one is set and where it comes from.
"""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from .config import CONFIG, SETTINGS_DIR

SCHEMA = 1
PROVIDER_ID = re.compile(r"^(ollama|rt-[0-9a-f]{8})$")   # providers a default model can name: Ollama or a saved connection
RUNTIME_ID = re.compile(r"^rt-[0-9a-f]{8}$")
RUNTIME_KINDS = ("lmstudio", "llamacpp", "vllm", "jan", "localai", "custom")   # only picks the icon and hint text; behaviour is identical
MAX_RUNTIMES = 20
SECRET_NAMES = ("openai", "anthropic")    # keys the Settings page can hold (used by later adapters)
SECRET_ENV = {"openai": "FLOWLYSTACK_OPENAI_KEY", "anthropic": "FLOWLYSTACK_ANTHROPIC_KEY"}
_lock = threading.Lock()


class SettingsError(ValueError):
    """A request the user can fix. `status` is the HTTP code the route answers with."""
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# ---------- validators: return the cleaned value or raise ValueError ----------

def _num(lo, hi, kind):
    def check(v):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or (kind is int and v != int(v)):
            raise ValueError(f"must be a {'whole ' if kind is int else ''}number")
        if not lo <= v <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return kind(v)
    return check


def _text(maxlen, choices=None, strip=True):
    def check(v):
        if not isinstance(v, str):
            raise ValueError("must be text")
        v = v.strip() if strip else v   # free text (the instructions) keeps its own spacing
        if len(v) > maxlen:
            raise ValueError(f"must be at most {maxlen} characters")
        if choices is not None and v not in choices:
            raise ValueError("must be one of: " + ", ".join(choices))
        return v
    return check


def _bool(v):
    if not isinstance(v, bool):
        raise ValueError("must be true or false")
    return v


def _flag(v):
    """A true/false that an environment variable can also spell: on/off, yes/no, 1/0, true/false (any case)."""
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    raise ValueError("must be on or off")


def _url(v):
    if not isinstance(v, str):
        raise ValueError("must be text")
    v = v.strip().rstrip("/")
    u = urlparse(v)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("must be a web address like http://127.0.0.1:11434")
    return v


def _provider(v):
    if not isinstance(v, str) or not PROVIDER_ID.match(v.strip()):
        raise ValueError("must be ollama or the id of a saved connection")
    return v.strip()


# Keyboard shortcuts are stored as "mod+shift+d": `mod` is Cmd on a Mac and Ctrl elsewhere, a shortcut always needs it (a bare
# letter would break typing) and may add Shift and/or Alt (Option on a Mac; the key is read by position, so Option's special
# characters never matter). Stored as mod[+shift][+alt]+key. The combinations the browser or text
# editing already own are refused, because a page cannot take them over (Cmd+N, Cmd+T, Cmd+W) or because taking them would break
# the text box (Cmd+C, Cmd+Z). The Settings page reads this list from the API so it never has its own copy.
RESERVED_HOTKEYS = tuple(sorted(
    [f"mod+{k}" for k in "acvxzyfghjklmnpqrtw1234567890"] + ["mod+shift+n", "mod+shift+t", "mod+shift+w", "mod+shift+z", "mod+shift+q", "mod+shift+r"]
    + [f"mod+alt+{k}" for k in "ijuc"] + ["mod+shift+alt+i", "mod+shift+alt+j", "mod+shift+alt+c"]))   # developer tools, view source
HOTKEY_LABELS = {"save": "Save", "details": "Properties", "assistant": "Assistant", "search": "Search", "note": "+ Note", "new": "New prompt", "tags": "Tags", "lsadd": "Add prompt block", "lsref": "Add reference block", "lsnote": "Add sticky note", "lsframe": "Add frame", "lstidy": "Tidy up", "paneldone": "Done (block panel)", "lsdone": "Mark done (Follow)", "lscopy": "Copy prompt (Follow)", "cofocus": "Focus the question box (Collections)", "cosend": "Send question (Collections)", "conewchat": "New chat (Collections)", "cosources": "Show or hide Sources (Collections)", "codocs": "Go to Documents (Collections)"}


def _hotkey(v):
    if not isinstance(v, str):
        raise ValueError("must be text like mod+shift+d")
    parts = [x for x in v.strip().lower().split("+")]
    key, mods = parts[-1], parts[:-1]
    if not (key == "enter" or (len(key) == 1 and key.isascii() and key.isalnum())) or not set(mods) <= {"mod", "shift", "alt"} or len(set(mods)) != len(mods) or "mod" not in mods:
        raise ValueError("must be Cmd (Ctrl on Windows and Linux), optionally Shift and/or Option (Alt), plus one letter, digit or Enter")
    combo = "mod+" + ("shift+" if "shift" in mods else "") + ("alt+" if "alt" in mods else "") + key
    if combo in RESERVED_HOTKEYS:
        raise ValueError("is already used by the browser or by text editing; pick another")
    return combo


# dotted path -> (default, validator, environment variable or None)
LEAVES = {
    "assistant.default.provider": ("ollama", _provider, None),
    "assistant.default.model": ("gemma3:1b", _text(200), None),
    "assistant.instructions": ("", _text(4000, strip=False), None),   # "" = the built-in instructions
    "assistant.num_ctx": (4096, _num(512, 131072, int), None),
    "assistant.context_turns": (6, _num(0, 50, int), None),
    "assistant.temperature": (0.4, _num(0, 2, float), None),
    "assistant.history": (True, _bool, None),
    "hotkeys.save": ("mod+s", _hotkey, None),
    "hotkeys.details": ("mod+shift+d", _hotkey, None),
    "hotkeys.assistant": ("mod+shift+a", _hotkey, None),
    "hotkeys.search": ("mod+shift+s", _hotkey, None),
    "hotkeys.note": ("mod+shift+e", _hotkey, None),
    "hotkeys.new": ("mod+alt+n", _hotkey, None),
    "hotkeys.tags": ("mod+alt+t", _hotkey, None),
    "hotkeys.lsadd": ("mod+alt+p", _hotkey, None),
    "hotkeys.lsref": ("mod+alt+r", _hotkey, None),
    "hotkeys.lsnote": ("mod+alt+s", _hotkey, None),
    "hotkeys.lsframe": ("mod+alt+f", _hotkey, None),
    "hotkeys.lstidy": ("mod+alt+l", _hotkey, None),
    "hotkeys.paneldone": ("mod+alt+o", _hotkey, None),
    "hotkeys.lsdone": ("mod+enter", _hotkey, None),
    "hotkeys.lscopy": ("mod+shift+c", _hotkey, None),
    "hotkeys.cofocus": ("mod+alt+k", _hotkey, None),
    "hotkeys.cosend": ("mod+alt+e", _hotkey, None),
    "hotkeys.conewchat": ("mod+alt+h", _hotkey, None),
    "hotkeys.cosources": ("mod+alt+g", _hotkey, None),
    "hotkeys.codocs": ("mod+alt+d", _hotkey, None),
    "knowledge.embedding_model": ("", _text(200), None),   # "" = none chosen yet: documents wait and search is keyword-only
    "knowledge.auto_index": (True, _bool, None),
    "knowledge.history": (True, _bool, None),
    "knowledge.top_k": (6, _num(1, 30, int), None),
    "knowledge.min_relevance": (0.0, _num(0, 1, float), None),   # 0 = off; Auto leaves out passages whose meaning score is below this
    "knowledge.num_ctx": (8192, _num(512, 131072, int), None),
    "knowledge.instructions": ("", _text(4000, strip=False), None),   # "" = the built-in instructions
    "knowledge.gallery_ignore_words": ("", _text(2000), None),   # words the Gallery leaves out of its word charts (comma or space separated)
    # In Docker (FLOWLYSTACK_IN_DOCKER=1) 127.0.0.1 is the container itself, so the default points at the computer that runs Docker; still editable in Settings.
    "connections.ollama.url": ("http://host.docker.internal:11434" if os.environ.get("FLOWLYSTACK_IN_DOCKER") else "http://127.0.0.1:11434", _url, "FLOWLYSTACK_OLLAMA_URL"),
    "updates.check": (True, _flag, "FLOWLYSTACK_UPDATE_CHECK"),   # on by default: the server asks GitHub for the latest release at most once a day (backend/updatecheck.py); off = no request at all
    "mcp.share_hidden": (False, _bool, None),   # agents may read entities from runs the user hid on the Lattice page (off: hidden stays hidden)
    "mcp.enabled": (False, _bool, None),   # off until the user switches it on (Settings > MCP); /mcp answers 404 while off
}
SECTIONS = tuple(dict.fromkeys(k.split(".")[0] for k in LEAVES))


# ---------- files ----------

def _file(name: str) -> Path:
    return SETTINGS_DIR / name


def _read(name: str) -> dict:
    try:
        o = json.loads(_file(name).read_text())
        return o if isinstance(o, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name: str, obj: dict, private: bool = False) -> None:
    path = _file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=name + ".", suffix=".tmp")   # mkstemp: created owner-only (0600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        if not private:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _dig(d, dotted: str):
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d


def _keys() -> dict:
    k = _read("secrets.json").get("keys")
    return k if isinstance(k, dict) else {}


def _stored() -> dict:
    v = _read("settings.json").get("values")
    return v if isinstance(v, dict) else {}


# ---------- reading ----------

def resolve(path: str) -> tuple:
    """`(value, source)` for one setting; source is env, settings, config or default."""
    default, check, env = LEAVES[path]
    candidates = [("env", os.environ.get(env) if env else None), ("settings", _dig(_stored(), path)), ("config", _dig(CONFIG, path))]
    for source, raw in candidates:
        if raw is None or (source == "env" and raw == ""):
            continue
        try:
            return check(raw), source
        except ValueError:
            continue   # an unusable stored value never breaks the app
    return default, "default"


def get(path: str):
    return resolve(path)[0]


def _nest(flat: dict) -> dict:
    out: dict = {}
    for path, v in flat.items():
        d = out
        *head, last = path.split(".")
        for part in head:
            d = d.setdefault(part, {})
        d[last] = v
    return out


def section_values(name: str) -> dict:
    """The effective values of one section as a nested dict (what the rest of the app reads)."""
    return _nest({p[len(name) + 1:]: get(p) for p in LEAVES if p.startswith(name + ".")})


def _secret_known(name) -> bool:
    return isinstance(name, str) and (name in SECRET_NAMES or name in {r["id"] for r in runtimes()})


def secret_status(name: str) -> dict:
    """`{"set": bool, "source": "env"|"file"|""}`. Never the key itself."""
    if os.environ.get(SECRET_ENV.get(name, "")):
        return {"set": True, "source": "env"}
    stored = bool(_keys().get(name))
    return {"set": stored, "source": "file" if stored else ""}


def get_secret(name: str) -> str:
    """The key for a provider adapter to use (environment first). Callers must never log it or pass it on."""
    if not _secret_known(name):
        raise KeyError(name)
    return os.environ.get(SECRET_ENV.get(name, "")) or _keys().get(name) or ""


def snapshot() -> dict:
    """What `GET /api/settings` returns: effective values, where each came from, the defaults, key status."""
    res = {p: resolve(p) for p in LEAVES}
    return {"schema_version": SCHEMA, "sections": {s: section_values(s) for s in SECTIONS},
            "sources": {p: src for p, (_, src) in res.items()}, "defaults": _nest({p: LEAVES[p][0] for p in LEAVES}),
            "env": {p: LEAVES[p][2] for p in LEAVES if LEAVES[p][2]},
            "secrets": {n: secret_status(n) for n in SECRET_NAMES},
            "runtimes": [{**r, "key": secret_status(r["id"])} for r in runtimes()]}


# ---------- writing ----------

def _flatten(section: str, patch, prefix: str = "") -> dict:
    """A nested patch for one section as `{dotted path: value}`; unknown keys are an error. null clears a stored value."""
    if not isinstance(patch, dict):
        raise SettingsError("expected an object of settings")
    out = {}
    for k, v in patch.items():
        path = f"{prefix}{k}" if prefix else f"{section}.{k}"
        if path in LEAVES:
            out[path] = v
        elif any(p.startswith(path + ".") for p in LEAVES):
            out.update(_flatten(section, v, path + "."))
        else:
            raise SettingsError(f"unknown setting: {path}")
    return out


def update(section: str, patch: dict) -> dict:
    """Save the given values of one section (all or nothing). Returns the section's effective values. A value set by an
    environment variable is refused (it would silently have no effect); null removes a stored value (back to the default)."""
    if section not in SECTIONS:
        raise SettingsError(f"unknown section: {section}", 404)
    flat = _flatten(section, patch)
    clean = {}
    for path, v in flat.items():
        env = LEAVES[path][2]
        if env and os.environ.get(env):
            raise SettingsError(f"{path} is set by the environment variable {env}; change it there", 409)
        if v is None:
            clean[path] = None
            continue
        try:
            clean[path] = LEAVES[path][1](v)
        except ValueError as e:
            raise SettingsError(f"{path}: {e}") from None
    if section == "hotkeys":   # two actions on the same keys would make one of them unreachable
        eff = {p: clean[p] if p in clean and clean[p] is not None else (LEAVES[p][0] if p in clean else get(p)) for p in LEAVES if p.startswith("hotkeys.")}
        seen: dict = {}
        for p, combo in eff.items():
            name = HOTKEY_LABELS[p.split(".")[1]]
            if combo in seen:
                raise SettingsError(f"{seen[combo]} and {name} use the same keys")
            seen[combo] = name
    with _lock:
        doc = _read("settings.json")
        values = doc.get("values") if isinstance(doc.get("values"), dict) else {}
        for path, v in clean.items():
            _put(values, path, v)
        _write("settings.json", {"schema_version": SCHEMA, "values": _prune(values)})
    return section_values(section)


def _put(values: dict, path: str, v) -> None:
    *head, last = path.split(".")
    d = values
    for part in head:
        if not isinstance(d.get(part), dict):
            d[part] = {}
        d = d[part]
    if v is None:
        d.pop(last, None)
    else:
        d[last] = v


def _prune(d: dict) -> dict:
    return {k: v for k, v in ((k, _prune(v) if isinstance(v, dict) else v) for k, v in d.items()) if v != {}}


def _clean_key(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500 or any(c.isspace() for c in value.strip()):
        raise SettingsError("a key is one line of text without spaces (at most 500 characters)")
    return value.strip()


def _store_key(name: str, value: str | None) -> None:
    """Write or drop one key. The caller holds `_lock`."""
    keys = _keys()
    if value is None:
        if keys.pop(name, None) is None:
            return
    else:
        keys[name] = value
    _write("secrets.json", {"schema_version": SCHEMA, "keys": keys}, private=True)


def set_secret(name: str, value) -> dict:
    if not _secret_known(name):
        raise SettingsError(f"unknown key: {name}", 404)
    key = _clean_key(value)
    with _lock:
        _store_key(name, key)
    return secret_status(name)


def remove_secret(name: str) -> dict:
    if not _secret_known(name):
        raise SettingsError(f"unknown key: {name}", 404)
    with _lock:
        _store_key(name, None)
    return secret_status(name)


# ---------- connections to other runtimes ----------
# A list does not fit the fixed LEAVES, so it lives beside them in settings.json (`values.runtimes`) and changes only through
# these functions. The key of a connection is in secrets.json under the connection's id and is never part of the list.

def _runtime_ok(r) -> bool:
    try:
        return (isinstance(r, dict) and bool(RUNTIME_ID.match(r["id"])) and r["kind"] in RUNTIME_KINDS
                and bool(_text(60)(r["name"])) and bool(_url(r["url"])))
    except (KeyError, ValueError):
        return False


def runtimes() -> list:
    """The saved connections `[{id, kind, name, url}]` in list order (a hand-edited bad entry is skipped, never fatal)."""
    raw = _stored().get("runtimes")
    return [{k: r[k] for k in ("id", "kind", "name", "url")} for r in raw if _runtime_ok(r)] if isinstance(raw, list) else []


def runtime(rid: str):
    return next((r for r in runtimes() if r["id"] == rid), None)


def _runtime_fields(name, url, others: list) -> tuple:
    try:
        name = _text(60)(name)
        url = _url(url)
    except ValueError as e:
        raise SettingsError(str(e)) from None
    if not name:
        raise SettingsError("give the connection a name")
    if any(c in name for c in "\r\n\t") or name.lower() == "ollama" or name.lower() in {r["name"].lower() for r in others}:
        raise SettingsError("that name is already used (names are compared without capital letters)" if name.lower() != "ollama" else "that name is used by the Ollama connection")
    if len(url) > 300:
        raise SettingsError("the address is too long")
    return name, url


def _save_runtimes(values: dict, items: list) -> None:
    if items:
        values["runtimes"] = items
    else:
        values.pop("runtimes", None)
    _write("settings.json", {"schema_version": SCHEMA, "values": _prune(values)})


def _values() -> dict:
    v = _read("settings.json").get("values")
    return v if isinstance(v, dict) else {}


def add_runtime(kind, name, url, key=None) -> dict:
    """Add a connection (and its key) in one locked step. The id is made here, never by the page."""
    if kind not in RUNTIME_KINDS:
        raise SettingsError("unknown kind of connection")
    clean_key = _clean_key(key) if key not in (None, "") else None
    with _lock:
        items = runtimes()
        if len(items) >= MAX_RUNTIMES:
            raise SettingsError(f"at most {MAX_RUNTIMES} connections")
        name, url = _runtime_fields(name, url, items)
        taken = {r["id"] for r in items}
        rid = "rt-" + _secrets.token_hex(4)
        while rid in taken:
            rid = "rt-" + _secrets.token_hex(4)
        item = {"id": rid, "kind": kind, "name": name, "url": url}
        if clean_key:
            _store_key(rid, clean_key)
        _save_runtimes(_values(), items + [item])
    return {**item, "key": secret_status(rid)}


_KEEP = object()


def edit_runtime(rid: str, name=_KEEP, url=_KEEP, key=_KEEP) -> dict:
    """Change the name and/or address; `key`: a string replaces it, None removes it, omitted leaves it."""
    with _lock:
        items = runtimes()
        cur = next((r for r in items if r["id"] == rid), None)
        if cur is None:
            raise SettingsError("unknown connection", 404)
        new_name, new_url = _runtime_fields(cur["name"] if name is _KEEP else name, cur["url"] if url is _KEEP else url,
                                            [r for r in items if r["id"] != rid])
        clean_key = _clean_key(key) if key is not _KEEP and key is not None else None
        out = [{**r, "name": new_name, "url": new_url} if r["id"] == rid else r for r in items]
        if key is not _KEEP:
            _store_key(rid, clean_key)
        _save_runtimes(_values(), out)
    return {**next(r for r in out if r["id"] == rid), "key": secret_status(rid)}


def remove_runtime(rid: str) -> dict:
    """Remove a connection and its key. When it was the default model's provider the default goes back to the built-in one."""
    with _lock:
        items = runtimes()
        if not any(r["id"] == rid for r in items):
            raise SettingsError("unknown connection", 404)
        values = _values()
        reset = _dig(values, "assistant.default.provider") == rid
        if reset:
            _put(values, "assistant.default.provider", None)
            _put(values, "assistant.default.model", None)
        _store_key(rid, None)
        _save_runtimes(values, [r for r in items if r["id"] != rid])
    return {"removed": rid, "default_reset": reset}
