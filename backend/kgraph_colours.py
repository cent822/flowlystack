"""Lattice, node colours (the user's own light and dark colour per item type and per collection). Standard library only.

    PROMPTS_DIR/kgraph/colours.json     {schema, types: {<type>: {light?, dark?}}, collections: {<collection id>: {light?, dark?}}}

The file holds only changes: with no file the page uses its built-in theme colours. A collection without its own colour takes the colour of the
"collection" type. Colours are `#rrggbb`. Colours are display data: nothing here touches a prompt, a document, a collection file or a vector, and agents can
never change them. Every write takes the lock and replaces the file atomically.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path

from .config import PROMPTS_DIR

SCHEMA = 1
TYPES = ("prompt", "studio", "document", "collection", "tag", "project", "reference", "linkshell")   # entity kinds have their own colours (kgraph_kinds.py)
MAX_COLLECTIONS = 500
_LOCK = threading.RLock()
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
WHICH = ("light", "dark")


class Invalid(Exception):
    """A refused request; the message is written for the user. `status` is the HTTP code the API uses."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _path(root) -> Path:
    return (Path(root) if root is not None else Path(PROMPTS_DIR) / "kgraph") / "colours.json"


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix="colours.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _pair(o) -> dict:
    """A stored override reduced to the keys that are valid (a hand-edited bad value is ignored, never an error)."""
    out = {}
    if isinstance(o, dict):
        for w in WHICH:
            v = o.get(w)
            if isinstance(v, str) and _HEX.match(v):
                out[w] = v.lower()
    return out


def load(root=None) -> dict:
    """{types: {type: {light?, dark?}}, collections: {id: {light?, dark?}}}: the overrides only."""
    try:
        d = json.loads(_path(root).read_text())
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    types = {t: p for t in TYPES if (p := _pair((d.get("types") or {}).get(t) if isinstance(d.get("types"), dict) else None))}
    cols = {}
    if isinstance(d.get("collections"), dict):
        for cid, o in d["collections"].items():
            if isinstance(cid, str) and _ID.match(cid) and (p := _pair(o)):
                cols[cid] = p
    return {"types": types, "collections": cols}


def _fields(fields) -> dict:
    if not isinstance(fields, dict) or not fields:
        raise Invalid("Nothing to change.")
    new = {}
    for w in WHICH:
        if w in fields:
            v = fields[w]
            if not isinstance(v, str) or not _HEX.match(v):
                raise Invalid(f"The {w} colour must look like #1a2b3c.")
            new[w] = v.lower()
    if not new:
        raise Invalid("Nothing to change.")
    return new


def _save(d: dict, root) -> None:
    if not d["types"] and not d["collections"]:
        _path(root).unlink(missing_ok=True)   # nothing left to remember: back to "no file"
        return
    _write(_path(root), {"schema": SCHEMA, "types": d["types"], "collections": d["collections"]})


def set_type(name: str, fields: dict, root=None) -> dict:
    """Change the light and/or dark colour of an item type (only the keys sent)."""
    with _LOCK:
        if name not in TYPES:
            raise Invalid("There is no such type.", 404)
        new = _fields(fields)
        d = load(root)
        d["types"].setdefault(name, {}).update(new)
        _save(d, root)
        return load(root)


def set_collection(cid: str, fields: dict, root=None) -> dict:
    with _LOCK:
        if not isinstance(cid, str) or not _ID.match(cid):
            raise Invalid("That is not a collection id.", 404)
        new = _fields(fields)
        d = load(root)
        if cid not in d["collections"] and len(d["collections"]) >= MAX_COLLECTIONS:
            raise Invalid(f"Colours are kept for at most {MAX_COLLECTIONS} collections.", 409)
        d["collections"].setdefault(cid, {}).update(new)
        _save(d, root)
        return load(root)


def clear_type(name: str, root=None) -> dict:
    """Back to the built-in colour of this type (both modes)."""
    with _LOCK:
        if name not in TYPES:
            raise Invalid("There is no such type.", 404)
        d = load(root)
        d["types"].pop(name, None)
        _save(d, root)
        return load(root)


def clear_collection(cid: str, root=None) -> dict:
    """The collection takes the colour of the Collections type again."""
    with _LOCK:
        d = load(root)
        d["collections"].pop(cid, None)
        _save(d, root)
        return load(root)


def reset(root=None) -> dict:
    with _LOCK:
        _path(root).unlink(missing_ok=True)
        return load(root)
