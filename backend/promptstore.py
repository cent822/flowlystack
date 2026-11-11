"""Prompt files on disk. Standard library only: the capture hook imports this with the system python3.

Layout under PROMPTS_DIR:
    2026-10/<id>.json        original prompt, written once by the hook or the import, never edited
    2026-10/<id>.meta.json   sidecar with your title, tags, note and star (not versioned)
    2026-10/<id>.md          the current editable text, created on the first save
    2026-10/<id>.versions.json  every saved version: {"versions": [{id, message, ts, text}, ...]}, oldest first
    .trash/2026-10/          deleted prompts are moved here (with all their files) until restored or deleted for good
    studio/2026-10/<id>.chat.json  Studio only: the Assistant conversation (saved pairs)
    studio/                  Prompt Studio: the same layout again (see the Studio section at the end of this file)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from . import promptdiff
from .config import PROMPTS_DIR

META_FIELDS = {"tags": list, "note": str, "title": str, "starred": bool}
STUDIO_STATUSES = ("draft", "refined", "final")
STUDIO_TEXT_FIELDS = ("purpose", "use_when", "target", "example")
# Properties (like Obsidian's): the user's own key/value pairs about a prompt, kept in order. Every one goes into the header of a
# Markdown export. The five documentation fields above (and `note`) are properties with a well-known key: the sidecar keeps them in
# step both ways, so the list view, the search and the Assistant keep reading them as before. `properties` missing from an older
# sidecar is built from those fields.
PROPERTY_FIELDS = ("purpose", "target", "use_when", "example", "note")
PROPERTY_ALIASES = {"when_to_use": "use_when", "when_to_use_it": "use_when"}
PROPERTY_RESERVED = ("title", "tags", "status")   # already in every export header
MAX_PROPERTIES, MAX_KEY, MAX_VALUE = 100, 80, 50_000
STUDIO_META_FIELDS = {**META_FIELDS, "status": str, **{k: str for k in STUDIO_TEXT_FIELDS}}
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}     # original path -> (mtime, parsed)


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        o = json.loads(path.read_text())
        return o if isinstance(o, dict) else None
    except (OSError, ValueError):
        return None


def _digest(session_id: str, prompt: str) -> str:
    return hashlib.sha1(f"{session_id}\n{prompt}".encode()).hexdigest()[:6]


def write_prompt(prompt: str, ts: float, session_id: str = "", cwd: str = "", source: str = "hook",
                 root: Path | None = None, extra: dict | None = None) -> str:
    """Save one original prompt file and return its id. `extra` adds fields such as `agent` (the core fields win)."""
    root = root or PROMPTS_DIR
    when = datetime.fromtimestamp(ts)
    base = f"{when:%Y%m%d-%H%M%S}-{(session_id or 'nosession')[:8]}-{_digest(session_id, prompt)}"
    pid, n = base, 1
    folder = root / f"{when:%Y-%m}"
    while (folder / f"{pid}.json").exists():
        n += 1
        pid = f"{base}-{n}"
    _write_json(folder / f"{pid}.json", {
        **(extra or {}),
        "id": pid, "ts": ts, "session_id": session_id, "cwd": cwd,
        "project": os.path.basename(cwd) if cwd else "", "prompt": prompt, "source": source,
    })
    return pid


CODEX_WRAP = "# Context from my IDE setup"
CODEX_MARKER = "## My request for Codex:"


def codex_typed_text(o: dict):
    """The text of a prompt you typed, from one rollout line, or None when the line is not a typed prompt.
    Older Codex writes an `event_msg` of type `user_message` (a `message` string). Current Codex writes an `event_msg` of type
    `item_completed` whose item is a `UserMessage` (`content` is a list of text parts). Other user-role messages (AGENTS.md,
    environment context) are injected context and are never typed prompts."""
    if o.get("type") != "event_msg":
        return None
    pl = o.get("payload") or {}
    kind = pl.get("type")
    if kind == "user_message":
        return pl.get("message") if isinstance(pl.get("message"), str) else ""
    if kind == "item_completed" and (pl.get("item") or {}).get("type") == "UserMessage":
        parts = (pl["item"].get("content") or [])
        return "\n".join(p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str))
    return None


def clean_codex_prompt(text) -> str:
    """The Codex VS Code extension wraps a prompt in an IDE-context block: keep only the request after its marker."""
    text = text if isinstance(text, str) else ""
    if text.startswith(CODEX_WRAP) and CODEX_MARKER in text:
        text = text.split(CODEX_MARKER, 1)[1]
    return text.strip()


def _meta_path(orig: Path) -> Path:
    return orig.with_name(orig.stem + ".meta.json")


def _clean_meta(m: dict | None, studio: bool = False) -> dict:
    """The sidecar as the app sees it. Library prompts keep their original shape; Studio prompts (`studio=True`,
    decided by `kind` in the original file) add a status and the documentation fields."""
    m = m or {}
    out = {
        "tags": [str(t) for t in m.get("tags", []) if str(t).strip()] if isinstance(m.get("tags"), list) else [],
        "note": m.get("note") if isinstance(m.get("note"), str) else "",
        "title": m.get("title") if isinstance(m.get("title"), str) else "",
        "starred": bool(m.get("starred")),
        "updated_at": m.get("updated_at") if isinstance(m.get("updated_at"), (int, float)) else 0,
    }
    if studio:
        out["status"] = m.get("status") if m.get("status") in STUDIO_STATUSES else "draft"
        out["status_at"] = m.get("status_at") if isinstance(m.get("status_at"), (int, float)) else 0
        for k in STUDIO_TEXT_FIELDS:
            out[k] = m.get(k) if isinstance(m.get(k), str) else ""
        out["properties"] = clean_properties(m["properties"]) if isinstance(m.get("properties"), list) \
            else [{"key": k, "value": out[k]} for k in PROPERTY_FIELDS if out[k].strip()]
    return out


def property_id(key: str) -> str:
    """A property name as compared: case, spaces and hyphens do not matter ("When to use" is `use_when`)."""
    k = re.sub(r"[\s-]+", "_", str(key).strip().lower())
    return PROPERTY_ALIASES.get(k, k)


def clean_properties(v) -> list[dict]:
    """The list as stored: text keys and values, empty keys and reserved or repeated names dropped, at most MAX_PROPERTIES."""
    out, seen = [], set()
    for p in v if isinstance(v, list) else []:
        if not isinstance(p, dict) or not isinstance(p.get("key"), str):
            continue
        key, val = p["key"].strip()[:MAX_KEY], p.get("value") if isinstance(p.get("value"), str) else ""
        pid = property_id(key)
        if key and pid not in PROPERTY_RESERVED and pid not in seen and len(out) < MAX_PROPERTIES:
            seen.add(pid)
            out.append({"key": key, "value": val[:MAX_VALUE]})
    return out


def check_properties(v) -> str:
    """Why a submitted list cannot be saved, in words for the user ("" when it is fine). Used by the API before saving."""
    if not isinstance(v, list) or len(v) > MAX_PROPERTIES:
        return f"Use at most {MAX_PROPERTIES} properties."
    seen = set()
    for p in v:
        key = (p.get("key") if isinstance(p, dict) else None)
        if not isinstance(key, str) or not isinstance(p.get("value", ""), str):
            return "A property needs a name and a text value."
        key = key.strip()
        if not key:
            return "Every property needs a name."
        if len(key) > MAX_KEY or len(p.get("value", "")) > MAX_VALUE:
            return f"“{key[:30]}” is too long."
        pid = property_id(key)
        if pid in PROPERTY_RESERVED:
            return f"“{key}” is already in every export (title, tags and status are added for you)."
        if pid in seen:
            return f"“{key}” appears twice."
        seen.add(pid)
    return ""


def _legacy_from_properties(meta: dict) -> None:
    """Keep the documentation fields and the note equal to the properties that carry their names."""
    by = {property_id(p["key"]): p["value"] for p in meta["properties"]}
    for k in PROPERTY_FIELDS:
        meta[k] = by.get(k, "")


def _properties_from_legacy(meta: dict, changed: set) -> None:
    """After a patch of the documentation fields themselves: update, add or remove the property that carries each."""
    props = [dict(p) for p in meta["properties"]]
    for k in PROPERTY_FIELDS:
        if k not in changed:
            continue
        i = next((i for i, p in enumerate(props) if property_id(p["key"]) == k), None)
        if meta[k].strip():
            if i is None:
                props.append({"key": k, "value": meta[k]})
            else:
                props[i]["value"] = meta[k]
        elif i is not None:
            del props[i]
    meta["properties"] = props


def _versions_path(orig: Path) -> Path:
    return orig.with_name(orig.stem + ".versions.json")


def _md_path(orig: Path) -> Path:
    return orig.with_suffix(".md")


def _chat_path(orig: Path) -> Path:
    return orig.with_name(orig.stem + ".chat.json")


def _auto_title(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:90]
    return "Untitled prompt"


def load_all(root: Path | None = None) -> list[dict]:
    """Every saved prompt with its sidecar merged in as `meta`, newest first."""
    root = root or PROMPTS_DIR
    out, seen = [], set()
    with _lock:
        for p in root.glob("*/*.json") if root.exists() else []:
            if p.name.endswith((".meta.json", ".versions.json", ".chat.json")) or p.parent.name.startswith("."):
                continue
            key = str(p)
            seen.add(key)
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            hit = _cache.get(key)
            if not hit or hit[0] != mt:
                o = _read_json(p)
                if not o or "prompt" not in o or "id" not in o:
                    continue
                hit = _cache[key] = (mt, o)
            mp, md = _meta_path(p), _md_path(p)
            studio = hit[1].get("kind") == "studio"
            meta = _clean_meta(_read_json(mp) if mp.exists() else None, studio)
            text, edited, updated = hit[1]["prompt"], False, max(hit[1].get("ts") or 0, meta["updated_at"])
            if md.exists():
                try:
                    text, edited = md.read_text(), True
                    updated = max(updated, md.stat().st_mtime)
                except OSError:
                    pass
            out.append({**hit[1], "agent": hit[1].get("agent") or ("" if studio else "claude"), "meta": meta, "text": text, "edited": edited, "updated": updated,
                        "title": meta["title"] or _auto_title(text), "_path": key})
        for k in [k for k in _cache if k not in seen]:
            del _cache[k]
    out.sort(key=lambda o: o.get("ts") or 0, reverse=True)
    return out


def update_meta(pid: str, patch: dict, root: Path | None = None) -> dict | None:
    """Merge allowed fields into the sidecar of prompt `pid`. Returns the new meta, or None if unknown."""
    with_path = next((o for o in load_all(root) if o["id"] == pid), None)
    if not with_path:
        return None
    mp = _meta_path(Path(with_path["_path"]))
    studio = with_path.get("kind") == "studio"
    with _lock:
        meta = _clean_meta(_read_json(mp) if mp.exists() else None, studio)
        status = meta.get("status")
        for k, typ in (STUDIO_META_FIELDS if studio else META_FIELDS).items():
            if k in patch and isinstance(patch[k], typ):
                if k == "status" and patch[k] not in STUDIO_STATUSES:
                    continue
                meta[k] = patch[k]
        if studio and isinstance(patch.get("properties"), list):
            meta["properties"] = clean_properties(patch["properties"])
            _legacy_from_properties(meta)
        elif studio and any(k in patch for k in PROPERTY_FIELDS):
            _properties_from_legacy(meta, {k for k in PROPERTY_FIELDS if k in patch})
        meta["tags"] = list(dict.fromkeys(t.strip() for t in meta["tags"] if t.strip()))
        meta["updated_at"] = datetime.now().timestamp()
        if studio and meta["status"] != status:
            meta["status_at"] = meta["updated_at"]
        _write_json(mp, meta)
    return _clean_meta(meta, studio)


def import_transcripts(projects_dir: Path, root: Path | None = None) -> dict:
    """One-off backfill: save human prompts found in Claude Code transcripts that are not saved yet.

    A prompt counts as already saved when the same session has the same text within two minutes
    (the hook and the transcript timestamp the same prompt a moment apart).
    """
    from .ingest import _is_human_prompt, _ts   # lazy: ingest needs a newer Python than the hook may have
    known: dict[tuple[str, str], list[float]] = {}
    for o in load_all(root):
        known.setdefault((o.get("session_id", ""), o["prompt"]), []).append(o.get("ts") or 0)
    imported = skipped = 0
    batch: set[tuple[str, str, float]] = set()   # same line twice in one run (copied history); real repeats differ in time
    files = sorted(projects_dir.glob("*/*.jsonl"))   # no files at all means the history folder is missing or empty: the page says so
    for path in files:
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") != "user" or not _is_human_prompt(o):
                continue
            c = o["message"]["content"]
            text = c if isinstance(c, str) else "\n\n".join(
                b["text"] for b in c if isinstance(b, dict) and b.get("type") == "text")
            ts, sid = _ts(o.get("timestamp")), o.get("sessionId") or path.stem
            if not text.strip() or ts is None:
                continue
            if (sid, text, ts) in batch or any(abs(ts - t) < 120 for t in known.get((sid, text), [])):
                skipped += 1
                continue
            write_prompt(text, ts, sid, o.get("cwd") or "", source="import", root=root)
            batch.add((sid, text, ts))
            imported += 1
    return {"imported": imported, "skipped": skipped, "files": len(files)}


def summarize(items: list[dict]) -> dict:
    tags: dict[str, int] = {}
    projects: dict[str, int] = {}
    agents: dict[str, int] = {}
    for o in items:
        agents[o["agent"]] = agents.get(o["agent"], 0) + 1
        for t in o["meta"]["tags"]:
            tags[t] = tags.get(t, 0) + 1
        if o.get("project"):
            projects[o["project"]] = projects.get(o["project"], 0) + 1
    by = lambda d: [{"name": k, "n": v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"tags": by(tags), "projects": by(projects), "agents": by(agents)}


def tag_counts(items: list[dict], base: list[dict]) -> list[dict]:
    """Every tag in `items`, counted over `base` (the prompts left after the other filters). A tag you have not picked
    shows how many prompts you would have if you added it; zero means picking it would empty the list."""
    n: dict[str, int] = {t["name"]: 0 for t in summarize(items)["tags"]}
    for o in base:
        for t in o["meta"]["tags"]:
            n[t] += 1
    return [{"name": k, "n": v} for k, v in sorted(n.items(), key=lambda kv: (-kv[1], kv[0]))]


def search(items: list[dict], q: str = "", tags: list[str] | None = None, project: str = "", starred: bool = False,
           edited: bool = False, agent: str = "") -> list[dict]:
    """`tags` is an AND filter: a prompt must carry every listed tag."""
    q = q.strip().lower()
    res = []
    for o in items:
        m = o["meta"]
        if tags and not all(t in m["tags"] for t in tags):
            continue
        if project and o.get("project") != project:
            continue
        if agent and o["agent"] != agent:
            continue
        if starred and not m["starred"]:
            continue
        if edited and not o["edited"]:
            continue
        if q and q not in "\n".join([o["text"], o["title"], m["note"], m.get("purpose", ""), " ".join(m["tags"])]).lower():
            continue
        res.append(o)
    return res


def sort_items(items: list[dict], key: str = "updated", desc: bool = True) -> list[dict]:
    if key == "relevance":   # keep the order the search engine returned
        return items
    keyfn = {"title": lambda o: o["title"].lower(), "created": lambda o: o.get("ts") or 0}.get(key, lambda o: o["updated"])
    return sorted(items, key=keyfn, reverse=desc)


def summary_row(o: dict) -> dict:
    """What the list page needs for one row (no full text)."""
    body = o["text"]
    if not o["meta"]["title"]:   # the auto-title is the first line, so the preview carries on after it
        lines = [ln for ln in body.splitlines() if ln.strip()]
        body = "\n".join(lines[1:]) if len(lines) > 1 else body
    return {"id": o["id"], "title": o["title"], "preview": " ".join(body.split())[:240], "ts": o.get("ts"),
            "updated": o["updated"], "project": o.get("project", ""), "source": o.get("source", ""),
            "agent": o["agent"], "model": o.get("model", ""), "edited": o["edited"], "meta": {k: o["meta"][k] for k in ("tags", "note", "starred")}}


# ---------- single prompt: text, versions, trash ----------

_HASH = re.compile(r"^[0-9a-f]{7,40}$")


def get(pid: str, root: Path | None = None) -> dict | None:
    return next((o for o in load_all(root) if o["id"] == pid), None)


def _read_versions(orig: Path) -> list[dict]:
    """Saved versions of a prompt, oldest first. The newest one is the current text."""
    vs = (_read_json(_versions_path(orig)) or {}).get("versions")
    return [v for v in vs if isinstance(v, dict) and "id" in v and "text" in v] if isinstance(vs, list) else []


def _write_versions(orig: Path, versions: list[dict]) -> None:
    _write_json(_versions_path(orig), {"versions": versions})


def _versions(o: dict) -> list[dict]:
    """Versions shown in the picker, newest first, without their text. `hash` and `short` both carry the version id."""
    if not o["edited"]:
        return []
    return [{"hash": v["id"], "short": v["id"], "message": v.get("message", ""), "ts": float(v.get("ts") or 0)}
            for v in reversed(_read_versions(Path(o["_path"])))]


def delete_revision(pid: str, rev: str, root: Path | None = None) -> dict | None | bool:
    """Remove one saved version for good. The current (newest) one cannot be deleted: it is the text on disk.
    Returns the new detail, None for an unknown prompt or version, False for the current version."""
    root = root or PROMPTS_DIR
    o = get(pid, root)
    if not o or not o["edited"]:
        return None
    orig = Path(o["_path"])
    with _lock:
        vs = _read_versions(orig)
        i = next((n for n, v in enumerate(vs) if v["id"] == rev), None)
        if i is None:
            return None
        if i == len(vs) - 1:
            return False
        del vs[i]
        _write_versions(orig, vs)
    return detail(pid, root)


def detail(pid: str, root: Path | None = None) -> dict | None:
    root = root or PROMPTS_DIR
    o = get(pid, root)
    if not o:
        return None
    d = {k: v for k, v in o.items() if k != "_path"}
    d["revisions"] = _versions(o)
    if o.get("kind") == "studio":
        d["variables"] = variables(o["text"])
    return d


def _new_version_id(taken: set[str]) -> str:
    while True:
        vid = uuid.uuid4().hex[:7]
        if vid not in taken:
            return vid


def save_text(pid: str, text: str, message: str = "", root: Path | None = None) -> dict | None:
    """Save a new version of the prompt text. The first save also records the captured original as the first version."""
    root = root or PROMPTS_DIR
    o = get(pid, root)
    if not o:
        return None
    orig = Path(o["_path"])
    if text == (o["text"] if o["edited"] else o["prompt"]):
        return detail(pid, root)   # nothing changed
    with _lock:
        vs = _read_versions(orig) if o["edited"] else [
            {"id": _new_version_id(set()), "message": "Initial version", "ts": o.get("ts") or time.time(), "text": o["prompt"]}]
        vs.append({"id": _new_version_id({v["id"] for v in vs}), "message": message.strip() or "Update", "ts": time.time(), "text": text})
        _write_versions(orig, vs)   # versions first: a .md without its versions file is the case to avoid
        md = _md_path(orig)
        tmp = md.with_name(md.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, md)
    return detail(pid, root)


def revision_text(pid: str, rev: str, root: Path | None = None) -> dict | None:
    root = root or PROMPTS_DIR
    o = get(pid, root)
    if not o or not o["edited"]:
        return None
    v = next((v for v in _read_versions(Path(o["_path"])) if v["id"] == rev), None)
    return {"hash": v["id"], "short": v["id"], "message": v.get("message", ""), "ts": float(v.get("ts") or 0), "text": v["text"]} if v else None


def diff(pid: str, a: str, b: str = "current", root: Path | None = None) -> dict | None:
    """Compare revision `a` with revision `b` (or the current text)."""
    root = root or PROMPTS_DIR
    ra = revision_text(pid, a, root)
    o = get(pid, root)
    if not ra or not o:
        return None
    if b == "current":
        rb = {"short": "current", "text": o["text"], "ts": o["updated"]}
    else:
        rb = revision_text(pid, b, root)
        if not rb:
            return None
    return {"a": {"short": ra["short"], "message": ra["message"], "ts": ra["ts"]},
            "b": {"short": rb["short"], "ts": rb["ts"]}, "rows": promptdiff.diff_rows(ra["text"], rb["text"])}


def trash(pid: str, root: Path | None = None) -> bool:
    """Move a prompt's files (original, sidecar, text, versions) to .trash/ and stamp when."""
    root = root or PROMPTS_DIR
    o = get(pid, root)
    if not o:
        return False
    orig = Path(o["_path"])
    mp = _meta_path(orig)
    _write_json(mp, {**(_read_json(mp) or {}), "deleted_at": time.time()})   # a move keeps mtime, so record the day it was deleted
    dest = root / ".trash" / orig.parent.name
    dest.mkdir(parents=True, exist_ok=True)
    for f in (orig, mp, _md_path(orig), _versions_path(orig), _chat_path(orig)):
        if f.exists():
            os.replace(f, dest / f.name)
    return True


# ---------- the trash: list, restore, delete for good ----------

def load_trash(root: Path | None = None) -> list[dict]:
    """Every trashed prompt, most recently deleted first. `deleted_at` falls back to the file's change time."""
    root = root or PROMPTS_DIR
    out = []
    for p in (root / ".trash").glob("*/*.json"):
        if p.name.endswith((".meta.json", ".versions.json", ".chat.json")):
            continue
        o = _read_json(p)
        if not o or "prompt" not in o or "id" not in o:
            continue
        raw = _read_json(_meta_path(p)) or {}
        meta, md, text, edited = _clean_meta(raw, o.get("kind") == "studio"), _md_path(p), o["prompt"], False
        if md.exists():
            try:
                text, edited = md.read_text(), True
            except OSError:
                pass
        deleted = raw.get("deleted_at") if isinstance(raw.get("deleted_at"), (int, float)) else p.stat().st_ctime
        out.append({**o, "meta": meta, "text": text, "edited": edited, "deleted_at": deleted,
                    "title": meta["title"] or _auto_title(text), "_path": p})
    out.sort(key=lambda o: o["deleted_at"], reverse=True)
    return out


def trash_row(o: dict, days: int = 0) -> dict:
    body = o["text"]
    return {"id": o["id"], "title": o["title"], "preview": " ".join(body.split())[:240], "project": o.get("project", ""),
            "ts": o.get("ts"), "deleted_at": o["deleted_at"], "edited": o["edited"], "tags": o["meta"]["tags"],
            "purge_at": o["deleted_at"] + days * 86400 if days else None}


def _trash_files(o: dict) -> list[Path]:
    p = o["_path"]
    return [f for f in (p, _meta_path(p), _md_path(p), _versions_path(p), _chat_path(p)) if f.exists()]


def trash_get(pid: str, root: Path | None = None) -> dict | None:
    return next((o for o in load_trash(root) if o["id"] == pid), None)


def restore(pid: str, root: Path | None = None) -> bool | None:
    """Put a trashed prompt back where it was. None = unknown id, False = something already sits at its place."""
    root = root or PROMPTS_DIR
    o = trash_get(pid, root)
    if not o:
        return None
    dest = root / o["_path"].parent.name
    files = _trash_files(o)
    if any((dest / f.name).exists() for f in files):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    mp = _meta_path(o["_path"])
    if mp.exists():   # drop the deletion stamp; the rest of the sidecar is unchanged
        _write_json(mp, {k: v for k, v in (_read_json(mp) or {}).items() if k != "deleted_at"})
    for f in files:
        os.replace(f, dest / f.name)
    return True


def purge(pid: str, root: Path | None = None) -> bool:
    """Delete a trashed prompt's files for good, versions included."""
    o = trash_get(pid, root)
    if not o:
        return False
    for f in _trash_files(o):
        f.unlink(missing_ok=True)
    return True


def empty_trash(root: Path | None = None) -> int:
    n = 0
    for o in load_trash(root):
        n += purge(o["id"], root)
    return n


def purge_expired(days: int, root: Path | None = None) -> int:
    """Delete trashed prompts older than `days` (0 = keep them)."""
    if days <= 0:
        return 0
    cutoff, n = time.time() - days * 86400, 0
    for o in load_trash(root):
        if o["deleted_at"] < cutoff:
            n += purge(o["id"], root)
    return n


# ---------- Prompt Studio: prompts you write on purpose ----------
#
# Same file model as the Library, in its own root (PROMPTS_DIR/studio, trash in studio/.trash) so the Library loader never
# sees it. Every function above already takes `root`; Studio prompts are told apart by `kind: "studio"` in the original
# file, which switches on the extended sidecar (status and documentation fields). Nothing here changes a Library prompt.

STUDIO_DIR = PROMPTS_DIR / "studio"
STUDIO_SCHEMA = 1
_VAR = re.compile(r"\{\{\s*([A-Za-z_][\w-]*)\s*\}\}", re.ASCII)   # ASCII names, so the browser (whose \w is ASCII) finds the same ones


def variables(text: str) -> list[str]:
    """`{{name}}` placeholders in the text: unique names in order of first appearance. Never stored, always parsed."""
    return list(dict.fromkeys(_VAR.findall(text or "")))


def _new_studio_id(root: Path) -> str:
    """`ps-` plus 12 random hex characters. Never reused: live and trashed prompts both count as taken."""
    while True:
        pid = "ps-" + uuid.uuid4().hex[:12]
        if not any(root.glob(f"*/{pid}.json")) and not any((root / ".trash").glob(f"*/{pid}.json")):
            return pid


def _write_studio_files(orig: Path, original: dict, meta: dict, text: str, versions: list[dict], chat: dict | None = None) -> None:
    """Versions, text and sidecar first, the original last: the original is what makes a prompt visible, so a crash
    half way leaves stray files at worst, never a prompt that is listed but incomplete."""
    _write_versions(orig, versions)
    if chat:
        _write_json(_chat_path(orig), chat)
    md = _md_path(orig)
    tmp = md.with_name(md.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, md)
    _write_json(_meta_path(orig), meta)
    _write_json(orig, original)


def create_studio(text: str, title: str = "", tags: list[str] | None = None, derived_from: dict | None = None,
                  root: Path | None = None, message: str = "Created") -> dict:
    """Create a Studio prompt, versioned from its first moment (`message`, "Created" unless the caller says who made it), status Draft. Returns the detail."""
    root = root or STUDIO_DIR
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a prompt needs some text")
    now = time.time()
    with _lock:
        pid = _new_studio_id(root)
        orig = root / f"{datetime.fromtimestamp(now):%Y-%m}" / f"{pid}.json"
        meta = _clean_meta({"title": (title or "").strip(), "tags": [t.strip() for t in (tags or []) if t.strip()],
                            "status": "draft", "status_at": now, "updated_at": now}, True)
        meta["tags"] = list(dict.fromkeys(meta["tags"]))
        original = {"id": pid, "kind": "studio", "schema_version": STUDIO_SCHEMA, "ts": now, "prompt": text,
                    **({"derived_from": derived_from} if derived_from else {})}
        _write_studio_files(orig, original, meta, text, [{"id": _new_version_id(set()), "message": message, "ts": now, "text": text}])
    return detail(pid, root)


def promote_from_library(lib_id: str, root: Path | None = None, library_root: Path | None = None) -> dict | None:
    """Copy a Library prompt (its current text, explicit title and tags) into Studio with a link back.
    The Library prompt is only read. Returns the new Studio detail, or None for an unknown Library id."""
    o = get(lib_id, library_root)
    if not o:
        return None
    m = o["meta"]
    return create_studio(o["text"], m["title"], m["tags"], {"store": "library", "id": lib_id}, root)


def studio_row(o: dict) -> dict:
    """What the Studio list needs for one row (no full text)."""
    body = o["text"]
    if not o["meta"]["title"]:   # the auto-title is the first line, so the preview carries on after it
        lines = [ln for ln in body.splitlines() if ln.strip()]
        body = "\n".join(lines[1:]) if len(lines) > 1 else body
    m = o["meta"]
    return {"id": o["id"], "title": o["title"], "preview": " ".join(body.split())[:240], "ts": o.get("ts"), "updated": o["updated"],
            "derived_from": o.get("derived_from"), "variables": len(variables(o["text"])),
            "meta": {k: m[k] for k in ("tags", "note", "starred", "status", "purpose", "target")}}


def status_counts(items: list[dict]) -> list[dict]:
    """All three statuses with how many of `items` carry each (zero included, so the filter can show them dimmed)."""
    n = {s: 0 for s in STUDIO_STATUSES}
    for o in items:
        n[o["meta"]["status"]] += 1
    return [{"name": s, "n": c} for s, c in n.items()]


def export_studio(root: Path | None = None) -> dict:
    """Every Studio prompt, trashed ones too, as one JSON-able dict that `import_studio` can read back unchanged."""
    root = root or STUDIO_DIR
    out = []
    for trashed, items in ((False, load_all(root)), (True, load_trash(root))):
        for o in items:
            orig = Path(o["_path"])
            out.append({"id": o["id"], "month": orig.parent.name, "trashed": trashed, "original": _read_json(orig),
                        "meta": _read_json(_meta_path(orig)) or {}, "text": _md_path(orig).read_text(),
                        "versions": _read_versions(orig), **({"chat": _read_json(_chat_path(orig))} if _chat_path(orig).exists() else {})})
    out.sort(key=lambda p: p["id"])
    return {"kind": "studio-export", "schema_version": STUDIO_SCHEMA, "prompts": out}


def import_studio(data: dict, root: Path | None = None) -> dict:
    """Write an `export_studio` dict into `root`. Ids that already exist (live or trashed) are skipped, never overwritten."""
    root = root or STUDIO_DIR
    if not isinstance(data, dict) or data.get("kind") != "studio-export" or data.get("schema_version") != STUDIO_SCHEMA:
        raise ValueError("not a Studio export this version can read")
    imported = skipped = 0
    with _lock:
        for p in data.get("prompts", []):
            pid = p["id"]
            if any(root.glob(f"*/{pid}.json")) or any((root / ".trash").glob(f"*/{pid}.json")):
                skipped += 1
                continue
            folder = (root / ".trash" if p["trashed"] else root) / p["month"]
            _write_studio_files(folder / f"{pid}.json", p["original"], p["meta"], p["text"], p["versions"], p.get("chat"))
            imported += 1
    return {"imported": imported, "skipped": skipped}


# ---------- Studio Assistant: the saved conversation ----------
#
# One `<id>.chat.json` per Studio prompt: `{"schema_version": 1, "exchanges": [...]}`, oldest first. An exchange is a
# dataset-ready pair (`prompt` + `response`) plus the exact `system` and `context` the model saw. The file follows its
# prompt through trash, restore, purge, export and import. Library prompts have none.

CHAT_SCHEMA = 1
PROPOSAL_STATUSES = ("open", "applied", "dismissed")


def _chat_file(pid: str, root: Path | None) -> Path | None:
    o = get(pid, root or STUDIO_DIR)
    return _chat_path(Path(o["_path"])) if o and o.get("kind") == "studio" else None


def _read_chat(f: Path) -> dict:
    c = _read_json(f) or {}
    ex = c.get("exchanges")
    return {"schema_version": CHAT_SCHEMA, "exchanges": [e for e in ex if isinstance(e, dict) and "id" in e] if isinstance(ex, list) else []}


def read_chat(pid: str, root: Path | None = None) -> list[dict] | None:
    """The saved exchanges, oldest first (empty when none). None for an unknown or non-Studio prompt."""
    f = _chat_file(pid, root)
    return None if f is None else _read_chat(f)["exchanges"]


def new_exchange(ex: dict) -> dict:
    """An exchange record from what the model call produced (not saved). `ex` carries model, params, system, context,
    prompt, response and optionally kind, partial and proposal (`{"text": ...}`); id, ts, curation and the proposal
    status are filled in here. Used for conversations that are not being saved too, so the page can still show them."""
    prop = ex.get("proposal")
    return {"id": "e-" + uuid.uuid4().hex[:8], "ts": time.time(), "kind": ex.get("kind") or "chat",
            "model": ex.get("model") or {}, "params": ex.get("params") or {}, "system": str(ex.get("system") or ""),
            "context": str(ex.get("context") or ""), "prompt": str(ex.get("prompt") or ""), "response": str(ex.get("response") or ""),
            "partial": bool(ex.get("partial")),
            "proposal": {"text": str(prop["text"]), "status": "open"} if isinstance(prop, dict) and prop.get("text") else None,
            "curation": {"keep": None, "note": ""}}


def add_exchange(pid: str, ex: dict, root: Path | None = None) -> dict | None:
    """Append one exchange (see `new_exchange`) to the prompt's conversation and return it as stored."""
    f = _chat_file(pid, root)
    if f is None:
        return None
    rec = new_exchange(ex)
    with _lock:
        chat = _read_chat(f)
        chat["exchanges"].append(rec)
        _write_json(f, chat)
    return rec


def _change_exchange(pid: str, eid: str, fn, root: Path | None) -> dict | None:
    f = _chat_file(pid, root)
    if f is None:
        return None
    with _lock:
        chat = _read_chat(f)
        e = next((e for e in chat["exchanges"] if e["id"] == eid), None)
        if e is None:
            return None
        fn(e)
        _write_json(f, chat)
    return e


def set_proposal_status(pid: str, eid: str, status: str, root: Path | None = None) -> dict | None:
    """Mark an exchange's proposal `applied` or `dismissed` (or back to `open`). None when the exchange has no proposal."""
    if status not in PROPOSAL_STATUSES:
        raise ValueError("unknown proposal status")
    def fn(e):
        if e.get("proposal"):
            e["proposal"]["status"] = status
    e = _change_exchange(pid, eid, fn, root)
    return e if e and e.get("proposal") else None


_UNSET = object()


def set_curation(pid: str, eid: str, keep=_UNSET, note=_UNSET, root: Path | None = None) -> dict | None:
    """Your data curation of a pair: `keep` True, False or None (not reviewed) and a free-text `note`. Only what is
    passed changes. Never changes what the model sees."""
    def fn(e):
        c = e.setdefault("curation", {"keep": None, "note": ""})
        if keep is not _UNSET:
            c["keep"] = keep if isinstance(keep, bool) else None
        if note is not _UNSET:
            c["note"] = str(note or "")
    return _change_exchange(pid, eid, fn, root)


def delete_exchange(pid: str, eid: str, root: Path | None = None) -> bool:
    f = _chat_file(pid, root)
    if f is None:
        return False
    with _lock:
        chat = _read_chat(f)
        keep = [e for e in chat["exchanges"] if e["id"] != eid]
        if len(keep) == len(chat["exchanges"]):
            return False
        _write_json(f, {**chat, "exchanges": keep})
    return True


def clear_chat(pid: str, root: Path | None = None) -> int | None:
    """Delete the whole conversation. Returns how many exchanges went, None for an unknown prompt."""
    f = _chat_file(pid, root)
    if f is None:
        return None
    with _lock:
        n = len(_read_chat(f)["exchanges"])
        f.unlink(missing_ok=True)
    return n
