"""Keyword search over passages: the Meilisearch `collections` index, with a plain scan as the fallback. Standard library only.

Meilisearch is optional (`search.url` in flowlystack.config.json). Unlike the prompt indexes, which are aligned from a full list every
few seconds, a passage index can be large, so the indexer writes to it incrementally (`put`, `drop_ref`) and remembers what it sent. When
the service is not configured or is down, `search` scans the passages the indexer streams from the files: slower, never broken.
Meilisearch ids may only hold letters, digits, `-` and `_`, so a passage `kd-x#3` is stored as id `kd-x_3` and keeps its real id in `pid`.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
from typing import Callable, Iterable

from ..search import MeiliEngine, RETRY_AFTER

INDEX = "collections"
SETTINGS = {"searchableAttributes": ["title", "tags", "text"],
            "filterableAttributes": ["collections", "tags", "source", "ref"],
            "rankingRules": ["words", "typo", "proximity", "attributeRank", "sort", "wordPosition", "exactness"],
            "pagination": {"maxTotalHits": 5000}}
_BAD = re.compile(r"[^A-Za-z0-9_-]")


def safe_id(pid: str) -> str:
    return _BAD.sub("_", pid)


# Small words that carry no meaning in a question ("how do I deploy with Docker compose"). They are taken out of the question before the keyword search, so
# the search looks for "deploy docker compose" and does not rank passages that merely contain "how do I". English only; other languages pass through.
# Measured on the real index (150 questions made from random passages, top 5): found 0.50 with `frequency` alone, 0.81 with the small words removed;
# literal-excerpt searches did not get worse. The meaning search keeps the full question.
STOP_WORDS = frozenset("""a an the is are was were be been being am do does did done doing how what why when where which who whom whose can could should would will shall
may might must i you he she it we they me my your our their his her its this that these those of in on at to for from with by about as into than then so if or and but
not no yes there here have has had having get got let please tell give show find know want need make like just also really very much more most some any each other such
own same too only both few now again once up down out over under off above below between through during before after
don't doesn't didn't can't won't isn't aren't wasn't weren't couldn't shouldn't wouldn't i'm i've i'll i'd it's that's what's there's let's we're you're they're""".split())
_TOKEN = re.compile(r"[\w'\u2019-]+")


def focus(q: str) -> str:
    """The question without its small words. Left alone when it has a quoted phrase, or when nothing but small words would be left."""
    if '"' in q:
        return q
    words = _TOKEN.findall(q)
    kept = [w for w in words if w.lower().replace("\u2019", "'").strip("'-") not in STOP_WORDS]
    return " ".join(kept) if kept else q


def _q(v: str) -> str:
    return json.dumps(str(v))   # a JSON string is also a valid Meilisearch filter string (quotes and backslashes escaped)


def _filter(collections=None, tags=None, source=None) -> str:
    parts = []
    if collections:
        parts.append(f"collections IN [{', '.join(_q(c) for c in collections)}]")
    for t in tags or []:
        parts.append(f"tags = {_q(t)}")
    if source:
        parts.append(f"source = {_q(source)}")
    return " AND ".join(parts)


def _doc(p: dict) -> dict:
    title = " · ".join(x for x in (p.get("title", ""), p.get("locator", "")) if x)
    return {"id": safe_id(p["id"]), "pid": p["id"], "ref": p["ref"], "n": p["n"], "title": title, "text": p["text"],
            "tags": p.get("tags", []), "collections": p.get("collections", []), "source": p.get("source", "")}


def _words(q: str) -> list[str]:
    return [w for w in re.findall(r"\w+", q.lower()) if w]


class KeywordIndex:
    """`url` None = no Meilisearch: everything below that talks to it is skipped and `search` scans. `scan` is a callable that streams every
    current passage as {id, ref, n, title, locator, text, tags, collections, source}."""

    def __init__(self, url: str | None, key: str | None, scan: Callable[[], Iterable[dict]]):
        self.scan = scan
        self.meili = MeiliEngine(url, key, INDEX, SETTINGS) if url else None
        self._ready = False

    # ---- state ----
    @property
    def configured(self) -> bool:
        return self.meili is not None

    @property
    def usable(self) -> bool:
        return bool(self.meili) and time.time() >= self.meili._down_until

    def status(self) -> dict:
        live = self.usable and self._ready
        return {"engine": "meilisearch" if live else "scan", "configured": "meilisearch" if self.meili else "scan",
                "ready": live, "error": self.meili._error if self.meili else ""}

    def _ensure(self) -> None:
        if not self._ready:
            self.meili._ensure_index()
            self._ready = True

    def _call(self, fn):
        """Run a Meilisearch call; a failure puts the service on hold (searches scan meanwhile) and returns False."""
        try:
            fn()
            return True
        except (OSError, ValueError) as e:   # URLError, HTTPError, timeouts, bad JSON
            self._ready = False
            self.meili._fail(e)
            return False

    # ---- writing (called by the indexer) ----
    def put(self, ref: str, passages: list[dict], wait: bool = False) -> bool:
        """Replace everything the index holds for one document or prompt. False = not done (service off or down): try again later."""
        if not self.usable:
            return False

        def go():
            self._ensure()
            m = self.meili
            t = m._req("POST", f"/indexes/{INDEX}/documents/delete", {"filter": f"ref = {_q(ref)}"}, 30)
            for i in range(0, len(passages), 500):
                t = m._req("POST", f"/indexes/{INDEX}/documents", [_doc(p) for p in passages[i:i + 500]], 30)
            if wait:
                m._wait(t)
        return self._call(go)

    def drop_ref(self, ref: str, wait: bool = False) -> bool:
        return self.put(ref, [], wait)

    def clear(self) -> bool:
        if not self.usable:
            return False

        def go():
            self._ensure()
            self.meili._wait(self.meili._req("DELETE", f"/indexes/{INDEX}/documents", timeout=30))
        return self._call(go)

    def count(self) -> int | None:
        if not self.usable or not self._ready:
            return None
        try:
            return self.meili._req("GET", f"/indexes/{INDEX}/stats")["numberOfDocuments"]
        except (OSError, ValueError, KeyError):
            return None

    # ---- searching ----
    def search(self, q: str, collections=None, tags=None, source=None, k: int = 20) -> list[dict]:
        """Passages that match, best first: [{id, ref, n, rank}] with rank 1 = best. Same answer shape from both engines."""
        if not q.strip():
            return []
        q = focus(q)
        if self.usable and self._ready:
            hits = self._meili_search(q, collections, tags, source, k)
            if hits is not None:
                return hits
        return self._scan_search(q, collections, tags, source, k)

    def _meili_search(self, q, collections, tags, source, k):
        out: list[dict] = []

        def go():
            # "frequency": passages that have every word still come first, and otherwise the most common words (how, do, with ...) are dropped first,
            # so a question keeps its key words. ("last" dropped the words from the END, which threw away "Docker compose" and kept "how do I".)
            body = {"q": q, "limit": k, "matchingStrategy": "frequency", "attributesToRetrieve": ["pid", "ref", "n"]}
            if (f := _filter(collections, tags, source)):
                body["filter"] = f
            r = self.meili._req("POST", f"/indexes/{INDEX}/search", body)
            out.extend({"id": h["pid"], "ref": h["ref"], "n": h["n"], "rank": i} for i, h in enumerate(r["hits"], 1))
        return out if self._call(go) else None

    def _scan_search(self, q, collections, tags, source, k):
        words = _words(q)
        scored = []
        for p in self.scan():
            if collections and not set(collections) & set(p.get("collections", [])):
                continue
            if tags and not set(tags) <= set(p.get("tags", [])):
                continue
            if source and p.get("source") != source:
                continue
            title, text = " ".join((p.get("title", ""), p.get("locator", ""))).lower(), p["text"].lower()
            hit = [w for w in words if w in text or w in title]
            if not hit:
                continue
            score = (len(hit) / len(words), sum(w in title for w in hit), sum(text.count(w) for w in hit))
            scored.append((score, p))
        # every word first, then fewer words; inside a group title matches and repeated words win
        scored.sort(key=lambda sp: sp[0], reverse=True)
        return [{"id": p["id"], "ref": p["ref"], "n": p["n"], "rank": i} for i, (_, p) in enumerate(scored[:k], 1)]
