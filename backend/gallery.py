"""The Gallery snapshot: what the Knowledge / Gallery page draws. Read-only: it reads the Library and Studio
through `promptstore` and the stored vectors through `rag.vectors`; it writes only its own cache (`<data dir>/gallery/snapshot.json`), a
rebuildable file. Nothing is sent anywhere and no model is called: a prompt that has no stored vector is grouped by its words instead.

numpy is imported lazily (inside the functions that need it) so the rest of the app starts without it. The pure functions here take plain
lists and arrays, so `scripts/check_gallery.py` can test them without a server.
"""
from __future__ import annotations

import collections
import datetime
import gzip
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from . import promptstore

ALGO = 1             # bump when the snapshot's content changes shape: forces a rebuild
K = 8                # topic groups (the chart palette has eight categorical colours)
MAP_MAX = 3000       # the map shows the newest this many prompts (t-SNE memory is O(n squared))
MIN_STRUCTURE = 10   # below this many prompts, no groups, map or terms are computed
REPEAT_MIN_CHARS = 40
REPEAT_SIM = {"embeddings": 0.90, "tfidf-svd": 0.72}   # near-duplicate cosine; the embedding value is calibrated on real data (plan 5.6)
NEW_SHARE = 0.05     # a map is recomputed fully when this share of the prompts is new; otherwise new prompts are placed beside their neighbours

STOP = frozenset("""the and for that this with you your are was were will would could should can cant cannot not but have has had having from they them their then than there
here what when where which who whom whose why how all any both each few more most other some such only own same too very just also into out over under again further once about
above below between through during before after against off down our ours its it's i'm i'll i've don't doesn't didn't isn't aren't wasn't won't let lets get got make made use used
using need needs want wants like please thanks thank help one two new now way yes yeah okay ok sure really still much many may might must shall does did done doing been being itself
myself yourself buddy hello hey hi able know see look let's something anything everything going take come give tell say said think thing things kind sort bit lot etc per via within
without across onto upon while whether either neither whats next right first yet because keep then""".split())
_CODE = re.compile(r"```.*?```", re.S)
_URL = re.compile(r"https?://\S+|/[\w./-]{6,}")
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def _np():
    import numpy
    return numpy


# ---------------------------------------------------------------- words

def ignore_set(text: str) -> frozenset[str]:
    """The user's own noise words (Settings > Knowledge): comma, space or line separated, any case."""
    return frozenset(w for w in re.split(r"[\s,;]+", (text or "").lower()) if w)


def tokens(text: str) -> list[str]:
    """Lower-case words of a prompt without code blocks, links and paths. Stop words are NOT removed here (phrases need them as boundaries)."""
    return [w.lower().strip("'-") for w in _WORD.findall(_URL.sub(" ", _CODE.sub(" ", text or "")))]


def keep_words(tk: list[str], extra: frozenset[str] = frozenset()) -> list[str]:
    return [w for w in tk if len(w) > 2 and w not in STOP and w not in extra]


def features(text: str, ts: float) -> dict:
    """What can be counted about one prompt: plain facts, no guessing about tone."""
    local = datetime.datetime.fromtimestamp(ts)
    fences = len(_CODE.findall(text)) + (1 if text.count("```") % 2 else 0)
    return {"ch": len(text), "ln": text.count("\n") + 1, "w": len(text.split()), "q": text.count("?"), "v": len(promptstore.variables(text)), "cd": fences,
            "h": round(local.hour + local.minute / 60, 2), "d": local.strftime("%Y-%m-%d"), "m": local.strftime("%Y-%m")}


def tfidf(docs: list[list[str]]):
    """(vocab, X, Xn): TF-IDF over words seen in 4 prompts to 35% of the prompts (at most 2,500 words), rows L2-normalised."""
    np = _np()
    n = len(docs)
    df = collections.Counter(w for d in docs for w in set(d))
    vocab = sorted((w for w, c in df.items() if c >= min(4, max(2, n // 10)) and c <= 0.35 * n), key=lambda w: (-df[w], w))[:2500]
    vi = {w: i for i, w in enumerate(vocab)}
    idf = np.array([math.log((1 + n) / (1 + df[w])) + 1 for w in vocab], dtype=np.float32)
    X = np.zeros((n, max(len(vocab), 1)), dtype=np.float32)
    for i, d in enumerate(docs):
        for w, c in collections.Counter(w for w in d if w in vi).items():
            X[i, vi[w]] = (1 + math.log(c)) * idf[vi[w]]
    nrm = np.linalg.norm(X, axis=1, keepdims=True)
    nrm[nrm == 0] = 1
    return vocab, X, X / nrm


# ---------------------------------------------------------------- vectors, projection, groups

def _pca(A, dims: int):
    """Centre A and project onto its top `dims` directions (the small Gram matrix, so tall inputs stay cheap)."""
    np = _np()
    A = A - A.mean(0)
    w, v = np.linalg.eigh(A.T @ A)
    order = np.argsort(-w)[:dims]
    return A @ v[:, order]


def space(Xn, vecs):
    """The meaning space every chart uses: stored embeddings when they cover the prompts (`vecs`, one row each), else the words (60 directions of
    the TF-IDF matrix). Returns (unit rows, method). The two spaces are never mixed."""
    np = _np()
    if vecs is not None:
        Z = vecs - vecs.mean(0)
        method = "embeddings"
    else:
        Z, method = _pca(Xn, 60), "tfidf-svd"
    nrm = np.linalg.norm(Z, axis=1, keepdims=True)
    return (Z / np.maximum(nrm, 1e-9)).astype(np.float32), method


def stored_vectors(items: list[dict], model: str, lookup: Callable[[str, list[str]], dict]):
    """One stored vector per prompt, or None when too few are there (the model changed, indexing is off or not finished). The vector of a prompt is
    keyed by the passage text the indexer built (title, tags, purpose and text), not by the raw prompt, so rebuild that text and look it up; a
    prompt of several passages gets the mean. Fewer than 80% covered means the words are used for all of them."""
    if not model or not items:
        return None
    np = _np()
    from .rag import indexer, vectors
    per = [[vectors.text_hash(p["text"]) for p in indexer.prompt_passages(o, "library")] for o in items]
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


def tsne(Zn, perplexity: float = 30.0, iters: int = 600, seed: int = 3):
    """A small t-SNE (numpy only) of unit rows to 2-D, scaled to 0..1. O(n squared) memory: the caller caps n (MAP_MAX)."""
    np = _np()
    n = len(Zn)
    rng = np.random.default_rng(seed)
    A = _pca(Zn, min(40, Zn.shape[1])).astype(np.float32)
    sq = (A ** 2).sum(1)
    D = np.maximum(sq[:, None] + sq[None, :] - 2 * A @ A.T, 0)
    perp = min(perplexity, max(2.0, (n - 1) / 3))
    target = math.log(perp)
    P = np.zeros((n, n), dtype=np.float32)
    idx = np.arange(n)
    for i in range(n):
        d = np.delete(D[i], i).astype(np.float64)
        d -= d.min()
        lo, hi, beta, pr = 0.0, math.inf, 1.0, None
        for _ in range(40):
            pr = np.exp(-d * beta)
            s = pr.sum()
            pr /= s
            H = math.log(s) + beta * (d * pr).sum()
            if abs(H - target) < 1e-4:
                break
            if H > target:
                lo, beta = beta, beta * 2 if hi == math.inf else (beta + hi) / 2
            else:
                hi, beta = beta, beta / 2 if lo == 0 else (beta + lo) / 2
        P[i, idx != i] = pr
    P = np.maximum((P + P.T) / (2 * n), 1e-12)
    del D
    Y = rng.normal(0, 1e-4, (n, 2)).astype(np.float32)
    vel, gains = np.zeros_like(Y), np.ones_like(Y)
    for it in range(iters):
        ex = 12.0 if it < 150 else 1.0
        s2 = (Y ** 2).sum(1)
        num = 1 / (1 + np.maximum(s2[:, None] + s2[None, :] - 2 * Y @ Y.T, 0))
        np.fill_diagonal(num, 0)
        Q = np.maximum(num / num.sum(), 1e-12)
        W = (ex * P - Q) * num
        grad = 4 * (W.sum(1)[:, None] * Y - W @ Y)
        gains = np.maximum(np.where(np.sign(grad) != np.sign(vel), gains + 0.2, gains * 0.8), 0.01)
        vel = (0.5 if it < 250 else 0.8) * vel - 100 * gains * grad
        Y = Y + vel
        Y -= Y.mean(0)
    return (Y - Y.min(0)) / (Y.max(0) - Y.min(0) + 1e-9)


def place_new(Zn, known: dict[int, tuple[float, float]], near: int = 5):
    """Positions for prompts that have none yet: the mean position of their `near` most similar prompts that have one (plus a tiny spread so
    duplicates do not sit exactly on top of each other). `known` maps row index -> (x, y)."""
    np = _np()
    ki = np.array(sorted(known))
    kp = np.array([known[i] for i in ki])
    out = {}
    for i in range(len(Zn)):
        if i in known:
            continue
        s = Zn[ki] @ Zn[i]
        top = np.argsort(-s)[:near]
        x, y = kp[top].mean(0)
        jx, jy = ((i * 7919) % 101 - 50) / 25000, ((i * 104729) % 101 - 50) / 25000   # a fixed, tiny spread
        out[i] = (float(min(1, max(0, x + jx))), float(min(1, max(0, y + jy))))
    return out


def kmeans(Zn, k: int, iters: int = 40, seed: int = 5):
    """k-means on unit rows (cosine): (labels, centroids), groups sorted by size so group 0 is the largest."""
    np = _np()
    rng = np.random.default_rng(seed)
    c = [Zn[rng.integers(len(Zn))]]
    for _ in range(k - 1):
        d = np.min([((Zn - x) ** 2).sum(1) for x in c], axis=0)
        c.append(Zn[rng.choice(len(Zn), p=d / d.sum())] if d.sum() > 0 else Zn[rng.integers(len(Zn))])
    c = np.array(c)
    for _ in range(iters):
        lab = np.argmax(Zn @ c.T, axis=1)
        for j in range(k):
            m = Zn[lab == j]
            if len(m):
                v = m.mean(0)
                c[j] = v / max(np.linalg.norm(v), 1e-9)
    lab = np.argmax(Zn @ c.T, axis=1)
    order = np.argsort(-np.bincount(lab, minlength=k))
    remap = {int(o): i for i, o in enumerate(order)}
    return np.array([remap[int(x)] for x in lab]), c[order]


def group_tree(clusters: list[dict], cent) -> dict:
    """Average-linkage tree over the topic groups (what the dendrogram draws)."""
    np = _np()
    nodes = {k: {"name": clusters[k]["label"], "cluster": k, "value": clusters[k]["n"]} for k in range(len(clusters))}
    live = {k: [k] for k in range(len(clusters))}
    nid = len(clusters)
    while len(live) > 1:
        keys, best = list(live), None
        for a in range(len(keys)):
            for b in range(a + 1, len(keys)):
                s = float(np.mean([cent[i] @ cent[j] for i in live[keys[a]] for j in live[keys[b]]]))
                if best is None or s > best[0]:
                    best = (s, keys[a], keys[b])
        _, a, b = best
        nodes[nid] = {"name": "", "children": [nodes[a], nodes[b]]}
        live[nid] = live.pop(a) + live.pop(b)
        nid += 1
    return nodes[nid - 1]


def repeat_groups(Zn, texts: list[str], times: list[float], labels, threshold: float, top: int = 14, min_group: int = 3) -> list[dict]:
    """Near-duplicate groups: prompts of at least REPEAT_MIN_CHARS whose cosine is above `threshold`, joined by union-find, then tightened (a prompt
    whose average similarity to the rest of its group is too low is dropped, so A~B and B~C do not chain A and C together). Groups of `min_group` (3) or more."""
    np = _np()
    n = len(Zn)
    ok = np.array([len(t) >= REPEAT_MIN_CHARS for t in texts])
    par = list(range(n))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for s in range(0, n, 1000):   # block by block: never a full n x n matrix
        S = Zn[s:s + 1000] @ Zn.T
        for r, c in zip(*np.where(S >= threshold)):
            a, b = s + int(r), int(c)
            if a < b and ok[a] and ok[b]:
                par[find(a)] = find(b)
    grp = collections.defaultdict(list)
    for i in range(n):
        if ok[i]:
            grp[find(i)].append(i)
    out = []
    for g in grp.values():
        while len(g) >= 3:
            S = Zn[g] @ Zn[g].T
            avg = (S.sum(1) - 1) / (len(g) - 1)
            worst = int(np.argmin(avg))
            if avg[worst] >= threshold - 0.06:
                break
            g = g[:worst] + g[worst + 1:]
        if len(g) >= min_group:
            g = sorted(g, key=lambda i: times[i])
            out.append({"n": len(g), "ids": g, "first": times[g[0]], "last": times[g[-1]], "sample": " ".join(texts[g[-1]].split())[:140],
                        "cluster": int(np.bincount(labels[g]).argmax())})
    return sorted(out, key=lambda r: -r["n"])[:top]


# ---------------------------------------------------------------- the snapshot

def _title_terms(X, vocab, mask, n: int):
    np = _np()
    s = X[mask].sum(0) - 0.35 * X.sum(0) * (mask.sum() / len(X))
    return [vocab[i] for i in np.argsort(-s)[:n] if s[i] > 0 and i < len(vocab)]


def empty_snapshot(note: str = "") -> dict:
    return {"version": ALGO, "method": "none", "n": 0, "agents": [], "months": [], "clusters": [], "tree": None, "terms": [], "network": {"nodes": [], "edges": []},
            "bigrams": [], "repeats": [], "rows": [], "life": {"library": 0, "studio": 0, "lib_groups": [], "stu_groups": []}, "treemap": {"name": "prompts", "children": []},
            "vtrees": [], "map": {"kind": "none", "shown": 0, "cap": MAP_MAX}, "note": note}


def build(lib: list[dict], studio: list[dict], *, ignore: frozenset[str] = frozenset(), vecs_for: Callable[[list[dict]], object] = lambda items: None,
          versions_of: Callable[[dict], int] = lambda o: 0, studio_versions: Callable[[dict], list[dict]] = lambda o: [], prev: dict | None = None,
          force_map: bool = False) -> dict:
    """Build the whole snapshot from loaded prompts (`promptstore.load_all` items). `vecs_for(items)` returns one stored vector per item or None."""
    np = _np()
    items = sorted((o for o in lib if (o.get("text") or "").strip()), key=lambda o: float(o.get("ts") or 0))
    n = len(items)
    if n == 0:
        snap = empty_snapshot()
        snap["life"] = _life([], studio, studio_versions)
        return snap
    texts = [o["text"] for o in items]
    times = [float(o.get("ts") or 0) for o in items]
    tk = [tokens(t) for t in texts]
    docs = [keep_words(t, ignore) for t in tk]
    feats = [features(t, ts) for t, ts in zip(texts, times)]
    rows = []
    for i, o in enumerate(items):
        m = o.get("meta", {})
        rows.append({"i": i, "id": o["id"], "t": int(times[i] * 1000), "a": o.get("agent") or "claude", "c": 0, "x": None, "y": None, **feats[i],
                     "s": " ".join(texts[i].split())[:150], "title": m.get("title") or "", "tags": list(m.get("tags") or []), "star": bool(m.get("starred")),
                     "nv": versions_of(o), "proj": o.get("project") or "", "model": o.get("model") or ""})
    snap = empty_snapshot()
    snap.update({"n": n, "agents": sorted({r["a"] for r in rows}), "months": sorted({r["m"] for r in rows}), "rows": rows,
                 "life": _life(rows, studio, studio_versions), "treemap": _treemap(rows), "vtrees": _vtrees(studio, studio_versions)})
    if n < MIN_STRUCTURE:
        return snap
    vocab, X, Xn = tfidf(docs)
    Zn, method = space(Xn, vecs_for(items))
    k = max(1, min(K, n // 6))
    lab, cent = kmeans(Zn, k)
    for i, r in enumerate(rows):
        r["c"] = int(lab[i])
    clusters = []
    for g in range(k):
        mask = lab == g
        members = np.where(mask)[0]
        tt = _title_terms(X, vocab, mask, 8)
        clusters.append({"id": g, "n": int(mask.sum()), "terms": tt, "label": " · ".join(tt[:3]) or f"group {g + 1}",
                         "termn": [sum(1 for i in members if t in set(docs[i])) for t in tt]})
    # map: newest MAP_MAX prompts; a stored map is kept when few prompts are new (plan 5.4)
    snap["map"] = _positions(rows, Zn, method, prev, force_map)
    snap.update({"method": method, "clusters": clusters, "tree": group_tree(clusters, cent) if k > 1 else {"name": clusters[0]["label"], "cluster": 0, "value": n}})
    snap.update(_terms(docs, tk, lab, ignore, n))
    snap["repeats"] = repeat_groups(Zn, texts, times, lab, REPEAT_SIM[method])
    return snap


def _positions(rows: list[dict], Zn, method: str, prev: dict | None, force: bool) -> dict:
    """Fill x, y in `rows` (only the newest MAP_MAX). Returns the map status."""
    n = len(rows)
    lo = max(0, n - MAP_MAX)
    old = {}
    if prev and not force and prev.get("method") == method:
        old = {r["id"]: (r["x"], r["y"]) for r in prev.get("rows", []) if r.get("x") is not None}
    known = {i: old[r["id"]] for i, r in enumerate(rows) if i >= lo and r["id"] in old}
    new = (n - lo) - len(known)
    if known and new <= NEW_SHARE * (n - lo) and len(known) >= 10:
        pos = dict(known)
        for i, v in place_new(Zn[lo:], {i - lo: v for i, v in known.items()}).items():
            pos[i + lo] = v
        kind = "placed"
    else:
        Y = tsne(Zn[lo:])
        pos = {lo + j: (float(Y[j, 0]), float(Y[j, 1])) for j in range(len(Y))}
        kind = "full"
    for i, (x, y) in pos.items():
        rows[i]["x"], rows[i]["y"] = round(x, 4), round(y, 4)
    return {"kind": kind, "shown": n - lo, "cap": MAP_MAX}


def _terms(docs, tk, lab, ignore, n: int) -> dict:
    df = collections.Counter(w for d in docs for w in set(d))
    lo, hi = min(5, max(2, n // 10)), 0.35 * n
    score = {w: df[w] * math.log(n / df[w]) for w in df if lo <= df[w] <= hi}
    top = sorted(score, key=lambda w: (-score[w], w))[:110]
    post = collections.defaultdict(list)
    topset = set(top)
    for i, d in enumerate(docs):
        for w in set(d):
            if w in topset:
                post[w].append(i)
    terms = []
    for w in top:
        pc = collections.Counter(int(lab[i]) for i in post[w])
        terms.append({"w": w, "df": df[w], "score": round(score[w], 1), "cluster": pc.most_common(1)[0][0], "ids": post[w]})
    tn = top[:46]
    sets = {w: set(post[w]) for w in tn}
    edges = []
    for a in range(len(tn)):
        for b in range(a + 1, len(tn)):
            inter = len(sets[tn[a]] & sets[tn[b]])
            if inter >= min(6, max(2, n // 20)) and inter / len(sets[tn[a]] | sets[tn[b]]) >= 0.10:
                edges.append({"a": tn[a], "b": tn[b], "n": inter, "j": round(inter / len(sets[tn[a]] | sets[tn[b]]), 3)})
    cl = {t["w"]: t["cluster"] for t in terms}
    bgids = collections.defaultdict(set)
    for i, t in enumerate(tk):
        for x, y in zip(t, t[1:]):
            if x not in STOP and y not in STOP and x not in ignore and y not in ignore and len(x) > 2 and len(y) > 2:
                bgids[(x, y)].add(i)
    minb = min(4, max(2, n // 20))
    bigrams = [{"a": a, "b": b, "n": len(v), "ids": sorted(v)} for (a, b), v in sorted(bgids.items(), key=lambda kv: (-len(kv[1]), kv[0])) if len(v) >= minb][:30]
    return {"terms": terms, "network": {"nodes": [{"w": w, "df": df[w], "cluster": cl[w]} for w in tn], "edges": edges}, "bigrams": bigrams}


def _life(rows: list[dict], studio: list[dict], studio_versions) -> dict:
    untouched = [r for r in rows if not (r["title"] or r["tags"] or r["star"])]
    tagged = [r for r in rows if (r["title"] or r["tags"]) and not r["star"]]
    starred = [r for r in rows if r["star"]]
    edited = lambda rs: sum(1 for r in rs if r["nv"] >= 2)
    by = collections.defaultdict(list)
    for s in studio:
        by[(s.get("meta") or {}).get("status") or "draft"].append(s)
    return {"library": len(rows), "studio": len(studio),
            "lib_groups": [{"name": "Kept as captured", "n": len(untouched), "edited": edited(untouched)}, {"name": "Titled or tagged", "n": len(tagged), "edited": edited(tagged)},
                           {"name": "Starred", "n": len(starred), "edited": edited(starred)}],
            "stu_groups": [{"name": k.title(), "n": len(v), "edited": sum(1 for s in v if len(studio_versions(s)) >= 2)} for k, v in sorted(by.items())]}


def _treemap(rows: list[dict]) -> dict:
    cnt = collections.Counter((r["a"], os.path.basename(r["proj"].rstrip("/")) if r["proj"] else (r["model"] or "other")) for r in rows)
    by = collections.defaultdict(list)
    for (a, pj), c in cnt.items():
        by[a].append({"name": pj or "other", "value": c})
    out = []
    for a, ch in by.items():
        ch.sort(key=lambda c: (-c["value"], c["name"]))
        if len(ch) > 9:
            ch = ch[:8] + [{"name": "others", "value": sum(c["value"] for c in ch[8:])}]
        out.append({"name": a, "children": ch})
    return {"name": "prompts", "children": sorted(out, key=lambda a: -sum(c["value"] for c in a["children"]))}


def _vtrees(studio: list[dict], studio_versions) -> list[dict]:
    out = []
    for s in studio:
        vs = studio_versions(s)
        if len(vs) >= 2:
            out.append({"id": s["id"], "title": s.get("title") or "", "status": (s.get("meta") or {}).get("status") or "draft",
                        "versions": [{"id": v.get("id"), "msg": v.get("message", ""), "ts": float(v.get("ts") or 0)} for v in vs]})
    return sorted(out, key=lambda s: -len(s["versions"]))[:5]


# ---------------------------------------------------------------- the running copy: cache file, signature, one background build

def gz(obj) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), 5)


class Gallery:
    """The snapshot of the running app. `get()` answers at once with the newest snapshot it has (possibly out of date, flagged `stale`) and starts
    one background build when the prompts, the embedding model, the stored vectors or the ignore words changed."""

    def __init__(self, data_dir: Path, library_dir: Path, studio_dir: Path, *, model: Callable[[], str], ignore: Callable[[], str], vector_lookup: Callable | None,
                 vector_count: Callable[[str], int] = lambda m: 0, recheck: float = 5.0):
        self.dir = Path(data_dir) / "gallery"
        self.library_dir, self.studio_dir = library_dir, studio_dir
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
        self._load()

    # -- files
    def _path(self) -> Path:
        return self.dir / "snapshot.json"

    def _load(self) -> None:
        try:
            o = json.loads(self._path().read_text())
            if o.get("snapshot", {}).get("version") == ALGO:
                self._snap, self._sig, self._built_at = o["snapshot"], o.get("sig", ""), o.get("built_at", 0.0)
        except (OSError, ValueError, AttributeError):
            pass

    def _save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="snapshot.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"sig": self._sig, "built_at": self._built_at, "snapshot": self._snap}, f, separators=(",", ":"), ensure_ascii=False)
            os.replace(tmp, self._path())
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- what the snapshot depends on
    def _items(self):
        return promptstore.load_all(self.library_dir), promptstore.load_all(self.studio_dir)

    def signature(self, lib=None, studio=None) -> str:
        if lib is None:
            lib, studio = self._items()
        h = hashlib.sha1(f"{ALGO}|{self.model()}|{sorted(ignore_set(self.ignore()))}|{self.vcount(self.model())}".encode())
        for o in lib:
            h.update(f"{o['id']}|{o.get('updated')}\n".encode())
        for o in studio:
            h.update(f"{o['id']}|{o.get('updated')}\n".encode())
        return h.hexdigest()

    def is_current(self, lib=None, studio=None) -> bool:
        """True when the stored snapshot still matches the prompts, the model, the ignore words and the vectors (the same signature `get()` uses to decide on a
        rebuild, so an add, an edit, a delete or a settings change all count). Never starts a build; False when there is no snapshot."""
        with self._lock:
            have, snap = self._sig, self._snap
        return snap is not None and self.signature(lib, studio) == have

    # -- building
    def _versions(self, o: dict) -> int:
        try:
            return len(promptstore._read_versions(Path(o["_path"])))
        except Exception:
            return 0

    def _studio_versions(self, o: dict) -> list[dict]:
        try:
            return promptstore._read_versions(Path(o["_path"]))
        except Exception:
            return []

    def _vecs(self, items):
        if self.lookup is None:
            return None
        try:
            return stored_vectors(items, self.model(), self.lookup)
        except Exception:
            return None   # never fail a build over the vector copy: the words are used instead

    def build_now(self, force_map: bool = False) -> dict:
        """Build synchronously and store the result (used by the background thread and by tests)."""
        lib, studio = self._items()
        sig = self.signature(lib, studio)
        snap = build(lib, studio, ignore=ignore_set(self.ignore()), vecs_for=self._vecs, versions_of=self._versions, studio_versions=self._studio_versions,
                     prev=self._snap, force_map=force_map)
        snap["model"], snap["ignored"] = self.model(), sorted(ignore_set(self.ignore()))
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
                    lib, studio = self._items()
                    self._want = self.signature(lib, studio)
                except Exception as e:
                    self._error = f"{type(e).__name__}: {e}"
                if self._snap is None or self._want != self._sig:
                    self._busy = True
                    threading.Thread(target=self._run, daemon=True).start()
            return self._answer()

    def rebuild(self, force_map: bool = False) -> dict:
        with self._lock:
            if not self._busy:
                self._busy, self._force_map = True, force_map
                threading.Thread(target=self._run, daemon=True).start()
            return self._answer()

    def _answer(self) -> dict:
        s = self._snap
        return {"status": {"state": "building" if self._busy else ("error" if self._error and s is None else "ready"), "stale": bool(self._busy and s is not None),
                           "built_at": self._built_at, "error": self._error, "method": (s or {}).get("method", ""), "prompts": (s or {}).get("n", 0),
                           "model": self.model()}, "snapshot": s}
