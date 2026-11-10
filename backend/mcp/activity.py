"""A short log of what agents created through MCP, with Undo. Standard library only.

`mcp_activity.json` sits beside auth.json (tests use FLOWLYSTACK_SETTINGS_DIR). It holds no secrets and no prompt text: the time, which token, which
tool, the store, the id and the title. Undo never deletes: a created item goes to the shared Trash (the user can restore it there), and a new Studio
version is undone by saving the previous text as another version, only if nobody has edited the prompt since.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

from ..config import SETTINGS_DIR

SCHEMA = 1
MAX_ITEMS = 200
_lock = threading.RLock()

LABELS = {"studio_create": "Created Studio prompt", "studio_save_version": "Saved a new version of Studio prompt",
          "linkshell_create_project_from_plan": "Created Linkshell project", "graph_add": "Added to Lattice (entities and links)"}
LINKS = {"studio": "#/studio/", "linkshell": "#/linkshell/", "lattice": "#/lattice"}


class UndoError(Exception):
    def __init__(self, msg: str, status: int = 409):
        super().__init__(msg)
        self.status = status


def _path() -> Path:
    return SETTINGS_DIR / "mcp_activity.json"


def _load() -> list:
    try:
        d = json.loads(_path().read_text())
        items = d.get("items") if isinstance(d, dict) else None
        return [i for i in items if isinstance(i, dict) and i.get("id")] if isinstance(items, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix="mcp_activity.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"schema_version": SCHEMA, "items": items[-MAX_ITEMS:]}, f, indent=1, ensure_ascii=False)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def record(token: dict, tool: str, store: str, ref: str, title: str, **extra) -> dict:
    """Add one entry (the newest is last in the file). `extra` carries what Undo needs (a version id), never text."""
    item = {"id": "a-" + uuid.uuid4().hex[:8], "ts": time.time(), "token": str(token.get("name", ""))[:60], "token_id": str(token.get("id", "")),
            "tool": tool, "store": store, "ref": ref, "title": str(title or "")[:200], "undone": 0, **extra}
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    return item


def touch(token: dict, tool: str, store: str, ref: str, title: str, **extra) -> dict:
    """Like `record`, but a run that calls a tool many times keeps ONE line: the entry for (tool, ref) gets the new title, or is created."""
    with _lock:
        items = _load()
        for i in items:
            if i.get("tool") == tool and i.get("ref") == ref and not i.get("undone"):
                i["title"] = str(title or "")[:200]
                _save(items)
                return i
        return record(token, tool, store, ref, title, **extra)


def public(i: dict) -> dict:
    return {"id": i["id"], "time": i["ts"], "token": i.get("token", ""), "what": LABELS.get(i.get("tool"), i.get("tool", "")), "title": i.get("title", ""),
            "store": i.get("store", ""), "ref": i.get("ref", ""), "open": LINKS.get(i.get("store"), "#/") + ("" if i.get("store") == "lattice" else i.get("ref", "")), "undone": i.get("undone", 0),
            "note": i.get("undo_note", "")}


def list_items(limit: int = 30) -> list:
    with _lock:
        return [public(i) for i in reversed(_load())][:max(1, limit)]


def delete(aid: str | None = None) -> list:
    """Remove one entry (or all when `aid` is None) from this list only; the prompts and projects stay. Returns the removed raw entries so the page can offer Undo."""
    with _lock:
        items = _load()
        gone = [i for i in items if aid is None or i["id"] == aid]
        if aid is not None and not gone:
            raise UndoError("That entry is not in the list any more.", 404)
        _save([i for i in items if i not in gone])
        return gone


_ID = re.compile(r"^a-[0-9a-f]{8}$")
_KEEP = ("token", "token_id", "tool", "store", "ref", "title", "version", "prev_version", "undo_note")


def restore(entries: list) -> int:
    """Put back entries `delete` returned (Undo of a delete). Only known tools and well-formed ids are accepted; entries already present are skipped."""
    with _lock:
        items = _load()
        have = {i["id"] for i in items}
        n = 0
        for e in entries[:MAX_ITEMS] if isinstance(entries, list) else []:
            if not (isinstance(e, dict) and isinstance(e.get("id"), str) and _ID.match(e["id"]) and e["id"] not in have and e.get("tool") in LABELS):
                continue
            try:
                ts, undone = float(e.get("ts", 0)), float(e.get("undone") or 0)
            except (TypeError, ValueError):
                continue
            items.append({"id": e["id"], "ts": ts, "undone": undone, **{k: str(e[k])[:200] for k in _KEEP if k in e}})
            have.add(e["id"])
            n += 1
        items.sort(key=lambda i: i.get("ts", 0))
        _save(items)
        return n


def undo(aid: str) -> str:
    """Reverse one entry and say what happened. Raises UndoError with words for the user."""
    from .. import linkshell as ls
    from .. import promptstore as ps
    from . import sync
    with _lock:
        items = _load()
        item = next((i for i in items if i["id"] == aid), None)
        if item is None:
            raise UndoError("That entry is not in the list any more.", 404)
        if item.get("undone"):
            raise UndoError("That was already undone.")
        tool, ref = item.get("tool"), item.get("ref", "")
        if tool == "studio_create":
            if ps.get(ref, ps.STUDIO_DIR):
                ps.trash(ref, ps.STUDIO_DIR)
                sync.studio_changed()
                note = "Moved to the Trash. Restore it there if you change your mind."
            else:
                note = "It was already gone (deleted or in the Trash)."
        elif tool == "studio_save_version":
            o = ps.get(ref, ps.STUDIO_DIR)
            if not o:
                raise UndoError("That prompt is not in Studio any more, so there is nothing to undo.")
            saved, prev = ps.revision_text(ref, item.get("version", ""), ps.STUDIO_DIR), ps.revision_text(ref, item.get("prev_version", ""), ps.STUDIO_DIR)
            if not saved or not prev:
                raise UndoError("The versions involved were deleted, so this cannot be undone automatically. Use the prompt's version history.")
            if o["text"] != saved["text"]:
                raise UndoError("The prompt was edited after the agent's version, so nothing was changed. Use its version history to go back.")
            ps.save_text(ref, prev["text"], f"Undo: version saved via MCP ({item.get('token', '')})", ps.STUDIO_DIR)
            sync.studio_changed()
            note = "The previous text is the current version again (the agent's version stays in the history)."
        elif tool == "linkshell_create_project_from_plan":
            if ls.get(ref):
                ls.trash(ref)
                sync.linkshell_changed()
                note = "Moved to the Trash. Restore it there if you change your mind."
            else:
                note = "It was already gone (deleted or in the Trash)."
        elif tool == "graph_add":
            from .. import kgraph
            b = kgraph.get_batch(ref)
            if b is None:
                note = "It was already gone (deleted on the Lattice page)."
            elif b["undone"]:
                note = "It was already hidden from Lattice."
            else:
                kgraph.undo_batch(ref)
                note = "Hidden everywhere in Lattice. Nothing was deleted."
        else:
            raise UndoError("This kind of entry cannot be undone.")
        item["undone"], item["undo_note"] = time.time(), note
        _save(items)
        return note
