"""Lattice, entity kinds. Standard library only.

A kind has a permanent slug and an editable label. The ten defaults keep their names as slugs; a custom kind gets `ek-` + 8 hex. Everything stored
elsewhere (batch files, entity keys, Undo) uses the slug, so renaming or deleting a kind never touches a batch file.

    PROMPTS_DIR/kgraph/kinds.json     {schema, over: {<default slug>: {label?, hint?, light?, dark?, deleted?}}, custom: [{slug, label, hint, light, dark, deleted}]}

The file holds only changes: with no file the built-in defaults apply. `light` and `dark` are `#rrggbb`. A deleted kind is kept (flagged), so Restore can
bring it back; its entities are shown as Other by the page. Agents resolve a kind by label or slug (`resolve`) and can never create or change kinds.
Every write takes the lock and replaces the file atomically.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
import uuid
from pathlib import Path

from .config import PROMPTS_DIR

SCHEMA = 1
MAX_KINDS, MAX_LABEL, MAX_HINT = 30, 24, 100   # active kinds in total, label characters, hint characters

# slug, label, hint, light colour, dark colour (the first eight reuse the dataviz steps in tokens.css; concept keeps today's colour)
DEFAULTS = (
    ("concept", "Concept", "an idea, method or principle", "#6250d6", "#9085e9"),
    ("person", "Person", "a named person", "#e87ba4", "#d55181"),
    ("organization", "Organization", "a company, team or institution", "#eda100", "#c98500"),
    ("technology", "Technology", "a tool, language, library or service", "#2a78d6", "#3987e5"),
    ("product", "Product", "a product or app", "#eb6834", "#d95926"),
    ("place", "Place", "a place", "#1baf7a", "#199e70"),
    ("event", "Event", "something that happens or happened", "#e34948", "#e66767"),
    ("process", "Process", "a procedure or workflow", "#0e9fbf", "#38b6d8"),
    ("metric", "Metric", "a measure or number", "#b04fc9", "#c77ddb"),
    ("other", "Other", "anything that fits nowhere else", "#8a8f98", "#9aa0a8"),
)
DEFAULT_SLUGS = tuple(d[0] for d in DEFAULTS)
OTHER = "other"

_LOCK = threading.RLock()
_CUSTOM = re.compile(r"^ek-[0-9a-f]{8}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class Invalid(Exception):
    """A refused request; the message is written for the user or the agent. `status` is the HTTP code the API uses."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def valid_slug(s) -> bool:
    return isinstance(s, str) and (s in DEFAULT_SLUGS or bool(_CUSTOM.match(s)))


def _path(root) -> Path:
    return (Path(root) if root is not None else Path(PROMPTS_DIR) / "kgraph") / "kinds.json"


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="kinds.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------- field checks

def clean_label(v) -> str:
    s = " ".join(v.split()) if isinstance(v, str) else ""
    if not s:
        raise Invalid("A kind needs a name.")
    if len(s) > MAX_LABEL:
        raise Invalid(f"That name is {len(s)} characters; the limit is {MAX_LABEL}.")
    if any(unicodedata.category(c).startswith("C") for c in s):
        raise Invalid("A name cannot contain control characters.")
    return s


def clean_hint(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise Invalid("The hint must be text.")
    s = " ".join(v.split())
    if len(s) > MAX_HINT:
        raise Invalid(f"The hint is {len(s)} characters; the limit is {MAX_HINT}.")
    if any(unicodedata.category(c).startswith("C") for c in s):
        raise Invalid("A hint cannot contain control characters.")
    return s


def clean_colour(v, which: str) -> str:
    if not isinstance(v, str) or not _HEX.match(v):
        raise Invalid(f"The {which} colour must look like #1a2b3c.")
    return v.lower()


# ---------------------------------------------------------------- read

def _read(root) -> dict:
    try:
        d = json.loads(_path(root).read_text())
    except (OSError, ValueError):
        return {"over": {}, "custom": []}
    over, custom = {}, []
    for slug, o in (d.get("over") or {}).items() if isinstance(d, dict) and isinstance(d.get("over"), dict) else []:
        if slug in DEFAULT_SLUGS and isinstance(o, dict):
            over[slug] = o
    for c in d.get("custom") or [] if isinstance(d, dict) and isinstance(d.get("custom"), list) else []:
        if isinstance(c, dict) and _CUSTOM.match(str(c.get("slug", ""))):
            custom.append(c)
    return {"over": over, "custom": custom}


def _field(rec: dict, key: str, fallback: str, ok) -> str:
    v = rec.get(key)
    try:
        return ok(v) if v is not None else fallback
    except Invalid:
        return fallback   # a hand-edited bad value falls back instead of breaking the page


def load(root=None) -> list[dict]:
    """Every kind, in order (defaults, then custom in creation order), deleted ones included and flagged:
    [{slug, label, hint, light, dark, builtin, deleted}]."""
    d = _read(root)
    out = []
    for slug, label, hint, light, dark in DEFAULTS:
        o = d["over"].get(slug, {})
        out.append({"slug": slug, "builtin": True, "deleted": bool(o.get("deleted")),
                    "label": _field(o, "label", label, clean_label), "hint": _field(o, "hint", hint, clean_hint),
                    "light": _field(o, "light", light, lambda x: clean_colour(x, "light")), "dark": _field(o, "dark", dark, lambda x: clean_colour(x, "dark"))})
    for c in d["custom"]:
        out.append({"slug": c["slug"], "builtin": False, "deleted": bool(c.get("deleted")),
                    "label": _field(c, "label", "Kind", clean_label), "hint": _field(c, "hint", "", clean_hint),
                    "light": _field(c, "light", "#8a8f98", lambda x: clean_colour(x, "light")), "dark": _field(c, "dark", "#9aa0a8", lambda x: clean_colour(x, "dark"))})
    return out


def active(root=None) -> list[dict]:
    return [k for k in load(root) if not k["deleted"]]


def get(slug: str, root=None) -> dict | None:
    return next((k for k in load(root) if k["slug"] == slug), None)


def resolve(value, root=None) -> str | None:
    """The slug of an active kind named by label (case-insensitive) or by slug; None when there is none (a deleted kind never resolves)."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = " ".join(value.split()).casefold()
    ks = active(root)
    for k in ks:
        if k["label"].casefold() == v:
            return k["slug"]
    for k in ks:
        if k["slug"] == v:
            return k["slug"]
    return None


def labels(root=None) -> list[str]:
    return [k["label"] for k in active(root)]


def describe(root=None) -> str:
    """One line per active kind for a tool description: `Label: hint` (the slug too for a default whose label was changed)."""
    lines = []
    for k in active(root):
        slug = f" ({k['slug']})" if k["builtin"] and k["slug"].casefold() != k["label"].casefold() else ""
        lines.append(f"{k['label']}{slug}" + (f": {k['hint']}" if k["hint"] else ""))
    return "; ".join(lines)


# ---------------------------------------------------------------- write

def _check_label(label: str, slug: str | None, ks: list[dict]) -> None:
    low = label.casefold()
    for k in ks:
        if k["deleted"] or k["slug"] == slug:
            continue
        if k["label"].casefold() == low or k["slug"] == low:
            raise Invalid(f"\"{label}\" is already used by another kind.", 409)


def _save(d: dict, root) -> None:
    _write(_path(root), {"schema": SCHEMA, "over": d["over"], "custom": d["custom"]})


def add(label, hint, light, dark, root=None) -> dict:
    with _LOCK:
        label, hint = clean_label(label), clean_hint(hint)
        light, dark = clean_colour(light, "light"), clean_colour(dark, "dark")
        ks = load(root)
        if sum(1 for k in ks if not k["deleted"]) >= MAX_KINDS:
            raise Invalid(f"There are already {MAX_KINDS} kinds, the limit. Delete one first.", 409)
        _check_label(label, None, ks)
        taken = {k["slug"] for k in ks}
        slug = "ek-" + uuid.uuid4().hex[:8]
        while slug in taken:
            slug = "ek-" + uuid.uuid4().hex[:8]
        d = _read(root)
        d["custom"].append({"slug": slug, "label": label, "hint": hint, "light": light, "dark": dark, "deleted": False})
        _save(d, root)
        return get(slug, root)


def _patch(slug: str, fields: dict, root) -> None:
    d = _read(root)
    if slug in DEFAULT_SLUGS:
        d["over"].setdefault(slug, {}).update(fields)
    else:
        rec = next((c for c in d["custom"] if c["slug"] == slug), None)
        if rec is None:
            raise Invalid("There is no such kind.", 404)
        rec.update(fields)
    _save(d, root)


def update(slug: str, fields: dict, root=None) -> dict:
    """Change label, hint, light or dark of an active kind (only the keys sent)."""
    with _LOCK:
        k = get(slug, root)
        if k is None:
            raise Invalid("There is no such kind.", 404)
        if k["deleted"]:
            raise Invalid("That kind is deleted; restore it first.", 409)
        if not isinstance(fields, dict) or not fields:
            raise Invalid("Nothing to change.")
        new = {}
        if "label" in fields:
            new["label"] = clean_label(fields["label"])
            _check_label(new["label"], slug, load(root))
        if "hint" in fields:
            new["hint"] = clean_hint(fields["hint"])
        for w in ("light", "dark"):
            if w in fields:
                new[w] = clean_colour(fields[w], w)
        _patch(slug, new, root)
        return get(slug, root)


def delete(slug: str, root=None) -> dict:
    """Soft delete: the kind is flagged, nothing else is touched. Its entities show as Other until it is restored."""
    with _LOCK:
        k = get(slug, root)
        if k is None:
            raise Invalid("There is no such kind.", 404)
        if k["slug"] == OTHER:
            raise Invalid("Other is where entities of a deleted kind are shown, so it cannot be deleted.", 409)
        if not k["deleted"]:
            _patch(slug, {"deleted": True}, root)
        return get(slug, root)


def restore(slug: str, root=None) -> dict:
    with _LOCK:
        k = get(slug, root)
        if k is None:
            raise Invalid("There is no such kind.", 404)
        if not k["deleted"]:
            return k
        ks = load(root)
        if sum(1 for x in ks if not x["deleted"]) >= MAX_KINDS:
            raise Invalid(f"There are already {MAX_KINDS} kinds, the limit. Delete one first.", 409)
        try:
            _check_label(k["label"], slug, ks)
        except Invalid:
            raise Invalid(f"Another kind now uses the name \"{k['label']}\". Rename it first, then restore.", 409)
        _patch(slug, {"deleted": False}, root)
        return get(slug, root)


def reset(root=None) -> list[dict]:
    """Back to the ten built-in defaults. Custom kinds are removed for good (their entities show as Other)."""
    with _LOCK:
        _path(root).unlink(missing_ok=True)
        return load(root)
