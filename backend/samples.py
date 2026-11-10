"""First-run sample content. Standard library plus the app's own stores.

Offered once to an empty app, added only when the user presses a button, removable in one action. Every sample carries the tag `Sample`, and
`<prompts folder>/.samples.json` records exactly what was added, so "remove" touches nothing else. It is written through the same functions the
routes use (so search, Trash and Undo behave as for the user's own content), sends nothing anywhere and calls no model (indexing the documents for search is the user's own Collections setting, not this module).

The manifest lives next to the user's prompts (not in data/) so a backup, or a re-created data volume, keeps the state and never re-offers.
States: offered (no file yet), added, dismissed, removed. Only "offered" on an empty app is ever shown as an offer.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import collections as co, linkshell as ls, promptstore
from .config import PROMPTS_DIR
from .mcp import plan as planmod
from .promptstore import STUDIO_DIR

CONTENT = Path(__file__).with_name("samples_content.json")
_lock = threading.RLock()


def _manifest_path() -> Path:
    return PROMPTS_DIR / ".samples.json"


def _read() -> dict:
    try:
        m = json.loads(_manifest_path().read_text(encoding="utf-8"))
        if isinstance(m, dict) and m.get("state") in ("added", "dismissed", "removed") and isinstance(m.get("items"), list):
            return m
    except (OSError, ValueError):
        pass
    return {"state": "offered", "items": []}


def _write(m: dict) -> None:
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(m, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def content() -> dict:
    return json.loads(CONTENT.read_text(encoding="utf-8"))


def will_add() -> dict:
    c = content()
    return {"studio": len(c["studio"]), "linkshell": 1, "collections": 1, "documents": len(c["collection"]["documents"])}


def is_empty() -> bool:
    """No Studio prompt, no Linkshell project and no collection document: only then is the app offered samples."""
    return (not promptstore.load_all(STUDIO_DIR) and ls.list_projects(page_size=1)["total"] == 0 and not co.all_documents())


def _look(kind: str, id_: str):
    """(exists, tagged) for one manifest item. A trashed or purged item does not exist; an item whose Sample tag was removed is the user's now."""
    tag = content()["tag"]
    if kind == "studio":
        o = promptstore.get(id_, STUDIO_DIR)
        return (True, tag in o["meta"]["tags"]) if o else (False, False)
    if kind == "linkshell":
        p = ls.get(id_)
        return (True, tag in p["project"].get("tags", [])) if p else (False, False)
    if kind == "collection":
        c = co.get(id_)
        return (True, tag in c.get("tags", [])) if c else (False, False)
    return (False, False)


def _present(m: dict) -> list[dict]:
    out = []
    for it in m["items"]:
        exists, tagged = _look(it["kind"], it["id"])
        if exists:
            out.append({**it, "tagged": tagged})
    return out


def _counts(items: list[dict]) -> dict:
    n = {"studio": 0, "linkshell": 0, "collections": 0}
    for it in items:
        n[{"studio": "studio", "linkshell": "linkshell", "collection": "collections"}[it["kind"]]] += 1
    return n


def status() -> dict:
    with _lock:
        m = _read()
        present = _present(m) if m["state"] == "added" else []
        offer = m["state"] == "offered" and is_empty()   # only the first-run state pays for the emptiness check
        return {"state": m["state"], "can_offer": offer, "will_add": will_add(), "present": _counts([i for i in present if i["tagged"]]),
                "kept": len([i for i in present if not i["tagged"]]), "tag": content()["tag"]}


def add() -> dict:
    """Create the samples. Does nothing while earlier samples are still there. Returns what was created."""
    with _lock:
        m = _read()
        if m["state"] == "added" and any(i["tagged"] for i in _present(m)):
            return {"added": False, "reason": "already there", **status()}
        c, tag, items = content(), content()["tag"], []
        for s in c["studio"]:
            o = promptstore.create_studio(s["text"], s["title"], [tag])
            items.append({"kind": "studio", "id": o["id"]})
        data, _ = planmod.build(c["linkshell"])
        p = ls.import_json(data)
        pid = p["project"]["id"]
        ls.update(pid, {"tags": [tag]})   # the plan builder also marks projects as made over MCP; these are not
        items.append({"kind": "linkshell", "id": pid})
        col = co.create(c["collection"]["name"], c["collection"]["description"], [tag])
        for d in c["collection"]["documents"]:
            co.add_document(col["id"], d["name"], d["text"].encode("utf-8"))
        items.append({"kind": "collection", "id": col["id"]})
        _write({"state": "added", "items": items, "kinds": _counts(items)})
        return {"added": True, **status()}


def remove() -> dict:
    """Move the samples that are still there and still tagged to the Trash (30 days, restorable). An item the user already deleted is skipped;
    an item whose Sample tag the user removed is kept (that is the way to keep an edited sample)."""
    with _lock:
        m = _read()
        removed = {"studio": 0, "linkshell": 0, "collections": 0}
        kept = missing = 0
        for it in m["items"]:
            exists, tagged = _look(it["kind"], it["id"])
            if not exists:
                missing += 1
            elif not tagged:
                kept += 1
            elif it["kind"] == "studio" and promptstore.trash(it["id"], STUDIO_DIR):
                removed["studio"] += 1
            elif it["kind"] == "linkshell" and ls.trash(it["id"]):
                removed["linkshell"] += 1
            elif it["kind"] == "collection" and co.trash_collection(it["id"]):
                removed["collections"] += 1
        if m["state"] != "offered":
            _write({"state": "removed", "items": []})
        return {**status(), "removed": removed, "kept": kept, "missing": missing}   # this call's counts win over status()'s own "kept"


def dismiss() -> dict:
    """"No thanks": remember it. Never changes samples that were added."""
    with _lock:
        m = _read()
        if m["state"] == "offered":
            _write({"state": "dismissed", "items": []})
        return status()
