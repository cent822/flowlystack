"""Lattice, entity layer storage and validator. Standard library only.

The entity layer is user data and the source of truth. One file per run (a "batch"):

    PROMPTS_DIR/kgraph/batches/gb-<10 hex>.json
        {schema, id, ts, updated, by, via ("mcp" | "local"), note, run (opened by start_run), hidden, undone (0 or the time),
         entities: [{id, name, kind, key, aliases, note, merged}],
         edges: [{type ("mentions" | "related"), from, to, label, item, quote}]}

An entity id is `en-` + 10 hex. For `mentions`, `from` is an item id and `to` an entity id; for `related` both are entity ids. Every edge carries the
item it came from and a short quote, and the server checks that the quote really occurs in that item's text (whitespace, case and unicode form are
ignored). That check is the main guard against made-up entities. A new entity needs at least one verified `mentions` edge in the same call.

An entity that already exists is not created again: the later batch carries a small record with the same id (`merged: true`) holding only the alias or
note it adds, so undoing either batch never loses the other's data. Nothing here deletes or rewrites what another batch wrote. Agents only add; deleting
is the user's action on the page (`delete_batch`, `delete_entity`, both return what they removed so the page can offer Undo).

Every write takes the module lock and replaces the file atomically. Nothing here reads or changes the Library, Studio or Collections (the stores are
read through `Stores`, only to check that an item exists and a quote occurs in it).
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Callable

from . import kgraph_kinds as kinds
from .config import PROMPTS_DIR

SCHEMA = 1
KINDS = kinds.DEFAULT_SLUGS   # the ten built-in slugs; the live list (renamed, custom, deleted) is `kgraph_kinds.active()`
EDGE_TYPES = ("mentions", "related")
VIAS = ("mcp", "local")
MAX_ENTITIES_CALL = 200
MAX_EDGES_CALL = 400
MAX_ENTITIES_BATCH = 2000   # one run cannot grow without limit
MAX_EDGES_BATCH = 4000
MAX_READ = 2000             # item ids one batch remembers as read (a local-model run that found nothing in an item still marks it read)
MAX_NAME, MAX_ALIASES, MAX_NOTE, MAX_LABEL, MAX_QUOTE, MIN_QUOTE, MAX_BY, MAX_RUN_NOTE = 120, 8, 200, 60, 200, 8, 60, 200
RUN_IDLE = 3600             # a run closes after one hour without a call
REFUSED_SHOWN = 20

_LOCK = threading.RLock()
_GB = re.compile(r"^gb-[0-9a-f]{10}$")
_EN = re.compile(r"^en-[0-9a-f]{10}$")
_ITEM = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


class Invalid(Exception):
    """A call or request that is refused; the message is written for the agent or the user. `status` is the HTTP code the API uses."""

    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------- files

def _root(root) -> Path:
    return Path(root) if root is not None else Path(PROMPTS_DIR) / "kgraph"


def _dir(root) -> Path:
    return _root(root) / "batches"


def _path(bid: str, root) -> Path:
    return _dir(root) / f"{bid}.json"


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.stem + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _s(v, n: int) -> str:
    return " ".join(str(v).split())[:n] if isinstance(v, (str, int, float)) else ""


def _clean_entity(e) -> dict | None:
    if not isinstance(e, dict) or not _EN.match(str(e.get("id", ""))):
        return None
    name, kind = _s(e.get("name"), MAX_NAME), e.get("kind")
    if not name or not kinds.valid_slug(kind):   # any well-formed slug loads: a deleted or unknown kind must never drop an entity
        return None
    al = [a for a in (_s(a, MAX_NAME) for a in (e.get("aliases") if isinstance(e.get("aliases"), list) else [])) if a][:MAX_ALIASES]
    return {"id": e["id"], "name": name, "kind": kind, "key": norm_key(name, kind), "aliases": list(dict.fromkeys(al)), "note": _s(e.get("note"), MAX_NOTE),
            "merged": bool(e.get("merged"))}


def _clean_edge(e) -> dict | None:
    if not isinstance(e, dict) or e.get("type") not in EDGE_TYPES:
        return None
    frm, to, item, quote = str(e.get("from", "")), str(e.get("to", "")), str(e.get("item", "")), _s(e.get("quote"), MAX_QUOTE)
    if not (_ITEM.match(item) and quote and _EN.match(to) and (_EN.match(frm) if e["type"] == "related" else frm == item)):
        return None
    return {"type": e["type"], "from": frm, "to": to, "label": _s(e.get("label"), MAX_LABEL) if e["type"] == "related" else "", "item": item, "quote": quote}


def _clean_batch(d, bid: str | None = None) -> dict | None:
    """The batch as the module understands it, or None when the file is not one. Unknown fields are dropped, bad rows skipped."""
    if not isinstance(d, dict) or not _GB.match(str(d.get("id", ""))) or (bid is not None and d["id"] != bid):
        return None
    try:
        ts, upd, undone = float(d.get("ts") or 0), float(d.get("updated") or d.get("ts") or 0), float(d.get("undone") or 0)
    except (TypeError, ValueError):
        return None
    ents = [x for x in (_clean_entity(e) for e in (d.get("entities") if isinstance(d.get("entities"), list) else [])) if x]
    edges = [x for x in (_clean_edge(e) for e in (d.get("edges") if isinstance(d.get("edges"), list) else [])) if x]
    return {"schema": SCHEMA, "id": d["id"], "ts": ts, "updated": upd, "by": _s(d.get("by"), MAX_BY), "via": d.get("via") if d.get("via") in VIAS else "mcp",
            "note": _s(d.get("note"), MAX_RUN_NOTE), "run": bool(d.get("run")), "hidden": bool(d.get("hidden")), "undone": undone, "entities": ents, "edges": edges,
            "read": list(dict.fromkeys(x for x in (str(i) for i in (d.get("read") if isinstance(d.get("read"), list) else [])) if _ITEM.match(x)))[:MAX_READ]}


def _read(path: Path) -> dict | None:
    try:
        return _clean_batch(json.loads(path.read_text()), path.stem)
    except (OSError, ValueError):
        return None


def _all(root, include_undone: bool = True) -> list[dict]:
    """Every readable batch, oldest first (a damaged file is skipped, never rewritten)."""
    d = _dir(root)
    out = [b for b in (_read(p) for p in sorted(d.glob("gb-*.json"))) if b] if d.exists() else []
    out.sort(key=lambda b: (b["ts"], b["id"]))
    return out if include_undone else [b for b in out if not b["undone"]]


def damaged(root=None) -> list[str]:
    """File names in the batches folder that could not be read (the user can look at them; nothing here touches them)."""
    d = _dir(root)
    return sorted(p.name for p in d.glob("gb-*.json") if _read(p) is None) if d.exists() else []


def _taken(root) -> set[str]:
    return {x for b in _all(root) for x in [b["id"]] + [e["id"] for e in b["entities"]]}


def _new_id(prefix: str, taken: set[str]) -> str:
    while True:
        i = prefix + uuid.uuid4().hex[:10]
        if i not in taken:
            taken.add(i)
            return i


# ---------------------------------------------------------------- normalising

def norm_text(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s or "").casefold().split())


def norm_name(s: str) -> str:
    return norm_text(s).strip(" .,;:!?\"'`()[]{}<>")


def norm_key(name: str, kind: str) -> str:
    return f"{norm_name(name)}|{kind}"


# ---------------------------------------------------------------- reading the stores (read-only)

class Stores:
    """Where an item's text comes from. `texts_of` returns the readings of an item the quote may occur in (None: no such item). Folders are optional
    so tests use temp ones; the defaults are the real stores. Nothing is written."""

    def __init__(self, library_dir: Path | None = None, studio_dir: Path | None = None, collections_root: Path | None = None):
        self.library_dir, self.studio_dir, self.collections_root = library_dir, studio_dir, collections_root
        self._cache: dict[str, list[str] | None] = {}
        self._loaded: dict[str, dict[str, dict]] = {}   # store -> id -> prompt, read once per instance (load_all scans every file)

    def _prompts(self, which: str) -> dict:
        if which not in self._loaded:
            from . import promptstore as ps
            root = (self.studio_dir or ps.STUDIO_DIR) if which == "studio" else self.library_dir
            self._loaded[which] = {o["id"]: o for o in ps.load_all(root)}
        return self._loaded[which]

    def texts_of(self, item_id: str) -> list[str] | None:
        if item_id not in self._cache:
            self._cache[item_id] = self._read(item_id)
        return self._cache[item_id]

    def exists(self, item_id: str) -> bool:
        """Does the item exist (cheaper than reading its text; used to mark an edge whose source vanished)."""
        if item_id in self._cache:
            return self._cache[item_id] is not None
        if item_id.startswith("kd-"):
            from . import collections as co
            return co.get_document(item_id, self.collections_root) is not None
        return item_id in self._prompts("studio" if item_id.startswith("ps-") else "library")

    def _read(self, iid: str) -> list[str] | None:
        from . import collections as co
        if iid.startswith("kd-"):
            doc = co.read_text(iid, self.collections_root)
            if not doc:
                return None
            joined = "\n\n".join(p.get("text", "") for p in co.passages(iid, self.collections_root))
            return [t for t in (doc.get("text") or "", joined) if t.strip()] or [""]
        o = self._prompts("studio" if iid.startswith("ps-") else "library").get(iid)
        return [o.get("text") or ""] if o else None


# ---------------------------------------------------------------- the index (what the page and the tools read)

def entities_index(root=None, *, include_hidden: bool = False, item_exists: Callable[[str], bool] | None = None) -> dict:
    """The live entity layer: `entities` {id: {id, name, kind, key, aliases, note, batches}}, `edges` [{... batch, by, via, source_gone}], `by_key`.
    Undone batches are always left out, hidden ones unless asked. Entities merge across batches by id (aliases joined up to the limit, the first
    note wins); an edge whose entity is gone is left out. `item_exists` marks edges whose source item vanished (`source_gone`; the quote stays as written)."""
    batches = [b for b in _all(root, include_undone=False) if include_hidden or not b["hidden"]]
    ents: dict[str, dict] = {}
    for b in batches:
        for e in b["entities"]:
            cur = ents.get(e["id"])
            if cur is None:
                ents[e["id"]] = {"id": e["id"], "name": e["name"], "kind": e["kind"], "key": e["key"], "aliases": list(e["aliases"]), "note": e["note"],
                                 "batches": [b["id"]]}
            else:
                cur["batches"].append(b["id"])
                cur["aliases"] = list(dict.fromkeys(cur["aliases"] + e["aliases"]))[:MAX_ALIASES]
                cur["note"] = cur["note"] or e["note"]
    edges, seen = [], set()
    for b in batches:
        for e in b["edges"]:
            if e["to"] not in ents or (e["type"] == "related" and e["from"] not in ents):
                continue
            k = _edge_key(e)
            if k in seen:
                continue
            seen.add(k)
            edges.append({**e, "batch": b["id"], "by": b["by"], "via": b["via"], "source_gone": bool(item_exists and not item_exists(e["item"]))})
    return {"entities": ents, "edges": edges, "by_key": {e["key"]: i for i, e in ents.items()}}


def _edge_key(e: dict) -> tuple:
    return (e["type"], e["from"], e["to"], norm_text(e.get("label", "")), e["item"])


# ---------------------------------------------------------------- batches (listing and control)

def _summary(b: dict) -> dict:
    return {"id": b["id"], "ts": b["ts"], "updated": b["updated"], "by": b["by"], "via": b["via"], "note": b["note"], "entities": sum(1 for e in b["entities"] if not e["merged"]),
            "merged": sum(1 for e in b["entities"] if e["merged"]), "edges": len(b["edges"]), "read": len(b["read"]), "hidden": b["hidden"], "undone": b["undone"], "run": b["run"],
            "open": b["run"] and not b["undone"] and _now() - b["updated"] <= RUN_IDLE}


def list_batches(root=None) -> list[dict]:
    """Newest first; includes hidden and undone ones (the page shows them with their state)."""
    return [_summary(b) for b in reversed(_all(root))]


def get_batch(bid: str, root=None) -> dict | None:
    return _read(_path(bid, root)) if _GB.match(bid or "") else None


def _need(bid: str, root) -> dict:
    b = get_batch(bid, root)
    if b is None:
        raise Invalid("That batch is not in the list any more.", 404)
    return b


def hide_batch(bid: str, hidden: bool = True, root=None) -> dict:
    with _LOCK:
        b = _need(bid, root)
        b["hidden"] = bool(hidden)
        _write(_path(bid, root), b)
        return _summary(b)


def undo_batch(bid: str, root=None) -> dict:
    """Mark the whole batch undone: it disappears everywhere and nothing is deleted (`reinstate_batch` brings it back)."""
    with _LOCK:
        b = _need(bid, root)
        if b["undone"]:
            raise Invalid("That was already undone.", 409)
        b["undone"] = _now()
        _write(_path(bid, root), b)
        return _summary(b)


def reinstate_batch(bid: str, root=None) -> dict:
    with _LOCK:
        b = _need(bid, root)
        if not b["undone"]:
            raise Invalid("That batch is not undone.", 409)
        b["undone"] = 0
        _write(_path(bid, root), b)
        return _summary(b)


def delete_batch(bid: str, root=None) -> dict:
    """Remove the batch file for good and return the raw batch, so the page can offer Undo through `restore_batch`."""
    with _LOCK:
        b = _need(bid, root)
        _path(bid, root).unlink(missing_ok=True)
        return b


def restore_batch(raw, root=None) -> dict:
    """Put back a batch `delete_batch` returned. Shape is re-checked (ids, kinds, lengths); quotes stay as written. An id that is taken is refused."""
    with _LOCK:
        b = _clean_batch(raw)
        if b is None:
            raise Invalid("That is not a batch FlowlyStack can restore.")
        if _path(b["id"], root).exists():
            raise Invalid("That batch is already back.", 409)
        live = [e for x in _all(root, include_undone=False) for e in x["entities"]]
        ids, keys = {e["id"] for e in live}, {e["key"]: e["id"] for e in live}
        for e in b["entities"]:   # an id shared with a live entity is a merge and fine; the same name under another id is a clash
            if e["id"] not in ids and keys.get(e["key"], e["id"]) != e["id"]:
                raise Invalid("An entity with the same name now exists under another id, so this batch cannot be restored as it was.", 409)
        _write(_path(b["id"], root), b)
        return _summary(b)


def delete_entity(eid: str, root=None) -> dict:
    """Remove one entity and every edge that touches it from all batches. Returns {entity_id, parts: [{batch, entities, edges}]} with the raw rows
    removed, for `restore_entity`. Batches left empty stay (the user deletes them as a run)."""
    if not _EN.match(eid or ""):
        raise Invalid("That is not an entity id.", 404)
    with _LOCK:
        parts = []
        for b in _all(root):
            ents = [e for e in b["entities"] if e["id"] == eid]
            edges = [e for e in b["edges"] if e["to"] == eid or e["from"] == eid]
            if not ents and not edges:
                continue
            parts.append({"batch": b["id"], "entities": ents, "edges": edges})
            b["entities"] = [e for e in b["entities"] if e["id"] != eid]
            b["edges"] = [e for e in b["edges"] if e not in edges]
            _write(_path(b["id"], root), b)
        if not any(p["entities"] for p in parts):
            raise Invalid("That entity is not in the list any more.", 404)
        return {"entity_id": eid, "parts": parts}


def restore_entity(removed, root=None) -> int:
    """Undo of `delete_entity`: put the rows back into the batches they came from (a batch that is gone is skipped). Returns the rows restored."""
    n = 0
    with _LOCK:
        for part in removed.get("parts", []) if isinstance(removed, dict) else []:
            b = get_batch(str(part.get("batch", "")), root) if isinstance(part, dict) else None
            if not b:
                continue
            have = {e["id"] for e in b["entities"]}
            for e in part.get("entities", []):
                c = _clean_entity(e)
                if c and c["id"] not in have:
                    b["entities"].append(c)
                    n += 1
            have_e = {_edge_key(e) for e in b["edges"]}
            for e in part.get("edges", []):
                c = _clean_edge(e)
                if c and _edge_key(c) not in have_e:
                    b["edges"].append(c)
                    n += 1
            _write(_path(b["id"], root), b)
    return n


def covered_items(root=None) -> set[str]:
    """Item ids the live entity layer has handled: those with an edge, and those a run read (a local-model run marks an item read even when it found
    nothing in it, so the next run does not ask again). Hidden batches count, undone ones do not."""
    ix = entities_index(root, include_hidden=True)
    return {e["item"] for e in ix["edges"]} | {i for b in _all(root, include_undone=False) for i in b["read"]}


def mark_read(bid: str, item_ids: list, root=None) -> None:
    with _LOCK:
        b = _need(bid, root)
        b["read"] = list(dict.fromkeys(b["read"] + [str(i) for i in item_ids if _ITEM.match(str(i))]))[:MAX_READ]
        _write(_path(bid, root), b)


# ---------------------------------------------------------------- adding (the validator)

def start_run(by: str, note: str = "", via: str = "mcp", root=None) -> dict:
    """Open an empty run; calls that carry its id are one batch (one Undo). It closes after RUN_IDLE seconds without a call."""
    by, via = _s(by, MAX_BY), via if via in VIAS else "mcp"
    with _LOCK:
        bid = _new_id("gb-", _taken(root))
        t = _now()
        b = {"schema": SCHEMA, "id": bid, "ts": t, "updated": t, "by": by, "via": via, "note": _s(note, MAX_RUN_NOTE), "run": True, "hidden": False, "undone": 0,
             "entities": [], "edges": [], "read": []}
        _write(_path(bid, root), b)
        return _summary(b)


def _plain(v, field: str, n: int, *, need: bool = False) -> str:
    if v is not None and not isinstance(v, str):
        raise Invalid(f"{field} must be text.")
    s = " ".join((v or "").split())
    if need and not s:
        raise Invalid(f"{field} is empty.")
    if len(s) > n:
        raise Invalid(f"{field} is {len(s)} characters; the limit is {n}.")
    return s


def add_batch(payload: dict, *, by: str, via: str = "mcp", note: str = "", run: str | None = None, strict: bool = True, root=None,
              stores: Stores | None = None) -> dict:
    """Validate and store `payload` {entities: [{name, kind, aliases?, note?}], edges: [{type, from, to, label?, item, quote}]}.

    strict (the MCP route): the first problem refuses the whole call, naming it, and nothing is written. Not strict (the local-model route): a failing
    entity or edge is dropped and counted, the rest is stored. Either way, an edge needs a real item and a quote that occurs in it, and a new entity needs
    a verified `mentions` edge in the same call. Returns {batch, created, merged, edges_added, edges_duplicate, refused_count, refused: [messages]}."""
    if not isinstance(payload, dict):
        raise Invalid("Send an object with `entities` and `edges`.")
    ents_in, edges_in = payload.get("entities") or [], payload.get("edges") or []
    if not isinstance(ents_in, list) or not isinstance(edges_in, list):
        raise Invalid("`entities` and `edges` must be lists.")
    if not ents_in and not edges_in:
        raise Invalid("Nothing to add: send at least one entity or edge.")
    if len(ents_in) > MAX_ENTITIES_CALL:
        raise Invalid(f"{len(ents_in)} entities in one call; the limit is {MAX_ENTITIES_CALL}. Split them over several calls (use a run to keep one Undo).")
    if len(edges_in) > MAX_EDGES_CALL:
        raise Invalid(f"{len(edges_in)} edges in one call; the limit is {MAX_EDGES_CALL}. Split them over several calls (use a run to keep one Undo).")
    by, via = _s(by, MAX_BY), via if via in VIAS else "mcp"
    stores = stores or Stores()
    refused: list[str] = []

    def refuse(msg: str) -> None:
        if strict:
            raise Invalid(msg)
        refused.append(msg)

    with _LOCK:
        live = entities_index(root, include_hidden=True)
        known_key, known_edges = dict(live["by_key"]), {_edge_key(e) for e in live["edges"]}
        taken = _taken(root)

        # 1. entities: clean, then match by key against the call itself and the live layer
        new: dict[str, dict] = {}        # key -> record this call creates
        merges: dict[str, dict] = {}     # key -> {id, record} for existing entities this call adds an alias or note to
        in_call: dict[str, str] = {}     # key -> id (new or existing)
        names: dict[str, set] = {}       # normalised name or alias -> entity ids, for resolving edge references
        for n, e in enumerate(ents_in, 1):
            where = f"entity {n}"
            try:
                if not isinstance(e, dict):
                    raise Invalid(f"{where} must be an object {{name, kind}}.")
                name = _plain(e.get("name"), f"{where} name", MAX_NAME, need=True)
                where = f"entity {n} ({name})"
                kind = kinds.resolve(e.get("kind"), root)   # a label or slug of an active kind; stored as the slug
                if kind is None:
                    raise Invalid(f"{where}: kind must be one of {', '.join(kinds.labels(root))}.")
                al_in = e.get("aliases") or []
                if not isinstance(al_in, list):
                    raise Invalid(f"{where}: aliases must be a list.")
                if len(al_in) > MAX_ALIASES:
                    raise Invalid(f"{where}: {len(al_in)} aliases; the limit is {MAX_ALIASES}.")
                aliases = list(dict.fromkeys(a for a in (_plain(a, f"{where} alias", MAX_NAME) for a in al_in) if a and norm_name(a) != norm_name(name)))
                text_note = _plain(e.get("note"), f"{where} note", MAX_NOTE)
            except Invalid as err:
                refuse(str(err))
                continue
            key = norm_key(name, kind)
            if key in in_call:    # the same entity twice in one call: fold into the first
                rec = new.get(key) or merges[key]["rec"]
                rec["aliases"] = list(dict.fromkeys(rec["aliases"] + aliases))[:MAX_ALIASES]
                rec["note"] = rec["note"] or text_note
            elif key in known_key:
                have = live["entities"][known_key[key]]
                add_al = [a for a in aliases if norm_name(a) not in {norm_name(x) for x in [have["name"]] + have["aliases"]}][:max(0, MAX_ALIASES - len(have["aliases"]))]
                add_note = text_note if (text_note and not have["note"]) else ""
                rec = {"id": have["id"], "name": have["name"], "kind": kind, "key": key, "aliases": add_al, "note": add_note, "merged": True}
                merges[key] = {"id": have["id"], "rec": rec}
                in_call[key] = have["id"]
            else:
                rec = {"id": _new_id("en-", taken), "name": name, "kind": kind, "key": key, "aliases": aliases, "note": text_note, "merged": False}
                new[key] = rec
                in_call[key] = rec["id"]
            for nm in [name] + aliases:
                names.setdefault(norm_name(nm), set()).add(in_call[key])
        live_names: dict[str, set] = {}  # existing entities by name: used only when this call does not declare the name itself
        for i, e in live["entities"].items():
            for nm in [e["name"]] + e["aliases"]:
                live_names.setdefault(norm_name(nm), set()).add(i)
        valid_ids = {r["id"] for r in new.values()} | {m["id"] for m in merges.values()} | set(live["entities"])

        def entity_ref(ref, where: str) -> str:
            if not isinstance(ref, str) or not ref.strip():
                raise Invalid(f"{where}: the entity is missing.")
            if _EN.match(ref.strip()):
                if ref.strip() not in valid_ids:
                    raise Invalid(f"{where}: there is no entity with id {ref.strip()}.")
                return ref.strip()
            ids = names.get(norm_name(ref)) or live_names.get(norm_name(ref), set())
            if not ids:
                raise Invalid(f"{where}: no entity is named \"{_s(ref, 60)}\" (add it in `entities` in this call, or use its id).")
            if len(ids) > 1:
                raise Invalid(f"{where}: \"{_s(ref, 60)}\" matches more than one entity (different kinds); use the id instead.")
            return next(iter(ids))

        # 2. edges: type, endpoints, item exists, quote occurs in it
        edges: list[dict] = []
        seen_edges, dup = set(known_edges), 0
        mentioned: set[str] = set()
        for n, e in enumerate(edges_in, 1):
            where = f"edge {n}"
            try:
                if not isinstance(e, dict):
                    raise Invalid(f"{where} must be an object.")
                typ = e.get("type")
                if typ not in EDGE_TYPES:
                    raise Invalid(f"{where}: type must be \"mentions\" or \"related\".")
                item = _plain(e.get("item"), f"{where} item", 120, need=True)
                if not _ITEM.match(item):
                    raise Invalid(f"{where}: item is not an item id.")
                quote = _plain(e.get("quote"), f"{where} quote", MAX_QUOTE, need=True)
                if len(norm_text(quote)) < MIN_QUOTE:
                    raise Invalid(f"{where}: the quote is too short to prove anything (at least {MIN_QUOTE} characters).")
                label = _plain(e.get("label"), f"{where} label", MAX_LABEL)
                if typ == "mentions":
                    frm = _plain(e.get("from"), f"{where} from", 120) or item
                    if frm != item:
                        raise Invalid(f"{where}: a `mentions` edge goes from the item it was found in (leave `from` out or repeat `item`).")
                    to, label = entity_ref(e.get("to"), where), ""
                else:
                    if not label:
                        raise Invalid(f"{where}: a `related` edge needs a label (what the relationship is, up to {MAX_LABEL} characters).")
                    frm, to = entity_ref(e.get("from"), where), entity_ref(e.get("to"), where)
                    if frm == to:
                        raise Invalid(f"{where}: an entity cannot be related to itself.")
                texts = stores.texts_of(item)
                if texts is None:
                    raise Invalid(f"{where}: item {item} does not exist in the Library, Studio or Collections.")
                q = norm_text(quote)
                if not any(q in norm_text(t) for t in texts):
                    raise Invalid(f"{where}: the quote does not occur in item {item}. Copy it exactly from the item's text (spacing and capital letters are ignored).")
            except Invalid as err:
                refuse(str(err))
                continue
            rec = {"type": typ, "from": frm, "to": to, "label": label, "item": item, "quote": quote}
            k = _edge_key(rec)
            if k in seen_edges:
                dup += 1
                continue
            seen_edges.add(k)
            edges.append(rec)
            if typ == "mentions":
                mentioned.add(to)

        # 3. a new entity must be backed by a verified mention
        dead: set[str] = set()
        for key, rec in list(new.items()):
            if rec["id"] not in mentioned:
                refuse(f"entity \"{rec['name']}\" has no verified `mentions` edge in this call (every new entity needs the item it was found in and a quote).")
                dead.add(rec["id"])
                del new[key]
        edges = [e for e in edges if e["to"] not in dead and e["from"] not in dead]
        created, merged = list(new.values()), [m["rec"] for m in merges.values() if m["rec"]["aliases"] or m["rec"]["note"] or any(e["to"] == m["id"] or e["from"] == m["id"] for e in edges)]
        carried = {r["id"] for r in created + merged}
        for eid in dict.fromkeys(x for e in edges for x in (e["to"], e["from"]) if x in live["entities"]):
            if eid not in carried:   # an edge points at an entity an earlier batch made: carry it, so undoing that batch does not orphan this edge
                le = live["entities"][eid]
                merged.append({"id": eid, "name": le["name"], "kind": le["kind"], "key": le["key"], "aliases": [], "note": "", "merged": True})
        if not created and not merged and not edges:
            return {"batch": run or None, "created": 0, "merged": 0, "edges_added": 0, "edges_duplicate": dup, "refused_count": len(refused),
                    "refused": refused[:REFUSED_SHOWN], "stored": False}

        # 4. store: into the run, or a new one-call batch
        t = _now()
        if run:
            b = get_batch(run, root)
            if b is None or not b["run"]:
                raise Invalid("That run does not exist. Start one with graph_start_run.", 404)
            if b["undone"]:
                raise Invalid("That run was undone by the user. Start a new run only if they ask for it.", 409)
            if t - b["updated"] > RUN_IDLE:
                raise Invalid("That run closed after an hour without a call. Start a new run.", 409)
            if b["by"] != by or b["via"] != via:
                raise Invalid("That run belongs to someone else.", 403)
            if len(b["entities"]) + len(created) + len(merged) > MAX_ENTITIES_BATCH or len(b["edges"]) + len(edges) > MAX_EDGES_BATCH:
                raise Invalid(f"This run is full ({MAX_ENTITIES_BATCH} entities, {MAX_EDGES_BATCH} edges). Start a new run.", 409)
        else:
            b = {"schema": SCHEMA, "id": _new_id("gb-", taken), "ts": t, "updated": t, "by": by, "via": via, "note": _s(note, MAX_RUN_NOTE), "run": False,
                 "hidden": False, "undone": 0, "entities": [], "edges": [], "read": []}
        b["entities"] += created + merged
        b["edges"] += edges
        b["updated"] = t
        _write(_path(b["id"], root), b)
        return {"batch": b["id"], "created": len(created), "merged": len(merged), "edges_added": len(edges), "edges_duplicate": dup,
                "refused_count": len(refused), "refused": refused[:REFUSED_SHOWN], "stored": True}
