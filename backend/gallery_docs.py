"""The Gallery snapshot for Documents mode. Same engine as `gallery.py` (it imports its pure functions), a different
unit: one row per imported document. Read-only: documents and passages are read through `collections`, stored vectors through the portable copy
(`rag.vectors`), nothing else; the only file written is the rebuildable cache `<data dir>/gallery/documents.json`. No model is called and nothing is
sent anywhere: a document with no stored vector is grouped by its words instead, and the two spaces are never mixed.

`build_documents` is pure (plain dicts in, a snapshot out) so `scripts/check_gallery_docs.py` can test it without a server. numpy is imported lazily.
`DocGallery` owns the cache, the signature and one background build, as `gallery.Gallery` does for prompts (copied on purpose, not shared: the prompts
Gallery must not change).
"""
from __future__ import annotations

import collections
import datetime
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from . import collections as co
from . import gallery as g
from . import promptstore

ALGO_DOCS = 6          # bump when the snapshot's content changes shape: forces a rebuild
MIN_STRUCTURE = 10     # below this many documents: no groups, map or words (the page lists the newest documents)
MIN_CARD = 15          # cards that need a crowd (word network, phrases, repeats, craft ...) say so below this many documents
DOC_CHARS = 300_000    # the word charts read at most this much of one document (a 500-page PDF must not dominate or stall a build)
EDGES_PER_NODE = 3     # the word network keeps at most this many lines per word: long documents share most words, and every word joined to every other is a hairball
JUNK_LETTERS = 0.4     # a document of 200+ characters where fewer than this share are letters is flagged `junk` and left out of the word charts
_HEAD = re.compile(r"^\s{0,3}#{1,6}\s", re.M)
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s|^\s*\|", re.M)   # a list item or a table row
_NONSPACE = re.compile(r"\S")

# The Craft measurements of a document. `tr` names a transform the browser knows (log, sqrt, lin); a scale ends at the 99th percentile unless `cap` is given.
FEATURES_DOCS = [
    {"k": "w", "name": "Words", "tr": "log"},
    {"k": "np", "name": "Passages", "tr": "log"},
    {"k": "hd", "name": "Headings", "tr": "sqrt"},
    {"k": "cd", "name": "Code blocks", "tr": "sqrt"},
    {"k": "nm", "name": "Numbers", "tr": "lin", "unit": "%"},
    {"k": "ls", "name": "List lines", "tr": "lin", "unit": "%"},
]
CORR_DOCS = ["w", "hd", "nm", "ls"]   # the four measurements of the Craft scatter matrix


def doc_features(text: str, passages: int) -> dict:
    """What can be counted about one document: plain facts, one pass over the text, no model. Words are counted from the passages, so the short
    tail repeated between two pieces of one section counts twice (about)."""
    fences = len(g._CODE.findall(text)) + (1 if text.count("```") % 2 else 0)
    nonspace = len(_NONSPACE.findall(text)) or 1
    letters = sum(1 for c in text if c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    lines = [ln for ln in text.splitlines() if ln.strip()]
    listy = len(_LIST.findall(text))
    return {"w": len(text.split()), "np": passages, "hd": len(_HEAD.findall(text)), "cd": fences,
            "nm": round(100 * digits / nonspace, 1), "ls": round(100 * listy / max(1, len(lines)), 1),
            "junk": len(text) >= 200 and letters / nonspace < JUNK_LETTERS}


def empty_documents(note: str = "") -> dict:
    return {"version": ALGO_DOCS, "mode": "documents", "method": "none", "n": 0, "agents": [], "months": [], "clusters": [], "tree": None, "terms": [],
            "network": {"nodes": [], "edges": []}, "bigrams": [], "repeats": [], "rows": [], "types": [], "collections": [], "features": FEATURES_DOCS, "corr": CORR_DOCS,
            "treemap": {"name": "documents", "children": []}, "map": {"kind": "none", "shown": 0, "cap": g.MAP_MAX}, "junk": 0,
            "use": {"history": False, "chats": 0, "exchanges": 0}, "nearest": {}, "min_card": MIN_CARD, "min_structure": MIN_STRUCTURE, "note": note}


def stored_vectors(items: list[dict], model: str, lookup: Callable[[str, list[str]], dict]):
    """One stored vector per document: the mean of its passages' vectors. A passage vector is keyed by the sha256 of the raw passage text (no embedding
    prefix) and the model, exactly as the indexer stores it. Fewer than 80% of the documents covered means None: the words are used for all of them."""
    if not model or not items:
        return None
    np = g._np()
    from .rag.vectors import text_hash
    per = [[text_hash(t) for t in d["passages"]] for d in items]
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


def chat_citations(root=None) -> dict | None:
    """What saved chats cited: {"chats", "exchanges", "cited": {document id: number of exchanges that cited it}}, or None when no saved exchange exists
    (History is off, or nothing was asked). **Cited** = a retrieved passage of the document that carries a citation number (it went to the model); a
    passage that was found but not sent does not count. Chats of every live collection and of My prompts are read; the files are only read."""
    cited: collections.Counter = collections.Counter()
    chats = exchanges = 0
    for d in co.chat_dirs(root):
        for p in sorted(d.glob("ch-*.json")):
            try:
                c = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            exs = c.get("exchanges") if isinstance(c, dict) else None
            if not exs:
                continue
            chats += 1
            for ex in exs:
                exchanges += 1
                refs = {x.get("ref") for x in ex.get("retrieved") or [] if isinstance(x, dict) and x.get("cite") is not None and str(x.get("ref", "")).startswith("kd-")}
                cited.update(refs)
    return {"chats": chats, "exchanges": exchanges, "cited": dict(cited)} if exchanges else None


def chat_stamp(root=None) -> str:
    """A cheap fingerprint of the chat files (names, sizes, times): no file is read."""
    h = hashlib.sha1()
    for d in co.chat_dirs(root):
        for p in sorted(d.glob("ch-*.json")):
            try:
                st = p.stat()
            except OSError:
                continue
            h.update(f"{d.parent.name}/{p.name}|{st.st_size}|{st.st_mtime_ns}\n".encode())
    return h.hexdigest()


def _sparse_edges(edges: list[dict], per: int = EDGES_PER_NODE) -> list[dict]:
    """Each word keeps its `per` strongest lines (a line stays when it is among either end's strongest), so no word loses all its links and the picture
    does not fall into one clump of the strongest pairs. At most `per` lines for each word, strongest first."""
    best = collections.defaultdict(list)
    for e in sorted(edges, key=lambda e: (-e["j"], -e["n"], e["a"], e["b"])):
        for w_ in (e["a"], e["b"]):
            if len(best[w_]) < per:
                best[w_].append(e)
    keep = {id(e) for es in best.values() for e in es}
    return [e for e in sorted(edges, key=lambda e: (-e["j"], -e["n"], e["a"], e["b"])) if id(e) in keep]


def _nearest(V, lib: list[dict], P, top: int = 5) -> dict:
    """For each document (row index as a string) its closest Library prompts by meaning: cosine of the stored vectors, which share one embedding model."""
    np = g._np()
    if V.shape[1] != P.shape[1] or not len(lib):
        return {}
    Vn = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-9)
    Pn = P / np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
    out = {}
    for s in range(0, len(Vn), 500):
        S = Vn[s:s + 500] @ Pn.T
        idx = np.argsort(-S, axis=1)[:, :top]
        for r in range(S.shape[0]):
            out[str(s + r)] = [{"id": lib[j]["id"], "t": lib[j]["t"], "s": round(float(S[r, j]), 3)} for j in idx[r]]
    return out


def _treemap(rows: list[dict], names: dict[str, str]) -> dict:
    """File type, then the document's first collection (by name), sized by words. A document in several collections is counted once here."""
    cnt = collections.Counter()
    for r in rows:
        cnt[(r["a"], names.get(r["cols"][0], r["cols"][0]) if r["cols"] else "none")] += max(1, r["w"])
    by = collections.defaultdict(list)
    for (a, c), v in cnt.items():
        by[a].append({"name": c, "value": v})
    out = []
    for a, ch in by.items():
        ch.sort(key=lambda c: (-c["value"], c["name"]))
        if len(ch) > 9:
            ch = ch[:8] + [{"name": "others", "value": sum(c["value"] for c in ch[8:])}]
        out.append({"name": a, "children": ch})
    return {"name": "documents", "children": sorted(out, key=lambda a: -sum(c["value"] for c in a["children"]))}


def build_documents(docs: list[dict], *, names: dict[str, str] | None = None, ignore: frozenset[str] = frozenset(),
                    vecs_for: Callable[[list[dict]], object] = lambda items: None, prev: dict | None = None, force_map: bool = False,
                    cites: dict | None = None, prompts_for: Callable[[], object] = lambda: None) -> dict:
    """The whole documents snapshot. `docs`: `{id, name, type, ts, cols: [collection ids], passages: [text, ...]}`; `names`: collection id -> name;
    `vecs_for(items)` returns one stored vector per document or None. `cites` is `chat_citations()` (None without saved chats); `prompts_for()` returns
    `(library prompts [{id, t}], their stored vectors)` or None, for the closest-prompts card (only when the groups come from embeddings)."""
    np = g._np()
    names = names or {}
    items = sorted((d for d in docs if any((t or "").strip() for t in d["passages"])), key=lambda d: (float(d.get("ts") or 0), d["id"]))
    n = len(items)
    snap = empty_documents()
    if n == 0:
        return snap
    texts = ["\n\n".join(d["passages"]) for d in items]
    rows = []
    for i, (d, t) in enumerate(zip(items, texts)):
        ts = float(d.get("ts") or 0)
        cols = sorted(d.get("cols") or [], key=lambda c: (names.get(c, c).lower(), c))
        rows.append({"i": i, "id": d["id"], "t": int(ts * 1000), "a": d.get("type") or "unknown", "c": 0, "x": None, "y": None, **doc_features(t, len(d["passages"])),
                     "s": " ".join(t[:400].split())[:150], "title": d.get("name") or d["id"], "m": datetime.datetime.fromtimestamp(ts).strftime("%Y-%m"),
                     "cols": cols, "cited": cites["cited"].get(d["id"], 0) if cites else None})
    cc = collections.Counter(c for r in rows for c in r["cols"])
    snap.update({"n": n, "agents": sorted({r["a"] for r in rows}), "months": sorted({r["m"] for r in rows}), "rows": rows,
                 "types": [{"type": a, "n": c} for a, c in sorted(collections.Counter(r["a"] for r in rows).items(), key=lambda kv: (-kv[1], kv[0]))],
                 "collections": [{"id": c, "name": names.get(c, c), "n": k} for c, k in sorted(cc.items(), key=lambda kv: (-kv[1], names.get(kv[0], kv[0]).lower()))],
                 "treemap": _treemap(rows, names), "junk": sum(1 for r in rows if r["junk"]),
                 "use": {"history": bool(cites), "chats": cites["chats"] if cites else 0, "exchanges": cites["exchanges"] if cites else 0}})
    if n < MIN_STRUCTURE:
        snap["note"] = f"Groups and the map need {MIN_STRUCTURE} documents; you have {n}."
        return snap
    tk = [[] if r["junk"] else g.tokens(t[:DOC_CHARS]) for r, t in zip(rows, texts)]
    words = [g.keep_words(t, ignore) for t in tk]
    vocab, X, Xn = g.tfidf(words)
    V = vecs_for(items)
    Zn, method = g.space(Xn, V)
    k = max(1, min(g.K, n // 6))
    lab, cent = g.kmeans(Zn, k)
    for i, r in enumerate(rows):
        r["c"] = int(lab[i])
    clusters = []
    for gi in range(k):
        mask = lab == gi
        members = np.where(mask)[0]
        tt = g._title_terms(X, vocab, mask, 8)
        clusters.append({"id": gi, "n": int(mask.sum()), "terms": tt, "label": " · ".join(tt[:3]) or f"group {gi + 1}",
                         "termn": [sum(1 for i in members if t in set(words[i])) for t in tt]})
    snap["map"] = g._positions(rows, Zn, method, prev, force_map)
    snap.update({"method": method, "clusters": clusters,
                 "tree": g.group_tree(clusters, cent) if k > 1 else {"name": clusters[0]["label"], "cluster": 0, "value": n}})
    snap.update(g._terms(words, tk, lab, ignore, n))
    net = snap["network"]
    net["edges"] = _sparse_edges(net["edges"])   # real documents gave 977 lines among 46 words
    snap["bigrams"] = [b for b in snap["bigrams"] if b["a"] != b["b"]]   # "backend backend" comes from paths and tables, not from phrases
    if V is not None:
        got = prompts_for()
        if got:
            snap["nearest"] = _nearest(V, *got)
    snap["repeats"] = g.repeat_groups(Zn, [t[:2000] for t in texts], [r["t"] / 1000 for r in rows], lab, g.REPEAT_SIM[method], min_group=2)
    return snap


def build_passage_map(docs: list[dict], *, model: str, lookup: Callable | None, prev: dict | None = None, force: bool = False) -> dict:
    """The passage map of the Structure slide: the newest `gallery.MAP_MAX` passages that have a stored vector, placed by t-SNE over those vectors.
    **Stored vectors only**: a passage without one is left out (there is no word fallback for passages), and with no model or fewer than
    `MIN_STRUCTURE` covered passages the answer is `kind: "none"` with a `reason` (`no_model`, `no_vectors`) the page shows. A passage keeps its place across
    builds when few passages are new (the same rule as the documents map). Points: `{d: document id, n: passage number, x, y, s: first words}`; colours come
    from the document's own row in the browser."""
    out = {"kind": "none", "reason": "", "total": 0, "shown": 0, "missing": 0, "cap": g.MAP_MAX, "pts": []}
    items = [(d["id"], n, t) for d in sorted(docs, key=lambda d: (float(d.get("ts") or 0), d["id"])) for n, t in enumerate(d["passages"]) if (t or "").strip()]
    out["total"] = len(items)
    if not model or lookup is None:
        out["reason"] = "no_model"
        return out
    from .rag.vectors import text_hash
    cand = items[-g.MAP_MAX:]
    found = lookup(model, sorted({text_hash(t) for _, _, t in cand}))
    keep = [(i, n, t, found[text_hash(t)]) for i, n, t in cand if text_hash(t) in found]
    out["missing"] = len(cand) - len(keep)
    if len(keep) < MIN_STRUCTURE:
        out["reason"] = "no_vectors"
        return out
    np = g._np()
    Zn, _ = g.space(None, np.array([k[3] for k in keep], dtype=np.float32))
    pr = [{"id": f"{i}#{n}", "x": None, "y": None} for i, n, _t, _v in keep]
    stub = {"method": "embeddings", "rows": [{"id": f"{p['d']}#{p['n']}", "x": p["x"], "y": p["y"]} for p in prev["pts"]]} if prev and prev.get("kind") not in (None, "none") else None
    status = g._positions(pr, Zn, "embeddings", stub, force)
    out.update({"kind": status["kind"], "shown": len(keep), "pts": [{"d": i, "n": n, "x": r["x"], "y": r["y"], "s": " ".join(t[:300].split())[:100]} for (i, n, t, _v), r in zip(keep, pr)]})
    return out


def load_documents(root=None) -> tuple[list[dict], dict[str, str]]:
    """Every live document whose text is available (`passages.json` not empty), with its collection ids, and the collection names. Read-only."""
    docs, names = [], {}
    for d in co.all_documents(root):
        ps = [p.get("text", "") for p in co.passages(d["id"], root)]
        if not any(t.strip() for t in ps):
            continue
        for cid in d["collections"]:
            if cid not in names:
                names[cid] = (co.get(cid, root) or {}).get("name") or cid
        docs.append({"id": d["id"], "name": d.get("name") or d["id"], "type": d.get("type") or "unknown", "ts": d.get("ts") or 0,
                     "cols": list(d["collections"]), "passages": ps})
    return docs, names


class DocGallery:
    """The documents snapshot of the running app. `get()` answers at once with the newest snapshot it has (possibly out of date, flagged `stale`) and starts
    one background build when the documents, their collections, the embedding model, the stored vectors or the ignore words changed."""

    def __init__(self, data_dir: Path, collections_root: Path | None, *, model: Callable[[], str], ignore: Callable[[], str],
                 vector_lookup: Callable | None, vector_count: Callable[[str], int] = lambda m: 0, recheck: float = 5.0, library_dir: Path | None = None):
        self.dir = Path(data_dir) / "gallery"
        self.root = collections_root
        self.library_dir = library_dir
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
        self._force_map = False
        self._pdata: dict | None = None   # the passage map (built on request, kept in passages.json)
        self._psig = ""
        self._pbusy = False
        self._pchecked = 0.0
        self._perror = ""
        self._pbuilt = 0.0
        self._pforce = False
        self._load()

    # -- files
    def _path(self) -> Path:
        return self.dir / "documents.json"

    def _load(self) -> None:
        try:
            o = json.loads(self._path().read_text())
            if o.get("snapshot", {}).get("version") == ALGO_DOCS:
                self._snap, self._sig, self._built_at = o["snapshot"], o.get("sig", ""), o.get("built_at", 0.0)
        except (OSError, ValueError, AttributeError):
            pass
        try:
            o = json.loads((self.dir / "passages.json").read_text())
            if o.get("algo") == ALGO_DOCS:
                self._pdata, self._psig, self._pbuilt = o["part"], o.get("sig", ""), o.get("built_at", 0.0)
        except (OSError, ValueError, AttributeError, KeyError):
            pass

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="documents.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"sig": self._sig, "built_at": self._built_at, "snapshot": self._snap}, f, separators=(",", ":"), ensure_ascii=False)
            os.replace(tmp, self._path())
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _psave(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="passages.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"algo": ALGO_DOCS, "sig": self._psig, "built_at": self._pbuilt, "part": self._pdata}, f, separators=(",", ":"), ensure_ascii=False)
            os.replace(tmp, self.dir / "passages.json")
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- what the snapshot depends on (no passage text is read here: a stat per document is enough)
    def signature(self) -> str:
        h = hashlib.sha1(f"{ALGO_DOCS}|{self.model()}|{sorted(g.ignore_set(self.ignore()))}|{self.vcount(self.model())}".encode())
        h.update(f"chats:{chat_stamp(self.root)}\n".encode())   # citations come from the saved chats
        if self.library_dir and self.model():   # the closest-prompts card reads the Library
            for o in promptstore.load_all(self.library_dir):
                h.update(f"{o['id']}|{o.get('updated')}\n".encode())
        for d in co.all_documents(self.root):
            h.update(f"{d['id']}|{co.passages_stamp(d['id'], self.root)}|{d.get('name')}|{d.get('type')}|{sorted(d['collections'])}\n".encode())
            for cid in d["collections"]:
                h.update(f"{cid}={(co.get(cid, self.root) or {}).get('name')}\n".encode())
        return h.hexdigest()

    def psignature(self) -> str:
        """What the passage map depends on: the documents' passages, the model and the number of stored vectors (no chats, no Library)."""
        h = hashlib.sha1(f"{ALGO_DOCS}|passages|{self.model()}|{self.vcount(self.model())}".encode())
        for d in co.all_documents(self.root):
            h.update(f"{d['id']}|{co.passages_stamp(d['id'], self.root)}\n".encode())
        return h.hexdigest()

    # -- building
    def _vecs(self, items):
        if self.lookup is None:
            return None
        try:
            return stored_vectors(items, self.model(), self.lookup)
        except Exception:
            return None   # never fail a build over the vector copy: the words are used instead

    def _prompts(self):
        """The Library prompts and their stored vectors for the closest-prompts card; None without a model, vectors or a library."""
        if self.lookup is None or not self.library_dir or not self.model():
            return None
        try:
            lib = [o for o in promptstore.load_all(self.library_dir) if (o.get("text") or "").strip()]
            P = g.stored_vectors(lib, self.model(), self.lookup)
            if P is None:
                return None
            return [{"id": o["id"], "t": (o.get("meta") or {}).get("title") or " ".join(o["text"].split())[:80]} for o in lib], P
        except Exception:
            return None

    def build_now(self, force_map: bool = False) -> dict:
        """Build synchronously and store the result (used by the background thread and by tests)."""
        sig = self.signature()
        docs, names = load_documents(self.root)
        snap = build_documents(docs, names=names, ignore=g.ignore_set(self.ignore()), vecs_for=self._vecs, prev=self._snap, force_map=force_map,
                              cites=chat_citations(self.root), prompts_for=self._prompts)
        snap["model"], snap["ignored"] = self.model(), sorted(g.ignore_set(self.ignore()))
        with self._lock:
            self._snap, self._sig, self._built_at, self._error = snap, sig, time.time(), ""
        self._save()
        return snap

    def _run(self) -> None:
        try:
            self.build_now(self._force_map)
        except Exception as e:   # shown in the status, retried on the next look
            with self._lock:
                self._error = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:   # a failed build is not retried for about 30 s (rechecks happen every `recheck` seconds)
                self._busy, self._force_map, self._checked = False, False, (time.time() + 25 if self._error else 0.0)

    def get(self) -> dict:
        now = time.time()
        with self._lock:
            if not self._busy and (now - self._checked >= self.recheck or self._snap is None):
                self._checked = now
                try:
                    self._want = self.signature()
                except Exception as e:
                    self._error = f"{type(e).__name__}: {e}"
                if self._snap is None or self._want != self._sig:
                    self._busy = True
                    threading.Thread(target=self._run, daemon=True).start()
            return self._answer()

    def rebuild(self, force_map: bool = False) -> dict:
        with self._lock:
            if force_map:
                self._pforce, self._psig = True, ""   # a full redraw of the document map redraws the passage map too, if one was ever asked for
            if not self._busy:
                self._busy, self._force_map = True, force_map
                threading.Thread(target=self._run, daemon=True).start()
            return self._answer()

    # -- the passage map: built only when asked for (the Structure card's Passages view), in the background, kept until the passages or vectors change
    def passages(self) -> dict:
        now = time.time()
        with self._lock:
            if not self._pbusy and (now - self._pchecked >= self.recheck or self._pdata is None):
                self._pchecked = now
                try:
                    want = self.psignature()
                except Exception as e:
                    want = None
                    self._perror = f"{type(e).__name__}: {e}"
                if want is not None and (self._pdata is None or want != self._psig):
                    self._pbusy = True
                    threading.Thread(target=self._prun, args=(want,), daemon=True).start()
            return self._panswer()

    def _prun(self, want: str) -> None:
        try:
            docs, _names = load_documents(self.root)
            part = build_passage_map(docs, model=self.model(), lookup=self.lookup, prev=self._pdata, force=self._pforce)
            with self._lock:
                self._pdata, self._psig, self._pbuilt, self._perror = part, want, time.time(), ""
            self._psave()
        except Exception as e:
            with self._lock:
                self._perror = f"{type(e).__name__}: {e}"
        finally:
            with self._lock:
                self._pbusy, self._pforce, self._pchecked = False, False, (time.time() + 25 if self._perror else 0.0)

    def _panswer(self) -> dict:
        p = self._pdata
        state = "building" if self._pbusy else ("error" if self._perror and p is None else ("none" if p and p["kind"] == "none" else "ready"))
        return {"status": {"state": state, "stale": bool(self._pbusy and p is not None), "built_at": self._pbuilt, "error": self._perror, "reason": (p or {}).get("reason", ""),
                           "model": self.model()}, "part": p if p and p["kind"] != "none" else None}

    def _answer(self) -> dict:
        s = self._snap
        return {"status": {"state": "building" if self._busy else ("error" if self._error and s is None else "ready"), "stale": bool(self._busy and s is not None),
                           "built_at": self._built_at, "error": self._error, "method": (s or {}).get("method", ""), "documents": (s or {}).get("n", 0),
                           "model": self.model()}, "snapshot": s}
