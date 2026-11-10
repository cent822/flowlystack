"""Collections storage: named sets of imported documents. Plain files, standard library only
(the parsers import `pypdf` only for a PDF). Owns everything under `PROMPTS_DIR/collections/`; the Library, Studio and Linkshell files
are never touched.

    collections/
      docs/kd-<12 hex>/        file.<ext> (the original), doc.json, passages.json (a cache, rebuilt by `read_document`)
      col-<12 hex>/            collection.json {documents: [kd ids], ...}, chats/
      .trash/<month>/col-…     deleted collections; .trash/docs/kd-… holds deleted documents

A document is stored once and can belong to several collections (the membership list lives in the collection). Deleting goes to the
Trash, never straight to nothing: a collection takes with it the documents that belong to no other collection (stamped `deleted_with`,
brought back by restoring the collection); a document removed from its last collection is trashed on its own. Every write takes the
module lock and its own temp name, like `linkshell.py`.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .config import PROMPTS_DIR
from .rag import parsers

SCHEMA_VERSION = 1
STATUSES = ("waiting", "reading", "indexing", "ready", "failed")
_COL = re.compile(r"^col-[0-9a-f]{12}$")
_DOC = re.compile(r"^kd-[0-9a-f]{12}$")


class Invalid(ValueError):
    """The request breaks a rule (empty name, unknown collection or document). The message says which."""


class Conflict(Invalid):
    """The stored file changed since the caller read it (a save made from an old copy). The API answers 409."""


_LOCK = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def run(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return run


# ---------- files ----------

def _tmp(path: Path) -> Path:
    return path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_json(path: Path, obj) -> None:
    _write_bytes(path, json.dumps(obj, ensure_ascii=False, indent=2).encode())


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else Path(PROMPTS_DIR) / "collections"


def _now() -> float:
    return time.time()


def _col_dir(cid: str, root) -> Path | None:
    if not _COL.match(cid or ""):
        return None
    d = _root(root) / cid
    return d if (d / "collection.json").is_file() else None


def _doc_dir(did: str, root) -> Path | None:
    if not _DOC.match(did or ""):
        return None
    d = _root(root) / "docs" / did
    return d if (d / "doc.json").is_file() else None


def _trashed_col(cid: str, root) -> Path | None:
    return next(iter((_root(root) / ".trash").glob(f"*/{cid}")), None) if _COL.match(cid or "") else None


def _trashed_doc(did: str, root) -> Path | None:
    d = _root(root) / ".trash" / "docs" / did
    return d if _DOC.match(did or "") and (d / "doc.json").is_file() else None


def _taken_ids(root) -> set[str]:
    r = _root(root)
    taken = set()
    for pattern in ("col-*", ".trash/*/col-*", "docs/kd-*", ".trash/docs/kd-*"):
        taken |= {p.name for p in r.glob(pattern) if p.is_dir()}
    return taken


def _new_id(prefix: str, root) -> str:
    taken = _taken_ids(root)
    while True:
        i = prefix + uuid.uuid4().hex[:12]
        if i not in taken:
            return i


def _tags(v) -> list[str]:
    return list(dict.fromkeys(str(t).strip() for t in (v or []) if str(t).strip()))


def _name(v, what="name") -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if not s:
        raise Invalid(f"The {what} cannot be empty")
    if len(s) > 120:
        raise Invalid(f"The {what} is longer than 120 characters")
    return s


# ---------- collections ----------

@_locked
def create(name: str, description: str = "", tags: list[str] | None = None, root=None) -> dict:
    cid = _new_id("col-", root)
    now = _now()
    c = {"id": cid, "kind": "collection", "schema_version": SCHEMA_VERSION, "ts": now, "name": _name(name),
         "description": str(description or "").strip()[:2000], "tags": _tags(tags), "star": False, "documents": [], "updated_at": now}
    _write_json(_root(root) / cid / "collection.json", c)   # last write: the collection exists from here on
    return c


def get(cid: str, root=None) -> dict | None:
    d = _col_dir(cid, root)
    return _read_json(d / "collection.json") if d else None


@_locked
def update(cid: str, root=None, **fields) -> dict | None:
    """Change name, description, tags or star. Unknown fields are ignored."""
    d = _col_dir(cid, root)
    c = _read_json(d / "collection.json") if d else None
    if not c:
        return None
    if "name" in fields:
        c["name"] = _name(fields["name"])
    if "description" in fields:
        c["description"] = str(fields["description"] or "").strip()[:2000]
    if "tags" in fields:
        c["tags"] = _tags(fields["tags"])
    if "star" in fields:
        c["star"] = bool(fields["star"])
    c["updated_at"] = _now()
    _write_json(d / "collection.json", c)
    return c


BUILTIN_NAME = "My prompts"


def builtin_prefs(root=None) -> dict:
    """The built-in My prompts collection is virtual, but the user may rename it and star it: {name, star}, kept in `builtin.json`."""
    d = _read_json(_root(root) / "builtin.json") or {}
    name = d.get("name") if isinstance(d.get("name"), str) and d["name"].strip() else BUILTIN_NAME
    return {"name": name, "star": bool(d.get("star"))}


def builtin_update(root=None, **fields) -> dict:
    """Change the name and/or star of My prompts (an empty name is refused; other fields are not accepted)."""
    cur = builtin_prefs(root)
    if fields.get("name") is not None:
        cur["name"] = _name(fields["name"])
    if fields.get("star") is not None:
        cur["star"] = bool(fields["star"])
    _write_json(_root(root) / "builtin.json", cur)
    return cur


def _collection_ids(root) -> list[str]:
    r = _root(root)
    return sorted(p.name for p in r.glob("col-*") if (p / "collection.json").is_file()) if r.is_dir() else []


def collections_of(did: str, root=None) -> list[str]:
    return [cid for cid in _collection_ids(root) if did in (get(cid, root) or {}).get("documents", [])]


def _summary(c: dict, root) -> dict:
    docs = documents(c["id"], root)
    working = [x for x in docs if x["status"] in ("waiting", "reading", "indexing")]
    ready = sum(x["status"] == "ready" for x in docs)
    failed = sum(x["status"] == "failed" for x in docs)
    if not docs:
        status = "empty"
    elif working:
        status = "preparing"
    elif ready:
        status = "ready"
    else:
        status = "failed"
    live = ready + len(working)
    return {**c, "documents": len(docs), "passages": sum(x["passages"] for x in docs if x["status"] == "ready"), "failed": failed,
            "status": status, "progress": (ready / live) if live else 0.0}


def list_collections(root=None, q: str = "", tags: list[str] | None = None, show: str = "all", sort: str = "edited", desc: bool = True,
                     page: int = 1, page_size: int = 50, only: list[str] | None = None) -> dict:
    """The home list (without the built-in My prompts row, which the API adds). `show`: all | ready | preparing | starred. `tags` filters AND
    together; the `tags` in the result count what each tag would give if added to the current filters. `only` (ids from the search engine, best
    match first) replaces `q`, and `sort="relevance"` keeps that order."""
    items = [_summary(c, root) for c in (get(cid, root) for cid in _collection_ids(root)) if c]
    if only is not None:
        rank = {cid: n for n, cid in enumerate(only)}
        items = [i for i in items if i["id"] in rank]
    else:
        rank = {}
        words = (q or "").lower().split()
        items = [i for i in items if all(w in " ".join([i["name"], i["description"], *i["tags"]]).lower() for w in words)]
    shows = {"all": lambda i: True, "ready": lambda i: i["status"] == "ready", "preparing": lambda i: i["status"] == "preparing",
             "starred": lambda i: i["star"]}
    items = [i for i in items if shows.get(show, shows["all"])(i)]
    want = list(tags or [])
    base = [i for i in items if all(t in i["tags"] for t in want)]
    counts = {t: sum(1 for i in items if t in i["tags"] and all(w in i["tags"] for w in want)) for t in {t for i in items for t in i["tags"]} | set(want)}
    keys = {"name": lambda i: i["name"].lower(), "documents": lambda i: i["documents"], "edited": lambda i: i["updated_at"],
            "relevance": lambda i: rank.get(i["id"], 0)}
    base.sort(key=keys.get(sort, keys["edited"]), reverse=desc and sort != "relevance")
    page, page_size = max(1, page), max(1, page_size)
    return {"items": base[(page - 1) * page_size: page * page_size], "total": len(base), "page": page, "page_size": page_size, "tags": counts}


def summary(cid: str, root=None) -> dict | None:
    c = get(cid, root)
    return _summary(c, root) if c else None


# ---------- documents ----------

def _safe_name(name: str) -> str:
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().lstrip(".")
    return base[:200] or "untitled"


def _doc_row(d: dict) -> dict:
    return {k: d.get(k) for k in ("id", "name", "type", "size", "sha256", "status", "error", "warnings", "units", "passages", "ts", "updated_at", "renamed")}


def get_document(did: str, root=None) -> dict | None:
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    return {**_doc_row(doc), "collections": collections_of(did, root)} if doc else None


def documents(cid: str, root=None) -> list[dict]:
    """The documents of a collection, in the order they were added, each with its status. Ids that no longer exist are skipped."""
    c = get(cid, root)
    rows = []
    for did in (c or {}).get("documents", []):
        d = _doc_dir(did, root)
        doc = _read_json(d / "doc.json") if d else None
        if doc:
            rows.append(_doc_row(doc))
    return rows


def membership(root=None) -> dict[str, list[str]]:
    """document id -> ids of the live collections it is in, from one pass over the collections."""
    member: dict[str, list[str]] = {}
    for cid in _collection_ids(root):
        for did in (get(cid, root) or {}).get("documents", []):
            member.setdefault(did, []).append(cid)
    return member


def all_documents(root=None) -> list[dict]:
    """Every live document that belongs to at least one live collection, with the collections it is in (for the indexer)."""
    member = membership(root)
    out = []
    for did, cids in sorted(member.items()):
        d = _doc_dir(did, root)
        doc = _read_json(d / "doc.json") if d else None
        if doc:
            out.append({**_doc_row(doc), "collections": cids})
    return out


def passages(did: str, root=None) -> list[dict]:
    d = _doc_dir(did, root)
    return (_read_json(d / "passages.json") or []) if d else []


def passages_stamp(did: str, root=None) -> str:
    """Changes whenever the passages were (re)built, and only then (status changes do not touch it): the indexer's change signal."""
    d = _doc_dir(did, root)
    try:
        return str((d / "passages.json").stat().st_mtime_ns) if d else ""
    except OSError:
        return ""


def file_path(did: str, root=None) -> Path | None:
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    p = d / doc["file"] if doc else None
    return p if p and p.is_file() else None


@_locked
def _set(did: str, root, **fields) -> dict | None:
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    if not doc:
        return None
    doc.update(fields)
    doc["updated_at"] = _now()
    _write_json(d / "doc.json", doc)
    return doc


@_locked
def set_status(did: str, status: str, error: str = "", root=None) -> bool:
    """For the indexer: waiting | reading | indexing | ready | failed (with the reason)."""
    if status not in STATUSES:
        raise Invalid(f"Unknown status {status!r}")
    return _set(did, root, status=status, error=error if status == "failed" else "") is not None


@_locked
def read_document(did: str, root=None) -> dict | None:
    """(Re)parse the stored file into `passages.json`. Success leaves the document `waiting` for the indexer; a file that cannot be read
    becomes `failed` with the reason, and never raises, so one bad file cannot stop the others."""
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    if not doc:
        return None
    try:
        kind = doc["type"]
        if kind not in parsers.KINDS.values():
            raise parsers.ParseError("This file type is not supported (Markdown, text, PDF, JSON and JSONL are)")
        res = parsers.parse(kind, (d / doc["file"]).read_bytes())
    except parsers.ParseError as e:
        _write_json(d / "passages.json", [])
        return _set(did, root, status="failed", error=str(e), units=0, passages=0, warnings=[])
    except OSError as e:
        return _set(did, root, status="failed", error=f"The stored file cannot be read ({e.strerror or e})", units=0, passages=0, warnings=[])
    _write_json(d / "passages.json", res["passages"])
    return _set(did, root, status="waiting", error="", units=res["units"], passages=len(res["passages"]), warnings=res["warnings"])


EDIT_MAX = 2_000_000    # bytes: a bigger text file opens read-only in the editor (the browser would struggle, and a passage list that long means nothing)
EDITABLE = ("markdown", "text", "json", "jsonl")


def _text_of(d: Path, doc: dict) -> str | None:
    try:
        return (d / doc["file"]).read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


@_locked
def read_text(did: str, root=None) -> dict | None:
    """What the viewer shows: the stored file as text, whether it can be edited, and the sha the next save must quote. A PDF (or a file that is not
    UTF-8, or one over `EDIT_MAX`) is read-only; a PDF's `text` is its indexed passages joined, never the binary."""
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    if not doc:
        return None
    kind, size = doc.get("type"), int(doc.get("size") or 0)
    base = {**_doc_row(doc), "collections": collections_of(did, root), "editable": False, "reason": "", "text": ""}
    if kind == "pdf":
        base["text"] = "\n\n".join(p.get("text", "") for p in (_read_json(d / "passages.json") or []))
        base["reason"] = "A PDF cannot be edited here; the text shown is what was read from it."
    elif kind not in EDITABLE:
        base["reason"] = "This file type cannot be edited here."
    elif size > EDIT_MAX:
        base["reason"] = f"This file is over {EDIT_MAX // 1_000_000} MB, too big to edit here."
    else:
        text = _text_of(d, doc)
        if text is None:
            base["reason"] = "The stored file is not readable as UTF-8 text."
        else:
            base.update(text=text, editable=True)
    return base


@_locked
def rename_document(did: str, name: str, root=None) -> dict | None:
    """Change a document's display name (the stored file, its type and its text are untouched). `renamed` puts the name into the indexing signature,
    so the keyword index gets the new title on the next pass; documents never renamed keep their signature, so nothing is re-indexed for them."""
    if not _doc_dir(did, root):
        return None
    _set(did, root, name=_name(name), renamed=True)
    return get_document(did, root)


@_locked
def write_text(did: str, text: str, base_sha: str, root=None) -> dict | None:
    """Replace a text document's stored file and read it again (the indexer then re-embeds it, when a model is set). `base_sha` is the sha the
    caller read: a different one means the file changed meanwhile (`Conflict`). A PDF or an unsupported file is refused. Text that no longer parses
    (broken JSON, say) is still saved: the document becomes `failed` with the reason, and saving again recovers it. Returns the new `read_text`."""
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    if not doc:
        return None
    if doc.get("type") not in EDITABLE:
        raise Invalid("This file type cannot be edited here")
    if not isinstance(text, str):
        raise Invalid("The text must be a string")
    data = text.encode("utf-8")
    if len(data) > EDIT_MAX:
        raise Invalid(f"The text is over {EDIT_MAX // 1_000_000} MB")
    if base_sha != doc.get("sha256"):
        raise Conflict("This document changed since you opened it. Reload it to see the new text.")
    _write_bytes(d / doc["file"], data)
    _set(did, root, size=len(data), sha256=hashlib.sha256(data).hexdigest(), status="reading", error="", warnings=[])
    read_document(did, root)
    return read_text(did, root)


@_locked
def add_document(cid: str, name: str, data: bytes, root=None) -> dict:
    """Copy a file into the app, parse it and add it to a collection. The same bytes imported twice are stored once: the existing document
    joins the collection and `duplicate` is true. Returns {"document": row, "duplicate": bool}; an unreadable file is still stored, as `failed`."""
    c = get(cid, root)
    if not c:
        raise Invalid("Unknown collection")
    digest = hashlib.sha256(data).hexdigest()
    for did in (p.name for p in (_root(root) / "docs").glob("kd-*")) if (_root(root) / "docs").is_dir() else []:
        d = _doc_dir(did, root)
        old = _read_json(d / "doc.json") if d else None
        if old and old.get("sha256") == digest:
            add_to(cid, did, root)
            return {"document": get_document(did, root), "duplicate": True}
    display = _safe_name(name)
    kind = parsers.kind_of(display) or "unknown"
    ext = display[display.rfind("."):].lower() if "." in display else ""
    stored = "file" + (ext if re.fullmatch(r"\.[a-z0-9]{1,8}", ext) else "")
    did = _new_id("kd-", root)
    now = _now()
    d = _root(root) / "docs" / did
    _write_bytes(d / stored, data)
    _write_json(d / "passages.json", [])
    _write_json(d / "doc.json", {"id": did, "kind": "document", "schema_version": SCHEMA_VERSION, "ts": now, "name": display, "type": kind,
                                 "size": len(data), "sha256": digest, "file": stored, "status": "reading", "error": "", "warnings": [],
                                 "units": 0, "passages": 0, "updated_at": now})   # doc.json last: the document exists from here on
    add_to(cid, did, root)
    read_document(did, root)
    return {"document": get_document(did, root), "duplicate": False}


@_locked
def add_to(cid: str, did: str, root=None) -> bool:
    d = _col_dir(cid, root)
    c = _read_json(d / "collection.json") if d else None
    if not c or not _doc_dir(did, root):
        raise Invalid("Unknown collection or document")
    if did not in c["documents"]:
        c["documents"].append(did)
        c["updated_at"] = _now()
        _write_json(d / "collection.json", c)
    return True


@_locked
def remove_from(cid: str, did: str, root=None) -> dict:
    """Take a document out of one collection. Its last collection takes it to the Trash. Returns {"trashed": bool}."""
    d = _col_dir(cid, root)
    c = _read_json(d / "collection.json") if d else None
    if not c or did not in c["documents"]:
        raise Invalid("The document is not in this collection")
    others = [x for x in collections_of(did, root) if x != cid]
    c["documents"].remove(did)
    c["updated_at"] = _now()
    _write_json(d / "collection.json", c)
    if others:
        return {"trashed": False}
    return {"trashed": _trash_document(did, root, deleted_from=[cid])}


# ---------- saved conversations ----------
# One file per conversation: <collection>/chats/ch-<8 hex>.json = {id, kind: "chat", schema_version, title, ts, updated_at, scope, exchanges}.
# Every exchange keeps what was asked and answered, the exact system and context text sent, the model and what the search found
# (with the passage text, so an old chat still shows its sources after a document is removed). A chat lives inside its collection's
# folder, so it follows the collection through Trash, Restore and purge with no extra code. The built-in My prompts collection has no folder
# of its own: its chats sit in `collections/prompts/chats/` and are never trashed.

_CHAT = re.compile(r"^ch-[0-9a-f]{8}$")
BUILTIN = "prompts"


def _chats_dir(cid: str, root) -> Path | None:
    if cid == BUILTIN:
        return _root(root) / BUILTIN / "chats"
    d = _col_dir(cid, root)
    return d / "chats" if d else None


def _chat_file(cid: str, ch: str, root) -> Path | None:
    d = _chats_dir(cid, root)
    return d / f"{ch}.json" if d and _CHAT.match(ch or "") else None


def _chat_title(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    return s if len(s) <= 60 else s[:59].rstrip() + "…"


def _chat_row(c: dict) -> dict:
    return {"id": c["id"], "title": c.get("title", ""), "ts": c.get("ts", 0), "updated_at": c.get("updated_at", 0), "scope": c.get("scope", []),
            "exchanges": len(c.get("exchanges", [])), "pinned": bool(c.get("pinned"))}


def chat_dirs(root=None) -> list[Path]:
    """The chat folders that exist, of every live collection and of My prompts (read-only: the Gallery counts citations from them)."""
    out = []
    for cid in [*_collection_ids(root), BUILTIN]:
        d = _chats_dir(cid, root)
        if d and d.is_dir():
            out.append(d)
    return out


def list_chats(cid: str, root=None) -> list[dict]:
    """Saved conversations of a collection, most recently used first. A conversation with no exchange yet is not listed."""
    d = _chats_dir(cid, root)
    rows = [_chat_row(c) for c in (_read_json(p) for p in sorted(d.glob("ch-*.json"))) if c and c.get("exchanges")] if d and d.is_dir() else []
    return sorted(rows, key=lambda r: -r["updated_at"])


def get_chat(cid: str, ch: str, root=None) -> dict | None:
    f = _chat_file(cid, ch, root)
    return _read_json(f) if f and f.is_file() else None


@_locked
def create_chat(cid: str, scope: list[str] | None = None, title: str = "", root=None) -> dict:
    d = _chats_dir(cid, root)
    if d is None:
        raise Invalid("Unknown collection")
    taken = {p.stem for p in d.glob("ch-*.json")} if d.is_dir() else set()
    while True:
        ch = "ch-" + uuid.uuid4().hex[:8]
        if ch not in taken:
            break
    now = _now()
    c = {"id": ch, "kind": "chat", "schema_version": SCHEMA_VERSION, "title": _chat_title(title), "ts": now, "updated_at": now,
         "scope": [s for s in dict.fromkeys(scope or [cid]) if s] or [cid], "exchanges": []}
    _write_json(d / f"{ch}.json", c)
    return c


@_locked
def add_exchange(cid: str, ch: str, exchange: dict, scope: list[str] | None = None, root=None) -> dict | None:
    """Append one question and answer. The first one names the conversation (its question, shortened) unless it already has a title."""
    f = _chat_file(cid, ch, root)
    c = _read_json(f) if f and f.is_file() else None
    if not c:
        return None
    now = _now()
    ex = {"id": "ex-" + uuid.uuid4().hex[:8], "ts": now, **exchange}
    c["exchanges"].append(ex)
    if not c.get("title"):
        c["title"] = _chat_title(ex.get("prompt", "")) or "Conversation"
    if scope:
        c["scope"] = [s for s in dict.fromkeys(scope) if s] or c.get("scope", [])
    c["updated_at"] = now
    _write_json(f, c)
    return c


@_locked
def set_proposal_status(cid: str, ch: str, ex_id: str, status: str, root=None) -> bool | None:
    """Mark an exchange's proposed edit open, applied or dismissed. None when the conversation or exchange is unknown, False when it has no proposal."""
    if status not in ("open", "applied", "dismissed"):
        raise Invalid("Unknown status")
    f = _chat_file(cid, ch, root)
    c = _read_json(f) if f and f.is_file() else None
    ex = next((e for e in (c or {}).get("exchanges", []) if e.get("id") == ex_id), None)
    if ex is None:
        return None
    if not ex.get("proposal"):
        return False
    ex["proposal"]["status"] = status
    _write_json(f, c)
    return True


@_locked
def rename_chat(cid: str, ch: str, title: str, root=None) -> dict | None:
    f = _chat_file(cid, ch, root)
    c = _read_json(f) if f and f.is_file() else None
    if not c:
        return None
    c["title"] = _name(title, "title")
    _write_json(f, c)
    return c


@_locked
def pin_chat(cid: str, ch: str, pinned: bool, root=None) -> dict | None:
    """Pinned conversations are listed first. Pinning changes nothing else (not even the 'used' time)."""
    f = _chat_file(cid, ch, root)
    c = _read_json(f) if f and f.is_file() else None
    if not c:
        return None
    c["pinned"] = bool(pinned)
    _write_json(f, c)
    return c


@_locked
def delete_chat(cid: str, ch: str, root=None) -> bool:
    f = _chat_file(cid, ch, root)
    if not f or not f.is_file():
        return False
    f.unlink()
    return True


# ---------- trash ----------

def _trash_document(did: str, root, deleted_from: list[str], deleted_with: str = "") -> bool:
    d = _doc_dir(did, root)
    doc = _read_json(d / "doc.json") if d else None
    if not doc:
        return False
    doc.update(deleted_at=_now(), deleted_from=deleted_from, deleted_with=deleted_with)
    _write_json(d / "doc.json", doc)
    dest = _root(root) / ".trash" / "docs" / did
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return True


@_locked
def trash_collection(cid: str, root=None) -> bool:
    d = _col_dir(cid, root)
    c = _read_json(d / "collection.json") if d else None
    if not c:
        return False
    for did in c["documents"]:
        if not [x for x in collections_of(did, root) if x != cid]:
            _trash_document(did, root, deleted_from=[cid], deleted_with=cid)
    c["deleted_at"] = _now()
    _write_json(d / "collection.json", c)
    dest = _root(root) / ".trash" / datetime.now().strftime("%Y-%m") / cid
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return True


@_locked
def trash_document(did: str, root=None) -> bool:
    """Delete a document everywhere (it leaves every collection)."""
    if not _doc_dir(did, root):
        return False
    cids = collections_of(did, root)
    for cid in cids:
        d = _col_dir(cid, root)
        c = _read_json(d / "collection.json")
        c["documents"].remove(did)
        c["updated_at"] = _now()
        _write_json(d / "collection.json", c)
    return _trash_document(did, root, deleted_from=cids)


@_locked
def restore_collection(cid: str, root=None) -> bool:
    t = _trashed_col(cid, root)
    if not t or (_root(root) / cid).exists():
        return False
    c = _read_json(t / "collection.json")
    c.pop("deleted_at", None)
    _write_json(t / "collection.json", c)
    shutil.move(str(t), str(_root(root) / cid))
    for tdoc in sorted((_root(root) / ".trash" / "docs").glob("kd-*")) if (_root(root) / ".trash" / "docs").is_dir() else []:
        doc = _read_json(tdoc / "doc.json")
        if doc and doc.get("deleted_with") == cid:
            _restore_doc_files(doc["id"], root)
    return True


def _restore_doc_files(did: str, root) -> None:
    t = _trashed_doc(did, root)
    doc = _read_json(t / "doc.json")
    for k in ("deleted_at", "deleted_from", "deleted_with"):
        doc.pop(k, None)
    _write_json(t / "doc.json", doc)
    (_root(root) / "docs").mkdir(parents=True, exist_ok=True)
    shutil.move(str(t), str(_root(root) / "docs" / did))


@_locked
def restore_document(did: str, root=None) -> bool:
    """Bring a deleted document back into the collections it was in. Refused when none of them exists any more (it would be invisible)."""
    t = _trashed_doc(did, root)
    doc = _read_json(t / "doc.json") if t else None
    if not doc or _doc_dir(did, root):
        return False
    back = [cid for cid in doc.get("deleted_from", []) if _col_dir(cid, root)]
    if not back:
        return False
    _restore_doc_files(did, root)
    for cid in back:
        add_to(cid, did, root)
    return True


@_locked
def purge_collection(cid: str, root=None) -> bool:
    """Delete a trashed collection for good, with the documents that were trashed along with it."""
    t = _trashed_col(cid, root)
    if not t:
        return False
    for tdoc in sorted((_root(root) / ".trash" / "docs").glob("kd-*")) if (_root(root) / ".trash" / "docs").is_dir() else []:
        doc = _read_json(tdoc / "doc.json")
        if doc and doc.get("deleted_with") == cid:
            shutil.rmtree(tdoc)
    shutil.rmtree(t)
    return True


@_locked
def purge_document(did: str, root=None) -> bool:
    t = _trashed_doc(did, root)
    if not t:
        return False
    shutil.rmtree(t)
    return True


def load_trash(root=None) -> list[dict]:
    """Trashed collections and individually deleted documents, newest deletion first. Documents that went with a collection are not listed
    on their own."""
    rows = []
    for cj in (_root(root) / ".trash").glob("*/col-*/collection.json"):
        c = _read_json(cj)
        if c:
            rows.append({"id": c["id"], "name": c["name"], "kind": "collection", "deleted_at": c.get("deleted_at", 0), "tags": c.get("tags", []),
                         "documents": len(c.get("documents", [])), "store": "collections"})
    for dj in (_root(root) / ".trash" / "docs").glob("kd-*/doc.json"):
        doc = _read_json(dj)
        if doc and not doc.get("deleted_with"):
            rows.append({"id": doc["id"], "name": doc["name"], "kind": "document", "deleted_at": doc.get("deleted_at", 0), "tags": [],
                         "size": doc.get("size", 0), "store": "collections"})
    return sorted(rows, key=lambda r: -r["deleted_at"])


@_locked
def purge(id_: str, root=None) -> bool:
    return purge_collection(id_, root) if id_.startswith("col-") else purge_document(id_, root)


@_locked
def restore(id_: str, root=None) -> bool:
    return restore_collection(id_, root) if id_.startswith("col-") else restore_document(id_, root)


@_locked
def empty_trash(root=None) -> int:
    return sum(purge(r["id"], root) for r in load_trash(root))


@_locked
def purge_expired(days: int, root=None) -> int:
    if days <= 0:
        return 0
    cutoff = _now() - days * 86400
    return sum(purge(r["id"], root) for r in load_trash(root) if r["deleted_at"] < cutoff)
