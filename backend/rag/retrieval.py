"""Hybrid retrieval over collections: a vector search and a keyword search merged with reciprocal
rank fusion. Small functions on purpose: the chat, the Sources panel and, later, an agentic chat mode and the MCP tools all call these
unchanged. Text returned from here is data, never instructions, for whoever reads it.
"""
from __future__ import annotations

from ..assistant.base import ProviderError
from . import embedding
from .indexer import Indexer
from .vectors import VectorError

RRF_K = 60   # the usual damping constant of reciprocal rank fusion


def _fuse(vector_hits: list[dict], keyword_hits: list[dict]) -> list[dict]:
    """One list, best first. A passage that both searches found beats one that only a single search found."""
    merged: dict[str, dict] = {}
    for rank, h in enumerate(vector_hits, 1):
        merged[h["id"]] = {"id": h["id"], "ref": h["ref"], "vector_score": round(h["score"], 4), "vector_rank": rank, "keyword_rank": None, "rrf": 1 / (RRF_K + rank)}
    for h in keyword_hits:
        m = merged.setdefault(h["id"], {"id": h["id"], "ref": h["ref"], "vector_score": None, "vector_rank": None, "keyword_rank": None, "rrf": 0.0})
        m["keyword_rank"] = h["rank"]
        m["rrf"] += 1 / (RRF_K + h["rank"])
    best = 2 / (RRF_K + 1)   # what a passage ranked first by both searches scores
    out = sorted(merged.values(), key=lambda m: -m["rrf"])
    for m in out:
        m["score"] = round(m.pop("rrf") / best, 4)   # 0 to 1
    return out


def search(indexer: Indexer, provider, query: str, scope: list[str] | None = None, source: str = "", tags: list[str] | None = None,
           k: int = 6) -> dict:
    """The best `k` passages for a question. `scope` is a list of collection ids (`"prompts"` = Library and Studio); empty = everywhere.
    Returns {"passages": [...], "mode": "hybrid" | "keyword", "note": str}. Each passage: id, ref, n, source, name, locator, text, tags,
    collections, score (0 to 1), vector_score (cosine, or None), keyword_rank (or None). Without a usable vector index, or when Ollama does
    not answer, the keyword search alone is used and `note` says why."""
    query = (query or "").strip()
    if not query:
        return {"passages": [], "mode": "keyword", "note": ""}
    scope = [c for c in (scope or []) if c]
    tags = [t for t in (tags or []) if t]
    wide = max(k * 4, 20)   # candidates from each search before fusion
    note, vector_hits = "", []
    store, model = indexer.search_store(), indexer.model()
    if not model:
        note = "No embedding model is chosen yet, so only keyword search is used."
    elif store is None:
        note = "Nothing is indexed with vectors yet, so only keyword search is used."
    else:
        try:
            if provider is None:
                raise ProviderError("Ollama is not configured")
            vec = provider.embed(model, [embedding.question_text(model, query)])[0]
            where = {k_: v for k_, v in (("collections", scope), ("tags", tags), ("source", source)) if v}
            vector_hits = store.query(vec, wide, where or None)
        except (ProviderError, VectorError) as e:
            note = f"Vector search is unavailable ({e}), so only keyword search is used."
    keyword_hits = indexer.keyword.search(query, collections=scope or None, tags=tags or None, source=source or None, k=wide)
    fused = _fuse(vector_hits, keyword_hits)
    cache: dict[str, dict[str, dict]] = {}
    passages = []
    for m in fused:
        by_id = cache.get(m["ref"])
        if by_id is None:
            by_id = cache[m["ref"]] = {p["id"]: p for p in indexer.passages_of(m["ref"])}
        p = by_id.get(m["id"])
        if not p:   # the index is a little behind the files (the source changed or went away): leave the stale hit out
            continue
        if scope and not set(scope) & set(p["collections"]):
            continue
        passages.append({"id": p["id"], "ref": p["ref"], "n": p["n"], "source": p["source"], "name": p["title"], "locator": p["locator"],
                         "text": p["text"], "tags": p["tags"], "collections": p["collections"], "score": m["score"],
                         "vector_score": m["vector_score"], "keyword_rank": m["keyword_rank"]})
        if len(passages) >= k:
            break
    return {"passages": passages, "mode": "hybrid" if vector_hits else "keyword", "note": note}


def get_prompt(indexer: Indexer, pid: str) -> dict | None:
    """One saved prompt in full: {id, store, title, tags, purpose, text}, or None."""
    from .. import promptstore

    for store, folder in (("studio", indexer.studio_dir), ("library", indexer.library_dir)):
        if store == "studio" and not pid.startswith("ps-"):
            continue
        o = promptstore.get(pid, folder)
        if o:
            m = o.get("meta", {})
            return {"id": o["id"], "store": store, "title": o["title"], "tags": list(m.get("tags", [])), "purpose": m.get("purpose", ""), "text": o["text"]}
    return None


def list_by_tag(indexer: Indexer, tag: str, limit: int = 50) -> list[dict]:
    """Saved prompts that carry a tag, newest first: [{id, store, title, tags}]."""
    from .. import promptstore

    out = []
    for store, folder in (("library", indexer.library_dir), ("studio", indexer.studio_dir)):
        for o in promptstore.load_all(folder):
            if tag in o.get("meta", {}).get("tags", []):
                out.append({"id": o["id"], "store": store, "title": o["title"], "tags": list(o["meta"]["tags"]), "updated": o["updated"]})
    out.sort(key=lambda r: -r["updated"])
    return [{k: v for k, v in r.items() if k != "updated"} for r in out[:limit]]
