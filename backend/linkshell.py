"""Linkshell storage: projects of linked prompt blocks, as plain files. Standard library only.

    PROMPTS_DIR/linkshell/
      ls-<12 hex>/
        project.json        settings (written last on create, so a project is never listed half-created)
        graph.json          {rev, blocks, links, frames, viewport}: positions, links, statuses; never any text
        blocks/<id>.md      current text of a block
        blocks/<id>.versions.json   {"versions": [{id, message, ts, text}]}, oldest first, newest = current (Prompt and Spec only)
        assets/<a-xxxxxxxx-name>    uploaded files
        .removed/<id>/      files and record of a block deleted on the canvas (restorable, purged after trash.days)
      .trash/<month>/ls-…/  whole projects moved here by delete

Every function takes an optional `root` (the linkshell folder) so tests can use a temp directory. Writes go to a temp file
and then `os.replace`, like promptstore. Nothing here reads or changes the Library or Studio.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from .config import PROMPTS_DIR
from .promptstore import clean_properties, check_properties   # the name/value rows, shared with Studio

TYPES = ("prompt", "spec", "note", "reference", "start")
VERSIONED = ("prompt", "spec")                 # these keep a version history; note and start keep only the current text
TEXTED = ("prompt", "spec", "note", "start")   # these have a text file
STATUSES = ("todo", "done", "skipped")
LINK_KINDS = ("order", "context")
FORMAT = "flowlystack-linkshell"
_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")            # ids become file names, so nothing else gets through
_PROJECT = re.compile(r"^ls-[0-9a-f]{12}$")
_ASSET = re.compile(r"^a-[0-9a-f]{8}-[A-Za-z0-9._-]{1,80}$")


class Invalid(ValueError):
    """The request breaks a rule (unknown block, order cycle, bad field). The message says which."""


class Conflict(Exception):
    """The graph save started from an older `rev` than the one on disk."""

    def __init__(self, rev: int):
        super().__init__(f"graph is at rev {rev}")
        self.rev = rev


# ---------- files ----------

_LOCK = threading.RLock()   # the API runs routes on several threads; every write to a project takes this lock, so two saves cannot interleave


def _locked(fn):
    @functools.wraps(fn)
    def run(*a, **k):
        with _LOCK:
            return fn(*a, **k)
    return run


def _tmp(path: Path) -> Path:
    return path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")   # its own name, so even unlocked writers never share a temp file


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    tmp.write_text(text)
    os.replace(tmp, path)


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else Path(PROMPTS_DIR) / "linkshell"


def _dir(pid: str, root: Path | None) -> Path | None:
    """The folder of a live project, or None (an id that is not `ls-` + 12 hex never touches the disk)."""
    if not _PROJECT.match(pid or ""):
        return None
    d = _root(root) / pid
    return d if (d / "project.json").is_file() else None


def assets_alias(pid: str, root: Path | None = None) -> str:
    """A short folder path for a project's `assets/`, for the paths an agent reads: a symlink `<alias dir>/<4+ chars>` pointing at the real folder
    (alias dir: env FLOWLYSTACK_ALIAS_DIR, else ~/.flowlystack/r). The name comes from the project id, so it is stable; it grows only on a clash.
    Falls back to the real path when the link cannot be made."""
    d = _dir(pid, root)
    if not d:
        return ""
    real = d / "assets"
    real.mkdir(exist_ok=True)
    target = os.path.realpath(real)
    base = Path(os.environ.get("FLOWLYSTACK_ALIAS_DIR") or Path.home() / ".flowlystack" / "r")
    try:
        base.mkdir(parents=True, exist_ok=True)
        digest = int(hashlib.sha1(pid.encode()).hexdigest(), 16)
        name = ""
        while digest:
            name, digest = name + "0123456789abcdefghijklmnopqrstuvwxyz"[digest % 36], digest // 36
        for n in range(4, len(name) + 1):
            link = base / name[:n]
            if link.is_symlink() and os.path.realpath(link) == target:
                return str(link)
            if not link.exists() and not link.is_symlink():
                os.symlink(target, link)
                return str(link)
    except OSError:
        pass
    return target


def _now() -> float:
    return time.time()


def _new_id(prefix: str, n: int, taken) -> str:
    while True:
        i = prefix + uuid.uuid4().hex[:n]
        if i not in taken:
            return i


def _text_path(d: Path, bid: str) -> Path:
    return d / "blocks" / f"{bid}.md"


def _versions_path(d: Path, bid: str) -> Path:
    return d / "blocks" / f"{bid}.versions.json"


# ---------- graph rules ----------

def _num(v, default=0):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else default


def order_edges(g: dict) -> list[tuple[str, str]]:
    """The `order` links as block-to-block pairs. A link may start or end at a Frame: from a Frame means "after every block in it", into a Frame
    "before every block in it", so a Frame link stands for one pair per block it holds."""
    members: dict[str, list[str]] = {}
    for f in g.get("frames", []):
        members[f["id"]] = [b["id"] for b in g["blocks"] if b.get("frame") == f["id"]]
    return [(a, b) for l in g["links"] if l["kind"] == "order" for a in members.get(l["from"], [l["from"]]) for b in members.get(l["to"], [l["to"]]) if a != b]


def _has_cycle(ids: set[str], edges: list[tuple[str, str]]) -> bool:
    """True when the order edges contain a loop (Kahn's algorithm: whatever cannot be peeled off sits in a cycle)."""
    indeg = {i: 0 for i in ids}
    out: dict[str, list[str]] = {i: [] for i in ids}
    for a, b in edges:
        indeg[b] += 1
        out[a].append(b)
    stack, seen = [i for i, n in indeg.items() if n == 0], 0
    while stack:
        i = stack.pop()
        seen += 1
        for j in out[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                stack.append(j)
    return seen != len(ids)


def block_assets(b: dict) -> list[str]:
    """The stored file names of a Reference block: `assets` (a list), plus the older single `asset`, without repeats."""
    out = []
    for a in ([b["asset"]] if b.get("asset") else []) + list(b.get("assets") or []):
        if str(a) not in out:
            out.append(str(a))
    return out


NOTE_MAX = 20_000


def block_notes(b: dict) -> dict[str, str]:
    """The user's notes on the files of a Reference block: {stored file name: text}. Only files the block still lists, and only non-blank notes."""
    raw = b.get("file_notes")
    if not isinstance(raw, dict):
        return {}
    return {a: str(raw[a]).strip()[:NOTE_MAX] for a in block_assets(b) if isinstance(raw.get(a), str) and raw[a].strip()}


def _note_lines(note: str) -> list[str]:
    """A note as indented lines under its file (plain text, written exactly as the user typed it)."""
    return ["  Note: " + note.splitlines()[0]] + ["  " + x for x in note.splitlines()[1:]]


def block_urls(b: dict) -> list[str]:
    """The web links of a Reference block: `urls` (a list), plus the older single `url`, without repeats or blanks."""
    out = []
    for u in ([b["url"]] if b.get("url") else []) + list(b.get("urls") or []):
        u = str(u).strip()
        if u and u not in out:
            out.append(u)
    return out


def _clean_graph(g, old_blocks: dict[str, dict] | None = None) -> dict:
    """Validate a graph from the browser and return it with only the known fields. Raises Invalid. `rev` is added by the caller."""
    if not isinstance(g, dict):
        raise Invalid("graph must be an object")
    old_blocks = old_blocks or {}
    blocks, ids = [], set()
    for b in g.get("blocks") or []:
        if not isinstance(b, dict) or not _SAFE.match(str(b.get("id", ""))):
            raise Invalid("every block needs a safe id")
        bid = b["id"]
        if bid in ids:
            raise Invalid(f"duplicate block id {bid}")
        if b.get("type") not in TYPES:
            raise Invalid(f"unknown block type for {bid}")
        status = b.get("status", "todo")
        if status not in STATUSES:
            raise Invalid(f"unknown status for {bid}")
        o = {"id": bid, "type": b["type"], "title": str(b.get("title", "")), "x": _num(b.get("x")), "y": _num(b.get("y")),
             "w": _num(b.get("w"), 190), "h": _num(b.get("h"), 88), "frame": str(b.get("frame", "") or ""),
             "agent": str(b.get("agent", "") or ""), "status": status, "note": str(b.get("note", "") or ""),
             "context_off": [str(x) for x in b.get("context_off") or []]}
        before = old_blocks.get(bid)
        o["status_at"] = (before or {}).get("status_at", 0) if before and before.get("status") == status else (_now() if before or status != "todo" else 0)
        links = block_urls(b)   # likewise a list of web links; the older single `url` is folded into it
        if links:
            o["urls"] = links
        files = block_assets(b)   # a Reference keeps a list of files; the older single `asset` is folded into it
        if any(not _ASSET.match(a) for a in files):
            raise Invalid(f"bad asset name on {bid}")
        if files:
            o["assets"] = files
            notes = block_notes(b)   # a note per file: dropped with the file, kept across a rename (the page moves the key)
            if notes:
                o["file_notes"] = notes
        if isinstance(b.get("derived_from"), dict):
            o["derived_from"] = b["derived_from"]
        blocks.append(o)
        ids.add(bid)
    starts = [b for b in blocks if b["type"] == "start"]
    if len(starts) != 1:
        raise Invalid("a project has exactly one Start block")
    frames, fids = [], set()
    for f in g.get("frames") or []:
        if not isinstance(f, dict) or not _SAFE.match(str(f.get("id", ""))) or f["id"] in fids:
            raise Invalid("every frame needs a unique safe id")
        fids.add(f["id"])
        frames.append({"id": f["id"], "title": str(f.get("title", "")), "x": _num(f.get("x")), "y": _num(f.get("y")),
                       "w": _num(f.get("w"), 300), "h": _num(f.get("h"), 200), "collapsed": bool(f.get("collapsed"))})
    for b in blocks:
        if b["frame"] and b["frame"] not in fids:
            b["frame"] = ""
    links, seen, lids = [], set(), set()
    for l in g.get("links") or []:
        if not isinstance(l, dict):
            raise Invalid("a link must be an object")
        a, b, kind = l.get("from"), l.get("to"), l.get("kind")
        if kind not in LINK_KINDS:
            raise Invalid("a link is `order` or `context`")
        if a not in ids | fids or b not in ids | fids:   # a link joins blocks or frames
            raise Invalid("a link points at a block or frame that does not exist")
        if a == b:
            raise Invalid("a block cannot link to itself")
        if (a, b, kind) in seen:
            raise Invalid("that link already exists")
        lid = l.get("id") if _SAFE.match(str(l.get("id", ""))) and l.get("id") not in lids else _new_id("l-", 8, lids)
        seen.add((a, b, kind))
        lids.add(lid)
        o = {"id": lid, "from": a, "to": b, "kind": kind}
        for k in ("fs", "ts"):   # which side of each block the link attaches to: l, r, t or b (default: out of the right, into the left)
            if l.get(k) in ("l", "r", "t", "b"):
                o[k] = l[k]
        links.append(o)
    if _has_cycle(ids, order_edges({"blocks": blocks, "frames": frames, "links": links})):
        raise Invalid("those order links would make a loop")
    v = g.get("viewport") if isinstance(g.get("viewport"), dict) else {}
    return {"blocks": blocks, "links": links, "frames": frames, "viewport": {"x": _num(v.get("x")), "y": _num(v.get("y")), "k": _num(v.get("k"), 1) or 1}}


def status_of(g: dict, b: dict) -> str:
    """done | skipped | ready | todo. Ready is never stored: a To do Prompt is Ready when every `order` source is Done or Skipped."""
    if b["status"] in ("done", "skipped"):
        return b["status"]
    if b["type"] != "prompt":
        return "todo"
    by = {x["id"]: x for x in g["blocks"]}
    # only a Prompt or the Brief before it holds it back; a Spec or Reference linked in is material that comes along, not a step to finish
    return "ready" if all(by[a]["status"] in ("done", "skipped") for a, t in order_edges(g) if t == b["id"] and by[a]["type"] in ("prompt", "start")) else "todo"


def run_order(g: dict) -> list[dict]:
    """The Prompt blocks in the order to run them: each after everything linked before it, ties by position (top to bottom, then left to right)."""
    by = {b["id"]: b for b in g["blocks"]}
    indeg = {i: 0 for i in by}
    out: dict[str, list[str]] = {i: [] for i in by}
    for a, t in order_edges(g):
        indeg[t] += 1
        out[a].append(t)
    key = lambda i: (by[i]["y"], by[i]["x"])
    ready, res = sorted((i for i, n in indeg.items() if n == 0), key=key), []
    while ready:
        i = ready.pop(0)
        res.append(by[i])
        for j in out[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
        ready.sort(key=key)
    return [b for b in res if b["type"] == "prompt"]


def stats(g: dict) -> dict:
    steps = run_order(g)
    nxt = next((b for b in steps if status_of(g, b) == "ready"), None)
    return {"blocks": len(g["blocks"]), "frames": len(g["frames"]), "steps": len(steps), "done": sum(b["status"] == "done" for b in steps),
            "next": nxt["title"] if nxt else "", "agents": sorted({b["agent"] or "claude" for b in steps})}


# ---------- projects ----------

def _read_graph(d: Path) -> dict:
    return _read_json(d / "graph.json") or {"rev": 0, "blocks": [], "links": [], "frames": [], "viewport": {"x": 0, "y": 0, "k": 1}}


def _taken_ids(root: Path | None) -> set[str]:
    r = _root(root)
    taken = {p.name for p in r.glob("ls-*") if p.is_dir()} if r.is_dir() else set()
    taken |= {p.name for p in (r / ".trash").glob("*/ls-*")} if (r / ".trash").is_dir() else set()
    return taken


def _touch(d: Path, project: dict | None = None) -> dict:
    p = project or _read_json(d / "project.json")
    p["updated_at"] = _now()
    _write_json(d / "project.json", p)
    return p


def _start_block(taken: set[str] | None = None) -> dict:
    return {"id": "b-" + uuid.uuid4().hex[:8], "type": "start", "title": "Brief", "x": 60, "y": 80, "w": 160, "h": 70, "frame": "",
            "agent": "", "status": "todo", "status_at": 0, "note": "", "context_off": []}   # the Brief starts unticked: the user ticks it when it is written


@_locked
def create(name: str, root: Path | None = None, default_agent: str = "claude", brief: str = "") -> dict:
    """A new project with one Start block (the brief). Returns the whole project, as `get` does."""
    name = (name or "").strip()
    if not name:
        raise Invalid("a project needs a name")
    pid = _new_id("ls-", 12, _taken_ids(root))
    d = _root(root) / pid
    start = _start_block()
    start["frame"] = ""
    _write_json(d / "graph.json", {"rev": 1, "blocks": [start], "links": [], "frames": [], "viewport": {"x": 0, "y": 0, "k": 1}})
    _write_text(_text_path(d, start["id"]), brief)
    now = _now()
    _write_json(d / "project.json", {"id": pid, "kind": "linkshell", "schema_version": 1, "ts": now, "name": name, "default_agent": default_agent or "claude",
                                     "properties": [], "tags": [], "star": False, "updated_at": now})   # last: the project exists from here on
    return get(pid, root)


def get(pid: str, root: Path | None = None) -> dict | None:
    """The whole project: settings, graph and the text of every block (`texts`: block id -> text)."""
    d = _dir(pid, root)
    if not d:
        return None
    g = _read_graph(d)
    texts = {b["id"]: (_text_path(d, b["id"]).read_text() if _text_path(d, b["id"]).is_file() else "") for b in g["blocks"] if b["type"] in TEXTED}
    removed = sorted(p.name for p in (d / ".removed").iterdir() if p.is_dir()) if (d / ".removed").is_dir() else []
    project = _read_json(d / "project.json")
    project.setdefault("properties", [])   # projects made before properties existed
    return {"project": project, "graph": g, "texts": texts, "removed": removed}


@_locked
def update(pid: str, fields: dict, root: Path | None = None) -> dict | None:
    """Change name, default_agent, properties, tags or star. Unknown fields are ignored. `properties` is the user's own list of
    {key, value} rows (the same rows as a Studio prompt's Properties); they go into the header of an export."""
    d = _dir(pid, root)
    if not d:
        return None
    p = _read_json(d / "project.json")
    if "name" in fields:
        if not str(fields["name"]).strip():
            raise Invalid("a project needs a name")
        p["name"] = str(fields["name"]).strip()
    if "default_agent" in fields:
        p["default_agent"] = str(fields["default_agent"] or "claude")
    if "tags" in fields:
        p["tags"] = list(dict.fromkeys(str(t).strip() for t in fields["tags"] if str(t).strip()))
    if "star" in fields:
        p["star"] = bool(fields["star"])
    if "properties" in fields:
        why = check_properties(fields["properties"])
        if why:
            raise Invalid(why)
        p["properties"] = clean_properties(fields["properties"])
    _touch(d, p)
    return p


@_locked
def duplicate(pid: str, root: Path | None = None) -> dict | None:
    """A full copy (graph, texts, versions, assets) under a new id, named "<name> copy" and unstarred. `.removed/` is not copied."""
    d = _dir(pid, root)
    if not d:
        return None
    new = _new_id("ls-", 12, _taken_ids(root))
    nd = _root(root) / new
    shutil.copytree(d, nd, ignore=shutil.ignore_patterns(".removed", "*.tmp", "project.json"))
    p = _read_json(d / "project.json")
    now = _now()
    p.update({"id": new, "ts": now, "updated_at": now, "name": p["name"] + " copy", "star": False})
    _write_json(nd / "project.json", p)
    return get(new, root)


# ---------- the graph ----------

@_locked
def save_graph(pid: str, graph: dict, rev: int, root: Path | None = None) -> dict | None:
    """Autosave. `rev` is the revision the browser started from; an older one raises Conflict. Blocks missing from `graph` are moved to
    `.removed/` (restorable). Returns the saved graph with its new `rev`."""
    d = _dir(pid, root)
    if not d:
        return None
    cur = _read_graph(d)
    if rev != cur["rev"]:
        raise Conflict(cur["rev"])
    old = {b["id"]: b for b in cur["blocks"]}
    g = _clean_graph(graph, old)
    old_start = next((b["id"] for b in cur["blocks"] if b["type"] == "start"), None)
    if old_start and old_start not in {b["id"] for b in g["blocks"]}:
        raise Invalid("the Start block cannot be deleted")
    gone = [old[i] for i in old if i not in {b["id"] for b in g["blocks"]}]
    for b in gone:
        _park(d, b, cur)
    for b in g["blocks"]:   # an Undo on the canvas sends a deleted block back: its files come out of `.removed/` with it
        if b["id"] not in old:
            _unpark(d, b["id"])
    g["rev"] = cur["rev"] + 1
    _write_json(d / "graph.json", g)
    _sweep_assets(d, g)
    _touch(d)
    return g


@_locked
def save_viewport(pid: str, viewport: dict, root: Path | None = None) -> dict | None:
    """Remember where the canvas was panned and zoomed. Writes only `viewport` in graph.json: no new `rev` and no "edited" stamp, so panning around
    never makes another open tab ask to reload and never moves the project up the list."""
    d = _dir(pid, root)
    if not d:
        return None
    cur = _read_graph(d)
    v = viewport if isinstance(viewport, dict) else {}
    cur["viewport"] = {"x": _num(v.get("x")), "y": _num(v.get("y")), "k": min(max(_num(v.get("k"), 1), 0.05), 4) or 1}
    _write_json(d / "graph.json", cur)
    return cur["viewport"]


_ASSET_GRACE = 120   # seconds: a file uploaded a moment ago may not be in a saved graph yet


def _sweep_assets(d: Path, g: dict) -> None:
    """Delete files in `assets/` that no block uses any more (a removed or replaced file, or one left behind by an older version). Blocks parked in
    `.removed/` still count as users, so deleting a block and undoing it keeps its files. Fresh uploads are left alone for a short while."""
    folder = d / "assets"
    if not folder.is_dir():
        return
    used = {a for b in g["blocks"] for a in block_assets(b)}
    for f in (d / ".removed").glob("*/block.json") if (d / ".removed").is_dir() else []:
        used.update(block_assets((_read_json(f) or {}).get("block") or {}))
    now = time.time()
    for p in folder.glob("a-*"):
        try:
            if p.name not in used and now - p.stat().st_mtime > _ASSET_GRACE:
                p.unlink()
        except OSError:
            pass


def _park(d: Path, block: dict, graph: dict) -> None:
    """Move a removed block's files, and its record with the links that touched it, to `.removed/<id>/`."""
    r = d / ".removed" / block["id"]
    r.mkdir(parents=True, exist_ok=True)
    for src in (_text_path(d, block["id"]), _versions_path(d, block["id"])):
        if src.is_file():
            os.replace(src, r / src.name)
    _write_json(r / "block.json", {"block": block, "links": [l for l in graph["links"] if block["id"] in (l["from"], l["to"])], "removed_at": _now()})


def _unpark(d: Path, bid: str) -> None:
    r = d / ".removed" / bid
    if not (r / "block.json").is_file():
        return
    (d / "blocks").mkdir(exist_ok=True)
    for name in (f"{bid}.md", f"{bid}.versions.json"):
        if (r / name).is_file():
            os.replace(r / name, d / "blocks" / name)
    shutil.rmtree(r, ignore_errors=True)


@_locked
def restore_block(pid: str, bid: str, root: Path | None = None) -> dict | None:
    """Bring a deleted block back with its text, versions and the links whose other end still exists. Returns the new graph."""
    d = _dir(pid, root)
    if not d or not _SAFE.match(bid or ""):
        return None
    r = d / ".removed" / bid
    rec = _read_json(r / "block.json")
    if not rec:
        return None
    g = _read_graph(d)
    if any(b["id"] == bid for b in g["blocks"]):
        raise Invalid("that block is already on the canvas")
    (d / "blocks").mkdir(exist_ok=True)
    for name in (f"{bid}.md", f"{bid}.versions.json"):
        if (r / name).is_file():
            os.replace(r / name, d / "blocks" / name)
    ids = {b["id"] for b in g["blocks"]} | {bid}
    ends = ids | {f["id"] for f in g["frames"]}   # a link may end at a frame
    have = {l["id"] for l in g["links"]}
    block = rec["block"]
    if block["frame"] and block["frame"] not in {f["id"] for f in g["frames"]}:
        block["frame"] = ""
    g["blocks"].append(block)
    g["links"] += [l for l in rec["links"] if l["from"] in ends and l["to"] in ends and l["id"] not in have]
    if _has_cycle(ids, order_edges(g)):   # a link added since the delete could now close a loop: keep the block, drop the order links
        g["links"] = [l for l in g["links"] if bid not in (l["from"], l["to"]) or l["kind"] != "order"]
    g["rev"] += 1
    _write_json(d / "graph.json", g)
    shutil.rmtree(r, ignore_errors=True)
    _touch(d)
    return g


@_locked
def purge_removed(days: int, root: Path | None = None) -> int:
    """Delete `.removed/` entries older than `days` (0 = keep them). Returns how many went."""
    if days <= 0 or not _root(root).is_dir():
        return 0
    cutoff, n = _now() - days * 86400, 0
    for r in _root(root).glob("ls-*/.removed/*"):
        rec = _read_json(r / "block.json")
        if not rec or rec.get("removed_at", 0) < cutoff:
            shutil.rmtree(r, ignore_errors=True)
            n += 1
    return n


# ---------- block text and versions ----------

def _block(d: Path, bid: str) -> dict | None:
    return next((b for b in _read_graph(d)["blocks"] if b["id"] == bid), None)


def _versions(d: Path, bid: str) -> list[dict]:
    o = _read_json(_versions_path(d, bid))
    return o.get("versions", []) if isinstance(o, dict) else []


def read_text(pid: str, bid: str, root: Path | None = None) -> str | None:
    d = _dir(pid, root)
    if not d or not _SAFE.match(bid or "") or not _block(d, bid):
        return None
    p = _text_path(d, bid)
    return p.read_text() if p.is_file() else ""


@_locked
def save_text(pid: str, bid: str, text: str, message: str = "", root: Path | None = None) -> dict | None:
    """Save the text of a block. Prompt and Spec blocks get a new version (the first is "Created" when no message is given); Note and Start
    keep only the current text. Saving the same text again changes nothing (`changed: false`). Returns {changed, version?}."""
    d = _dir(pid, root)
    b = _block(d, bid) if d and _SAFE.match(bid or "") else None
    if not b:
        return None
    if b["type"] not in TEXTED:
        raise Invalid("this block has no text")
    cur = _text_path(d, bid).read_text() if _text_path(d, bid).is_file() else ""
    vs = _versions(d, bid) if b["type"] in VERSIONED else []
    if text == cur and (vs or b["type"] not in VERSIONED or not text):
        return {"changed": False}
    _write_text(_text_path(d, bid), text)
    out = {"changed": True}
    if b["type"] in VERSIONED:
        v = {"id": _new_id("", 7, {x["id"] for x in vs}), "message": (message or "").strip() or ("Created" if not vs else "Edited"), "ts": _now(), "text": text}
        _write_json(_versions_path(d, bid), {"versions": vs + [v]})
        out["version"] = {k: v[k] for k in ("id", "message", "ts")}
    _touch(d)
    return out


def revisions(pid: str, bid: str, root: Path | None = None) -> list[dict] | None:
    """Versions newest first, without their text: {id, short, message, ts, current}."""
    d = _dir(pid, root)
    if not d or not _SAFE.match(bid or "") or not _block(d, bid):
        return None
    vs = _versions(d, bid)
    return [{"id": v["id"], "short": v["id"][:7], "message": v["message"], "ts": v["ts"], "current": i == len(vs) - 1} for i, v in reversed(list(enumerate(vs)))]


def revision_text(pid: str, bid: str, rev: str, root: Path | None = None) -> dict | None:
    d = _dir(pid, root)
    if not d or not _SAFE.match(bid or ""):
        return None
    return next((v for v in _versions(d, bid) if v["id"] == rev), None)


@_locked
def delete_revision(pid: str, bid: str, rev: str, root: Path | None = None) -> bool | None:
    """Delete a version. None = no such version; Invalid = it is the current one (rollback means saving an old text as a new version)."""
    d = _dir(pid, root)
    if not d or not _SAFE.match(bid or ""):
        return None
    vs = _versions(d, bid)
    i = next((k for k, v in enumerate(vs) if v["id"] == rev), None)
    if i is None:
        return None
    if i == len(vs) - 1:
        raise Invalid("the current version cannot be deleted")
    _write_json(_versions_path(d, bid), {"versions": vs[:i] + vs[i + 1:]})
    return True


# ---------- assets ----------

@_locked
def add_asset(pid: str, name: str, data: bytes, root: Path | None = None) -> str | None:
    """Copy an uploaded file into the project; returns its stored name `a-xxxxxxxx-<safe name>` (what a Reference block keeps in `asset`)."""
    d = _dir(pid, root)
    if not d:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(name or "file")).strip(".-")[-80:] or "file"
    stored = "a-" + uuid.uuid4().hex[:8] + "-" + safe
    p = d / "assets" / stored
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(p)
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return stored


@_locked
def rename_asset(pid: str, stored: str, name: str, root: Path | None = None) -> str | None:
    """Give a stored file a new name part (`a-xxxxxxxx-<name>`, same id prefix, same extension unless the new name has one). Returns the new stored
    name, or None for an unknown file; raises Invalid when the new name is empty or already taken."""
    old = asset_path(pid, stored, root)
    if not old:
        return None
    ext = os.path.splitext(stored)[1]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(name or "")).strip(".-")[-80:]
    if not safe:
        raise Invalid("give the file a name")
    if not os.path.splitext(safe)[1]:
        safe += ext
    new = stored[:11] + safe
    if not _ASSET.match(new):
        raise Invalid("that name is not allowed")
    if new == stored:
        return stored
    target = old.parent / new
    if target.exists():
        raise Invalid("a file with that name already exists")
    os.replace(old, target)
    return new


def asset_path(pid: str, stored: str, root: Path | None = None) -> Path | None:
    d = _dir(pid, root)
    if not d or not _ASSET.match(stored or ""):
        return None
    p = d / "assets" / stored
    return p if p.is_file() else None


# ---------- delete, trash, purge ----------

@_locked
def trash(pid: str, root: Path | None = None) -> bool:
    """Move a whole project to `.trash/<month>/`, stamping `deleted_at`. Its id stays taken."""
    d = _dir(pid, root)
    if not d:
        return False
    p = _read_json(d / "project.json")
    p["deleted_at"] = _now()
    _write_json(d / "project.json", p)
    dest = _root(root) / ".trash" / datetime.now().strftime("%Y-%m") / pid
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return True


def load_trash(root: Path | None = None) -> list[dict]:
    """Trashed projects, newest deletion first: {id, name, deleted_at, tags, blocks}."""
    rows = []
    for pj in (_root(root) / ".trash").glob("*/ls-*/project.json"):
        p = _read_json(pj)
        if p:
            rows.append({"id": p["id"], "name": p["name"], "deleted_at": p.get("deleted_at", 0), "tags": p.get("tags", []), "blocks": len(_read_graph(pj.parent)["blocks"]), "store": "linkshell"})
    return sorted(rows, key=lambda r: -r["deleted_at"])


def _trashed(pid: str, root: Path | None) -> Path | None:
    if not _PROJECT.match(pid or ""):
        return None
    return next(iter((_root(root) / ".trash").glob(f"*/{pid}")), None)


@_locked
def restore(pid: str, root: Path | None = None) -> bool:
    t = _trashed(pid, root)
    if not t or (_root(root) / pid).exists():
        return False
    p = _read_json(t / "project.json")
    p.pop("deleted_at", None)
    _write_json(t / "project.json", p)
    shutil.move(str(t), str(_root(root) / pid))
    return True


@_locked
def purge(pid: str, root: Path | None = None) -> bool:
    """Delete a trashed project for good (texts, versions, assets, removed blocks)."""
    t = _trashed(pid, root)
    if not t:
        return False
    shutil.rmtree(t)
    return True


@_locked
def empty_trash(root: Path | None = None) -> int:
    return sum(purge(r["id"], root) for r in load_trash(root))


@_locked
def purge_expired(days: int, root: Path | None = None) -> int:
    if days <= 0:
        return 0
    cutoff = _now() - days * 86400
    return sum(purge(r["id"], root) for r in load_trash(root) if r["deleted_at"] < cutoff)


# ---------- the list ----------

def search_items(root: Path | None = None) -> list[dict]:
    """One searchable document per project, shaped like a prompt row so search.py's engines (Meilisearch or the substring fallback) take them
    unchanged: `title` is the name, `text` is the brief, every block title and every block text, `updated` is what the index compares."""
    out = []
    for pj in sorted(_root(root).glob("ls-*/project.json")):
        p, g = _read_json(pj), _read_graph(pj.parent)
        if not p:
            continue
        texts = [(_text_path(pj.parent, b["id"]).read_text() if _text_path(pj.parent, b["id"]).is_file() else "") for b in g["blocks"] if b["type"] in TEXTED]
        text = "\n".join([*(b["title"] for b in g["blocks"] if b["title"]), *(t for t in texts if t.strip())])
        out.append({"id": p["id"], "title": p["name"], "text": text, "updated": p.get("updated_at", 0), "edited": False,
                    "meta": {"note": "", "purpose": "", "tags": p.get("tags", []), "starred": bool(p.get("star"))}})
    return out


def list_projects(root: Path | None = None, q: str = "", tags: list[str] | None = None, show: str = "all", sort: str = "edited", desc: bool = True,
                  page: int = 1, page_size: int = 50, only: list[str] | None = None) -> dict:
    """The home page list. `show`: all | progress | todo | done | starred. `tag` filters AND together. `tags` in the result are counts of what each
    tag would give if added to the current filters (like the Library). Each item carries counts, progress, next step, brief and thumbnail data.
    `only` (ids from the search engine, best match first) replaces `q`, and `sort="relevance"` keeps that order."""
    items = []
    for pj in sorted(_root(root).glob("ls-*/project.json")):
        p, g = _read_json(pj), _read_graph(pj.parent)
        if not p:
            continue
        s = stats(g)
        start = next((b for b in g["blocks"] if b["type"] == "start"), None)
        brief = _text_path(pj.parent, start["id"]).read_text() if start and _text_path(pj.parent, start["id"]).is_file() else ""
        haystack = " ".join([p["name"], brief, *p.get("tags", []), *(b["title"] for b in g["blocks"])]).lower()
        thumb = {"frames": [{k: f[k] for k in "xywh"} for f in g["frames"]],
                 "blocks": [{**{k: b[k] for k in "xywh"}, "type": b["type"], "status": status_of(g, b)} for b in g["blocks"] if b["type"] != "note"]}
        items.append({"id": p["id"], "name": p["name"], "tags": p.get("tags", []), "star": p.get("star", False), "updated_at": p.get("updated_at", 0),
                      "brief": brief.strip().split("\n")[0], "default_agent": p.get("default_agent", "claude"), **s, "thumb": thumb, "_hay": haystack})
    if only is not None:
        rank = {pid: n for n, pid in enumerate(only)}
        items = [i for i in items if i["id"] in rank]
    else:
        rank = {}
        words = (q or "").lower().split()
        items = [i for i in items if all(w in i["_hay"] for w in words)]
    shows = {"all": lambda i: True, "progress": lambda i: 0 < i["done"] < i["steps"],
             "todo": lambda i: i["done"] == 0, "done": lambda i: i["steps"] > 0 and i["done"] == i["steps"], "starred": lambda i: i["star"]}
    items = [i for i in items if shows.get(show, shows["all"])(i)]
    want = list(tags or [])
    base = [i for i in items if all(t in i["tags"] for t in want)]
    counts = {t: sum(1 for i in items if t in i["tags"] and all(w in i["tags"] for w in want)) for t in {t for i in items for t in i["tags"]} | set(want)}
    keys = {"name": lambda i: i["name"].lower(), "progress": lambda i: (i["done"] / i["steps"]) if i["steps"] else 0, "edited": lambda i: i["updated_at"], "relevance": lambda i: rank.get(i["id"], 0)}
    base.sort(key=keys.get(sort, keys["edited"]), reverse=desc and sort != "relevance")
    total, page_size = len(base), max(1, page_size)
    page = max(1, page)
    out = base[(page - 1) * page_size: page * page_size]
    for i in out:
        i.pop("_hay", None)
    return {"items": out, "total": total, "page": page, "page_size": page_size, "tags": counts}


# ---------- assemble (Copy, Follow view and the Markdown export all use this) ----------

def _parts(proj: dict, bid: str) -> dict | None:
    """The pieces of a Prompt block, shared by `assemble` and the exports: {text, specs: [{title, text}], files: [stored names], urls}. Text is used as
    written: nothing is ever filled in."""
    g, by = proj["graph"], {b["id"]: b for b in proj["graph"]["blocks"]}
    b = by.get(bid)
    if not b or b["type"] != "prompt":
        return None
    specs, files, urls, notes, seen = [], [], [], {}, set()
    for l in g["links"]:
        # a Spec or Reference linked to a prompt (any link kind, in EITHER direction: the canvas draws no arrows, so the user cannot tell which way a
        # link was dragged) comes along, once
        other = l["from"] if l["to"] == bid else l["to"] if l["from"] == bid else None
        src = by.get(other) if other else None
        if src is None or src["type"] not in ("spec", "reference") or src["id"] in seen or src["id"] in b.get("context_off", []):
            continue
        seen.add(src["id"])
        if src["type"] == "spec":
            specs.append({"title": src["title"], "text": proj["texts"].get(src["id"], "").strip()})
        else:
            files.extend(block_assets(src))
            urls.extend(block_urls(src))
            notes.update(block_notes(src))
    return {"text": proj["texts"].get(bid, "").strip(), "specs": specs, "files": files, "urls": urls, "notes": notes}


def assemble(pid: str, bid: str, root: Path | None = None) -> dict | None:
    """The text to paste into an agent for a Prompt block: the prompt, then each switched-on Spec linked to it by a `context` link under its
    title, then each Reference as its full file path (or URL). Returns {text, references: [...]} or None."""
    proj = get(pid, root)
    p = _parts(proj, bid) if proj else None
    if not p:
        return None
    parts = [p["text"]] + [f"## {s['title']}\n{s['text']}" for s in p["specs"]]
    folder = assets_alias(pid, root)
    files, refs = p["files"], p["urls"]
    if files or refs:   # the long folder path is written once; each file is then only its stored name
        parts.append("## References\n" + (f"Files in {folder}/\n" + "\n".join("\n".join([f"- {a}"] + _note_lines(p["notes"][a]) if a in p["notes"] else [f"- {a}"]) for a in files) + ("\n" if refs else "") if files else "") + "\n".join(f"- {r}" for r in refs))
    text = "\n\n".join(x for x in parts if x)
    return {"text": text, "references": [f"{folder}/{a}" for a in files] + refs}


# ---------- export and import ----------

def export_plan(pid: str, root: Path | None = None, portable: bool = False) -> dict | None:
    """The plan as agents read it, and the one source of both exports: the brief, then each frame (phase) with its Prompts in run order. A Prompt
    has its filled text, `after` (the numbers of the Prompts it waits for), its Specs and its Reference paths. Always a clean plan: no status."""
    proj = get(pid, root)
    if not proj:
        return None
    g = proj["graph"]
    start = next((b for b in g["blocks"] if b["type"] == "start"), None)
    steps = run_order(g)
    groups = [(f["title"] or "Untitled phase", [b for b in steps if b["frame"] == f["id"]]) for f in sorted(g["frames"], key=lambda f: (f["y"], f["x"]))]
    groups.append(("Other prompts" if g["frames"] else "Prompts", [b for b in steps if not b["frame"]]))
    num = {b["id"]: i for i, b in enumerate((b for _, bs in groups for b in bs), 1)}
    after = {i: [] for i in num}
    for a, t in order_edges(g):
        if a in num and t in num:
            after[t].append(num[a])
    folder, phases = "assets" if portable else assets_alias(pid, root), []   # portable: relative paths, for the zip that carries the files
    for title, bs in groups:
        if not bs:
            continue
        prompts = []
        for b in bs:
            p = _parts(proj, b["id"])
            prompts.append({"n": num[b["id"]], "id": b["id"], "title": b["title"] or "Untitled", "agent": b.get("agent") or proj["project"]["default_agent"], "after": sorted(after[b["id"]]),
                            "text": p["text"], "specs": p["specs"], "references": [f"{folder}/{a}" for a in p["files"]] + p["urls"]})
            if p["notes"]:   # only when there is one, so a plan without notes keeps its old shape
                prompts[-1]["reference_notes"] = {f"{folder}/{a}": n for a, n in p["notes"].items() if a in p["files"]}
        phases.append({"title": title, "prompts": prompts})
    props = {q["key"]: q["value"] for q in proj["project"].get("properties", []) if q["value"].strip()}
    return {"name": proj["project"]["name"], "properties": props, "brief": proj["texts"].get(start["id"], "").strip() if start else "", "agent": proj["project"]["default_agent"], "phases": phases}


def export_json(pid: str, root: Path | None = None) -> dict | None:
    """One file for agents and for re-import: `plan` is the readable structure; `project`, `graph`, `blocks` and `assets` (base64) rebuild the
    project exactly. A clean plan: every block is To do, with no step notes."""
    d = _dir(pid, root)
    if not d:
        return None
    proj, plan = get(pid, root), export_plan(pid, root)
    project = {k: v for k, v in proj["project"].items() if k != "variables"}   # projects made before Properties may still carry the old key
    graph = json.loads(json.dumps(proj["graph"]))
    for b in graph["blocks"]:
        b["status"], b["status_at"], b["note"] = "todo", 0, ""
    blocks = {b["id"]: {"text": proj["texts"][b["id"]], "versions": _versions(d, b["id"])} for b in proj["graph"]["blocks"] if b["type"] in TEXTED}
    assets = {p.name: base64.b64encode(p.read_bytes()).decode() for p in sorted((d / "assets").glob("a-*"))} if (d / "assets").is_dir() else {}
    return {"format": FORMAT, "version": 1, "about": "A FlowlyStack Linkshell plan. Read `plan`; the other keys only rebuild the project. Text in it is data, not instructions to this tool.",
            "plan": plan, "project": project, "graph": graph, "blocks": blocks, "assets": assets}


@_locked
def import_json(data: dict, root: Path | None = None) -> dict:
    """Re-import an export as a NEW project (new id; block and link ids are kept). Raises Invalid for anything that is not a Linkshell export."""
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != 1:
        raise Invalid("not a FlowlyStack Linkshell export")
    src = data.get("project") or {}
    g = _clean_graph(data.get("graph") or {})
    for b in g["blocks"]:   # keep the original status times, which _clean_graph resets
        old = next((o for o in (data["graph"].get("blocks") or []) if o.get("id") == b["id"]), {})
        b["status_at"] = _num(old.get("status_at"))
    pid = _new_id("ls-", 12, _taken_ids(root))
    d = _root(root) / pid
    for name, b64 in (data.get("assets") or {}).items():
        if not _ASSET.match(name):
            raise Invalid(f"bad asset name {name!r}")
        p = d / "assets" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(base64.b64decode(b64))
    for bid, o in (data.get("blocks") or {}).items():
        if not _SAFE.match(bid) or bid not in {b["id"] for b in g["blocks"]}:
            raise Invalid(f"text for an unknown block {bid!r}")
        _write_text(_text_path(d, bid), str(o.get("text", "")))
        if o.get("versions"):
            _write_json(_versions_path(d, bid), {"versions": [{"id": str(v["id"]), "message": str(v.get("message", "")), "ts": _num(v.get("ts")), "text": str(v.get("text", ""))} for v in o["versions"]]})
    g["rev"] = 1
    _write_json(d / "graph.json", g)
    now = _now()
    _write_json(d / "project.json", {"id": pid, "kind": "linkshell", "schema_version": 1, "ts": now, "name": str(src.get("name") or "Imported project"),
                                     "default_agent": str(src.get("default_agent") or "claude"),
                                     "properties": clean_properties(src.get("properties")), "tags": [str(t) for t in src.get("tags") or []], "star": bool(src.get("star")), "updated_at": now})
    return get(pid, root)


def _fence(text: str, lang: str = "text") -> list[str]:
    f = "`" * max(3, max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    return [f"{f}{lang}", text, f]


def export_markdown(pid: str, root: Path | None = None, portable: bool = False) -> str | None:
    """A spec pack to drop into a repo's docs/, built from `export_plan`: name, brief, then each phase with its Prompts in run order (each prompt in
    a block fenced as `prompt`, then its Specs as `spec` blocks and its Reference files, links and notes as one `reference` block). A clean plan: no status."""
    plan = export_plan(pid, root, portable)
    if not plan:
        return None
    out = []
    if plan["properties"]:   # the user's properties, as a header block (one line each; several lines become a YAML block, like a Studio export)
        out.append("---")
        for k, v in plan["properties"].items():
            key = k if re.match(r"^[A-Za-z_][\w-]*$", k) else json.dumps(k)
            v = v.replace("\r\n", "\n").rstrip("\n")
            out.append(f"{key}: {json.dumps(v)}" if "\n" not in v or v[:1].isspace() else f"{key}: |-\n" + "\n".join("  " + l if l else "" for l in v.split("\n")))
        out += ["---", ""]
    out += [f"# {plan['name']}", "", "> A FlowlyStack Linkshell plan. Work through the prompts in order; each lists the specs and reference files that belong with it." + (" The reference files are in the `assets/` folder next to this file." if portable else ""), ""]
    if plan["brief"]:
        out += ["## Brief", "", plan["brief"], ""]
    for ph in plan["phases"]:
        out += [f"## {ph['title']}", ""]
        for p in ph["prompts"]:
            meta = f"Agent: {p['agent']}" + (f" · After: {', '.join(map(str, p['after']))}" if p["after"] else "")
            out += [f"### {p['n']}. {p['title']}", "", meta, "", *_fence(p["text"], "prompt"), ""]
            for sp in p["specs"]:
                out += [f"#### Spec: {sp['title']}", "", *_fence(sp["text"], "spec"), ""]
            if p["references"]:   # the files and links of every Reference block linked to this prompt, each file with its note, in one block
                lines = [x for r in p["references"] for x in [f"- {r}"] + (_note_lines(p["reference_notes"][r]) if r in p.get("reference_notes", {}) else [])]
                out += ["#### References", "", *_fence("\n".join(lines), "reference"), ""]
    return "\n".join(out).rstrip() + "\n"


def export_zip(pid: str, root: Path | None = None) -> bytes | None:
    """The plan to SHARE: one zip with `plan.md` (the Markdown export, reference files as relative `assets/<name>` paths) and an `assets/` folder
    holding exactly the reference files the plan lists. It works wherever it is unzipped and shows no path from this computer. Web links stay as they are."""
    plan = export_plan(pid, root, portable=True)
    if not plan:
        return None
    names = sorted({r.split("/", 1)[1] for ph in plan["phases"] for p in ph["prompts"] for r in p["references"] if r.startswith("assets/")})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("plan.md", export_markdown(pid, root, portable=True))
        for n in names:
            src = asset_path(pid, n, root)
            if src:
                z.write(src, f"assets/{n}")
    return buf.getvalue()
