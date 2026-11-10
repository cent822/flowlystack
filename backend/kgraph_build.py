"""Lattice, base layer: the graph FlowlyStack computes by itself, with no model call.

Nodes are Library prompts, Studio prompts, Collections documents, collections, tags (a tag used by two or more items) and projects (a project
folder used by two or more Library prompts). Edges are explicit facts from the user's files (`in_collection`, `tagged`, `derived_from`, `in_project`,
`followed_by` = the next prompt of the same session, `same_text` = identical text, `refers_to` = both name the same link, file or ticket id (through a
`reference` node used by two or more items), `refers_doc` = the text names a document of a collection) or estimated (`similar`, the closest items by meaning).
A Linkshell project is a `linkshell` node only when it has a real connection: `used_in` (a Library or Studio prompt whose text is identical to one of its Prompt or Spec
blocks, a block loaded From Studio, or a Studio prompt saved from one of its blocks) or `refers_to` (a link, file or ticket id in its Reference blocks that another item also
names). Linkshell blocks are never nodes and their text is never stored. Read-only on the user's prompts, documents, Linkshell projects and
vectors; the only thing written is the rebuildable cache `<data dir>/kgraph/base.json`. The snapshot holds ids, titles and numbers, never text.

numpy is imported lazily (as in gallery.py) so the app starts without it. `ALGO` forces a rebuild when the snapshot's shape changes: bump it.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from . import collections as co
from . import gallery as g
from . import kgraph_refs
from . import promptstore

ALGO = 4
LS_CAP = 500          # Linkshell projects read (a scan of each project's block texts)
REF_CAP = 3000        # reference nodes kept (the most shared first)
REF_PER_ITEM = 30     # reference lines kept per item (the most shared first): a pasted log with 500 paths must not drown the picture
DOC_NAMES_MAX = 300   # documents whose name contains a space are matched by substring only up to this many (a scan per prompt)
SAME_MIN = 20         # a text shorter than this ("yes", "continue") is never an exact-duplicate line: it would join unrelated prompts
CAP = 6000            # items drawn (newest first); the page says when more exist
TOPK = 12             # neighbours kept per item; the page's slider filters them again without a rebuild
MIN_SCORE = 0.2       # similarity below this is never stored: on the real library the closest-12 scores had a median of 0.40 (phase 1 measurement)
TEXT_CLIP = 20_000    # characters of one item used for the words fallback
BLOCK = 512


def _np():
    return g._np()


# ---------------------------------------------------------------- gathering (read-only)

def gather(library_dir: Path | None, studio_dir: Path | None, collections_root: Path | None) -> tuple[list[dict], list[dict]]:
    """(items, collections). Every item: id, type (prompt | studio | document), title, tags, cols, derived, updated, text (clipped, for the words
    fallback) and vt (the texts its stored vectors are keyed by)."""
    from .rag import indexer
    items: list[dict] = []
    for root, kind, src in ((library_dir, "prompt", "library"), (studio_dir, "studio", "studio")):
        if root is None:
            continue
        for o in promptstore.load_all(root):
            text = (o.get("text") or "").strip()
            d = o.get("derived_from") or {}
            lib = kind == "prompt"   # session and project come from the capture; Studio prompts are written on purpose and have neither
            lsd = d.get("id", "") if isinstance(d, dict) and d.get("store") == "linkshell" and kind == "studio" else ""   # saved from a Linkshell block
            items.append({"id": o["id"], "lsd": lsd, "type": kind, "title": o.get("title") or o["id"], "tags": list((o.get("meta") or {}).get("tags") or []), "cols": [],
                          "ts": float(o.get("ts") or 0), "session": str(o.get("session_id") or "") if lib else "", "project": str(o.get("project") or "").strip() if lib else "",
                          "derived": d.get("id", "") if isinstance(d, dict) and d.get("store") == "library" else "", "updated": float(o.get("updated") or 0),
                          "text": text[:TEXT_CLIP], "vt": [p["text"] for p in indexer.prompt_passages(o, src)]})
    cols = []
    for cid in co._collection_ids(collections_root):
        c = co.get(cid, collections_root)
        if c:
            cols.append({"id": cid, "name": c.get("name") or cid, "tags": list(c.get("tags") or []), "updated": float(c.get("updated_at") or 0)})
    for d in co.all_documents(collections_root):
        ps = [p.get("text", "") for p in co.passages(d["id"], collections_root)]
        items.append({"id": d["id"], "type": "document", "title": d.get("name") or d["id"], "tags": [], "cols": list(d["collections"]), "derived": "", "ts": 0.0, "session": "", "project": "",
                      "updated": float(d.get("updated_at") or d.get("ts") or 0), "text": " ".join(ps)[:TEXT_CLIP], "vt": [t for t in ps if t.strip()]})
    return items, cols


def _norm(text: str) -> str:
    """The key an exact-duplicate line uses: the clipped text, case and spacing ignored (the same rule as `same_text`)."""
    return " ".join((text or "").strip()[:TEXT_CLIP].casefold().split())


def gather_linkshell(library_dir: Path | None) -> list[dict]:
    """Linkshell projects, read-only (`<library_dir>/linkshell`, never anywhere else, so a test with a temp folder cannot reach the real projects):
    {id, name, updated, texts (the normalised text of each Prompt and Spec block, only when it has SAME_MIN characters or more), studio (ids of Studio
    prompts a block was loaded From), urls (the links of its Reference blocks as one text)}. Block text is only compared with: it is never kept in the snapshot."""
    if library_dir is None:
        return []
    from . import linkshell
    root = Path(library_dir) / "linkshell"
    out: list[dict] = []
    for pj in sorted(root.glob("ls-*/project.json"))[:LS_CAP]:
        try:
            d = linkshell.get(pj.parent.name, root)
        except (OSError, ValueError):
            continue
        if not d:
            continue
        texts, studio, urls = [], [], []
        for b in d["graph"]["blocks"]:
            if b["type"] in ("prompt", "spec"):
                k = _norm(d["texts"].get(b["id"], ""))
                if len(k) >= SAME_MIN:
                    texts.append(k)
            if b["type"] == "reference":
                urls.extend(str(u) for u in (b.get("urls") or []) if str(u).strip())
            df = b.get("derived_from")
            if isinstance(df, dict) and df.get("store") == "studio" and df.get("id"):
                studio.append(str(df["id"]))
        out.append({"id": pj.parent.name, "name": str(d["project"].get("name") or pj.parent.name), "updated": float(d["project"].get("updated_at") or 0),
                    "texts": sorted(set(texts)), "studio": sorted(set(studio)), "urls": " ".join(urls)})
    return out


def stored_vectors(items: list[dict], model: str, lookup: Callable[[str, list[str]], dict]):
    """One stored vector per item: the mean of its passages' vectors (the same keying as gallery.py and gallery_docs.py: sha256 of the text the indexer
    embedded, plus the model). None when fewer than 80% of the items are covered: then the words are used for all of them, never a mix."""
    if not model or not items:
        return None
    np = _np()
    from .rag.vectors import text_hash
    per = [[text_hash(t) for t in i["vt"]] for i in items]
    found = lookup(model, sorted({h for hs in per for h in hs}))
    rows, miss = [], 0
    for hs in per:
        vs = [found[h] for h in hs if h in found]
        rows.append(np.mean(vs, axis=0) if vs else None)
        miss += 0 if vs else 1
    if len(items) - miss < 0.8 * len(items):
        return None
    mean = np.mean([r for r in rows if r is not None], axis=0)
    return np.array([r if r is not None else mean for r in rows], dtype=np.float32)


# ---------------------------------------------------------------- building

def neighbours(Z, k: int = TOPK, floor: float = MIN_SCORE) -> list[tuple]:
    """The closest items by cosine (Z has unit rows): (i, j, score, rank) with i < j, each pair once, kept when either side lists it, rank the better
    of the two sides (0 is the closest). Blocks of rows, so 6,000 items stay small in memory."""
    np = _np()
    n = len(Z)
    if n < 2:
        return []
    k = min(k, n - 1)
    pairs: dict[tuple, list] = {}
    for a in range(0, n, BLOCK):
        S = Z[a:a + BLOCK] @ Z.T
        S[np.arange(S.shape[0]), np.arange(a, a + S.shape[0])] = -2.0
        top = np.argpartition(-S, k - 1, axis=1)[:, :k]
        for r in range(S.shape[0]):
            i = a + r
            order = sorted(top[r], key=lambda j: -S[r, j])
            for rank, j in enumerate(order):
                sc = float(S[r, j])
                if sc < floor:
                    break
                key = (i, int(j)) if i < j else (int(j), i)
                cur = pairs.get(key)
                if cur is None:
                    pairs[key] = [sc, rank]
                elif rank < cur[1]:
                    cur[1] = rank
    return [(i, j, round(v[0], 3), v[1]) for (i, j), v in pairs.items()]


def empty_snapshot(note: str = "") -> dict:
    return {"algo": ALGO, "n_items": 0, "capped": 0, "method": "none", "note": note, "nodes": [], "edges": [], "counts": {}, "scores": {}}


def build(items: list[dict], cols: list[dict], *, vecs_for: Callable[[list[dict]], object] = lambda items: None, ignore: frozenset[str] = frozenset(),
          cap: int = CAP, topk: int = TOPK, floor: float = MIN_SCORE, linkshell: list[dict] | None = None) -> dict:
    """The base snapshot: `nodes` [{id, t, n (title), d (connections)}], `edges` [[from, to, kind, score, rank]] (node numbers). Never reads text out of
    the snapshot: titles only."""
    if not items and not cols:
        return empty_snapshot("Nothing to connect yet.")
    items = sorted(items, key=lambda i: (-i["updated"], i["id"]))
    capped = max(0, len(items) - cap)
    items = items[:cap]
    nodes: list[dict] = []
    at: dict[str, int] = {}

    def add(id_: str, t: str, title: str) -> None:
        at[id_] = len(nodes)
        nodes.append({"id": id_, "t": t, "n": (title or id_)[:120], "d": 0})

    for it in items:
        add(it["id"], it["type"], it["title"])
    for c in cols:
        add(c["id"], "collection", c["name"])
    uses: dict[str, int] = {}
    for it in items:
        for t in {x.strip().lower() for x in it["tags"] if x.strip()}:
            uses[t] = uses.get(t, 0) + 1
    tags = sorted(t for t, n in uses.items() if n >= 2)
    for t in tags:
        add("tag:" + t, "tag", t)
    pu: dict[str, int] = {}
    for it in items:
        if it["project"]:
            pu[it["project"]] = pu.get(it["project"], 0) + 1
    for pj in sorted(p for p, n in pu.items() if n >= 2):
        add("project:" + pj, "project", pj)
    # references: a link, file or ticket id named (literally, by pattern) in the text of two or more items becomes one node
    found = {it["id"]: kgraph_refs.extract(it["text"]) for it in items}
    for ls in linkshell or []:   # the links in a project's Reference blocks count as one more item that names them
        found["linkshell:" + ls["id"]] = kgraph_refs.extract(ls["urls"])
    use: dict[str, int] = {}
    shown: dict[str, tuple] = {}
    for fs in found.values():
        for key, (disp, sub) in fs.items():
            use[key] = use.get(key, 0) + 1
            shown.setdefault(key, (disp, sub))
    for key in sorted((k for k, n in use.items() if n >= 2), key=lambda k: (-use[k], k))[:REF_CAP]:
        add("ref:" + key, "reference", shown[key][0])
        nodes[-1]["rk"] = shown[key][1]

    # Linkshell projects: a node only with a real connection, never a block, never block text (see the module note)
    ls_lines: list[tuple] = []   # (from id, to id, kind)
    if linkshell:
        by_text: dict[str, list[str]] = {}
        for it in items:
            if it["type"] in ("prompt", "studio"):
                k = " ".join(it["text"].casefold().split())
                if len(k) >= SAME_MIN:
                    by_text.setdefault(k, []).append(it["id"])
        studio_ids = {it["id"] for it in items if it["type"] == "studio"}
        saved_from: dict[str, list[str]] = {}
        for it in items:
            if it.get("lsd"):
                saved_from.setdefault(it["lsd"], []).append(it["id"])
        for ls in linkshell:
            lid = "linkshell:" + ls["id"]
            hit = {iid for k in ls["texts"] for iid in by_text.get(k, ())}   # identical text to one of its Prompt or Spec blocks
            hit.update(s for s in ls["studio"] if s in studio_ids)           # a block loaded From Studio
            hit.update(saved_from.get(ls["id"], ()))                          # a Studio prompt saved from one of its blocks
            refs = [k for k in sorted(found.get(lid, {}), key=lambda k: (-use[k], k)) if "ref:" + k in at][:REF_PER_ITEM]
            if hit or refs:
                add(lid, "linkshell", ls["name"])
                ls_lines += [(iid, lid, "used_in") for iid in sorted(hit)] + [(lid, "ref:" + k, "refers_to") for k in refs]

    edges: list[list] = [[at[a], at[b], kind, 1, 0] for a, b, kind in ls_lines]
    for it in items:
        for cid in it["cols"]:
            if cid in at:
                edges.append([at[it["id"]], at[cid], "in_collection", 1, 0])
        for t in {x.strip().lower() for x in it["tags"] if x.strip()}:
            if "tag:" + t in at:
                edges.append([at[it["id"]], at["tag:" + t], "tagged", 1, 0])
        if it["derived"] and it["derived"] in at and nodes[at[it["derived"]]]["t"] == "prompt":
            edges.append([at[it["id"]], at[it["derived"]], "derived_from", 1, 0])
    for c in cols:
        for t in {x.strip().lower() for x in c["tags"] if x.strip()}:
            if "tag:" + t in at:
                edges.append([at[c["id"]], at["tag:" + t], "tagged", 1, 0])

    # facts from the capture (no model): the project a prompt came from, the next prompt of the same session, identical text
    sessions: dict[str, list] = {}
    for it in items:
        if it["project"] and "project:" + it["project"] in at:
            edges.append([at[it["id"]], at["project:" + it["project"]], "in_project", 1, 0])
        if it["session"]:
            sessions.setdefault(it["session"], []).append(it)
    for sess in sessions.values():
        sess.sort(key=lambda i: (i["ts"], i["id"]))
        for a, b in zip(sess, sess[1:]):   # a chain in time order, one line per prompt: it joins no hub
            edges.append([at[a["id"]], at[b["id"]], "followed_by", 1, 0])
    for it in items:   # every item to the shared references it names (the most shared first, at most REF_PER_ITEM)
        mine = sorted((k for k in found[it["id"]] if "ref:" + k in at), key=lambda k: (-use[k], k))[:REF_PER_ITEM]
        for key in mine:
            edges.append([at[it["id"]], at["ref:" + key], "refers_to", 1, 0])
    docs: dict[str, list] = {}   # a prompt that names a document of a collection by its file name
    spaced: list[tuple] = []
    for it in items:
        if it["type"] == "document" and len(it["title"]) >= 5:
            nm = it["title"].casefold().strip()
            if " " in nm:
                spaced.append((nm, it["id"]))
            else:
                docs.setdefault(nm, []).append(it["id"])
    spaced = spaced if len(spaced) <= DOC_NAMES_MAX else []
    if docs or spaced:
        for it in items:
            if it["type"] not in ("prompt", "studio"):
                continue
            low = it["text"].casefold()
            hit: set[str] = set()
            for nm in kgraph_refs.file_names(it["text"]):
                hit.update(docs.get(nm, ()))
            for nm, did in spaced:
                if nm in low:
                    hit.add(did)
            for did in sorted(hit):
                edges.append([at[it["id"]], at[did], "refers_doc", 1, 0])
    same: dict[str, list] = {}
    for it in items:
        if it["type"] in ("prompt", "studio"):
            key = " ".join(it["text"].casefold().split())
            if len(key) >= SAME_MIN:
                same.setdefault(key, []).append(it)
    for grp in same.values():
        if len(grp) > 1:
            grp.sort(key=lambda i: (i["ts"] or i["updated"], i["id"]))
            for other in grp[1:]:   # every copy to the oldest one
                edges.append([at[other["id"]], at[grp[0]["id"]], "same_text", 1, 0])

    # similarity: only items with text; stored vectors when they cover 80% of them, else the words (never mixed)
    texted = [it for it in items if it["text"].strip()]
    method, scores = "none", {}
    if len(texted) >= 2:
        np = _np()
        tk = [g.keep_words(g.tokens(it["text"]), ignore) for it in texted]
        _, _, Xn = g.tfidf(tk)
        Z, method = g.space(Xn, vecs_for(texted))
        sims = neighbours(Z, topk, floor)
        for i, j, sc, rank in sims:
            edges.append([at[texted[i]["id"]], at[texted[j]["id"]], "similar", sc, rank])
        if sims:
            arr = np.array([s[2] for s in sims])
            scores = {f"p{p}": round(float(np.percentile(arr, p)), 3) for p in (10, 50, 90, 99)}
    for e in edges:
        nodes[e[0]]["d"] += 1
        nodes[e[1]]["d"] += 1
    counts: dict[str, int] = {}
    for nd in nodes:
        counts[nd["t"]] = counts.get(nd["t"], 0) + 1
    kinds: dict[str, int] = {}
    for e in edges:
        kinds[e[2]] = kinds.get(e[2], 0) + 1
    return {"algo": ALGO, "n_items": len(items), "capped": capped, "method": method, "note": "", "nodes": nodes, "edges": edges, "counts": counts,
            "edge_counts": kinds, "orphans": sum(1 for n in nodes if n["t"] in ("prompt", "studio", "document") and n["d"] == 0), "scores": scores}


# ---------------------------------------------------------------- the running snapshot

class KGraph:
    """The base snapshot of the running app. `get()` answers at once with the newest snapshot it has (flagged `stale` while a new one builds) and starts
    one background build when the items, collections, embedding model or stored vectors changed (modelled on gallery.Gallery)."""

    def __init__(self, data_dir: Path, library_dir: Path | None, studio_dir: Path | None, collections_root: Path | None, *, model: Callable[[], str],
                 ignore: Callable[[], str], vector_lookup: Callable | None, vector_count: Callable[[str], int] = lambda m: 0, recheck: float = 5.0):
        self.dir = Path(data_dir) / "kgraph"
        self.library_dir, self.studio_dir, self.root = library_dir, studio_dir, collections_root
        self.model, self.ignore, self.lookup, self.vcount = model, ignore, vector_lookup, vector_count
        self.recheck = recheck
        self._lock = threading.Lock()
        self._snap: dict | None = None
        self._sig = ""
        self._checked = 0.0
        self._want = ""
        self._busy = False
        self._error = ""
        self._built_at = 0.0
        self._load()

    def _path(self) -> Path:
        return self.dir / "base.json"

    def _load(self) -> None:
        try:
            d = json.loads(self._path().read_text())
            if d.get("algo") == ALGO and isinstance(d.get("snapshot"), dict):
                self._snap, self._sig, self._built_at = d["snapshot"], d.get("sig", ""), float(d.get("built_at") or 0)
        except (OSError, ValueError):
            pass

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="base.", suffix=".tmp")
        try:
            with open(fd, "w") as f:
                json.dump({"algo": ALGO, "sig": self._sig, "built_at": self._built_at, "snapshot": self._snap}, f, separators=(",", ":"))
            Path(tmp).replace(self._path())
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _gather(self):
        return gather(self.library_dir, self.studio_dir, self.root)

    def _ls(self) -> list[dict]:
        return gather_linkshell(self.library_dir)

    def signature(self, items=None, cols=None, ls=None) -> str:
        if items is None:
            items, cols = self._gather()
        if ls is None:
            ls = self._ls()
        m = self.model() or ""
        h = hashlib.sha1(json.dumps([ALGO, sorted((i["id"], i["updated"], sorted(i["cols"]), i["derived"], i["session"], i["project"], i.get("lsd", "")) for i in items),
                                     sorted((c["id"], c["updated"], c["name"]) for c in cols), m, self.vcount(m) if m else 0,
                                     sorted(g.ignore_set(self.ignore())),
                                     sorted((p["id"], p["updated"], p["name"], hashlib.sha1("\n".join(p["texts"]).encode()).hexdigest(), p["studio"], p["urls"]) for p in ls)],
                                    sort_keys=True).encode())
        return h.hexdigest()

    def _vecs(self, items):
        if self.lookup is None:
            return None
        try:
            return stored_vectors(items, self.model(), self.lookup)
        except Exception:
            return None   # never fail a build over the vector copy: the words are used instead

    def build_now(self) -> dict:
        """Build synchronously and store the result (used by the background thread and by tests)."""
        items, cols = self._gather()
        ls = self._ls()
        sig = self.signature(items, cols, ls)
        snap = build(items, cols, vecs_for=self._vecs, ignore=g.ignore_set(self.ignore()), linkshell=ls)
        snap["model"] = self.model()
        with self._lock:
            self._snap, self._sig, self._built_at, self._error = snap, sig, time.time(), ""
        self._save()
        return snap

    def _run(self) -> None:
        try:
            self.build_now()
        except Exception as e:   # shown in the status, retried on the next look
            with self._lock:
                self._error = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:
                self._busy, self._checked = False, (time.time() + 25 if self._error else 0.0)

    def get(self) -> dict:
        now = time.time()
        with self._lock:
            if not self._busy and now - self._checked >= self.recheck:   # first look: _checked is 0; after a failure it is 25 s ahead (no hot retry loop)
                self._checked = now
                try:
                    self._want = self.signature()
                except Exception as e:
                    self._error = f"{type(e).__name__}: {e}"
                if self._snap is None or self._want != self._sig:
                    self._busy = True
                    threading.Thread(target=self._run, daemon=True).start()
            return self._answer()

    def rebuild(self) -> dict:
        with self._lock:
            if not self._busy:
                self._busy = True
                threading.Thread(target=self._run, daemon=True).start()
            return self._answer()

    def _answer(self) -> dict:
        s = self._snap
        return {"status": {"state": "building" if self._busy else ("error" if self._error and s is None else "ready"), "stale": bool(self._busy and s is not None),
                           "error": self._error, "built_at": self._built_at, "method": (s or {}).get("method", "none")}, "snapshot": s}
