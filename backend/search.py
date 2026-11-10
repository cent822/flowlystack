"""Text search for the Prompt Library behind one small interface.

Two engines:
    SubstringEngine  the original case-insensitive "contains" match (no service needed, always available)
    MeiliEngine      Meilisearch: typo tolerance and relevance ranking; the index is a rebuildable cache,
                     the prompt files stay the source of truth

`engine` is Meilisearch when a URL is configured and the substring engine otherwise. The Meilisearch engine
falls back to the substring match whenever the service is down or its index is not in sync yet, so search
never breaks. Only the text match (q) goes through here; tag, project, star and edited filters stay in
promptstore.search.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

from . import promptstore
from .config import CONFIG

INDEX = "prompts"          # the Prompt Library's index
STUDIO_INDEX = "studio"    # Prompt Studio's index: same service, its own documents and settings
LINKSHELL_INDEX = "linkshell"   # Linkshell: one document per project (name, tags, block titles and texts)
MAX_HITS = 20_000
RETRY_AFTER = 10   # seconds to leave a failed service alone before trying it again
DRIFT_EVERY = 30   # seconds between cheap checks that the index still holds what this process believes it sent (it can be emptied from outside)


# Attribute order is the ranking weight: a match in the title beats tags, then note, then body text. Equally good
# matches fall back to the most recently updated prompt. Typo tolerance stays at the Meilisearch defaults.
SETTINGS = {"searchableAttributes": ["title", "tags", "note", "text"],
            "filterableAttributes": ["type", "project", "tags"],
            "sortableAttributes": ["updated"],
            "rankingRules": ["words", "typo", "proximity", "attributeRank", "sort", "wordPosition", "exactness", "updated:desc"],
            "pagination": {"maxTotalHits": MAX_HITS}}
STUDIO_SETTINGS = {**SETTINGS, "searchableAttributes": ["title", "tags", "purpose", "note", "text"],
                   "filterableAttributes": ["type", "tags", "status"]}

LINKSHELL_SETTINGS = {**SETTINGS, "searchableAttributes": ["title", "tags", "text"], "filterableAttributes": ["type", "tags"]}

MARK_ON, MARK_OFF = "\ue000", "\ue001"   # private-use markers around matches; the frontend escapes the text, then turns them into <mark>
SNIPPET = 70   # characters of context on each side of a match in the substring fallback


def _snippet(text: str, q: str) -> str | None:
    """Whitespace-collapsed context around the first match of q, marked; None when q is not in text."""
    text = " ".join(text.split())
    i = text.lower().find(q)
    if i < 0:
        return None
    a = max(0, i - SNIPPET)
    return ("…" if a else "") + _mark(text[a:i + len(q) + SNIPPET], q) + ("…" if i + len(q) + SNIPPET < len(text) else "")


def _mark(text: str, q: str) -> str | None:
    """Substring-engine highlight: `text` with the first match of q wrapped, or None when q is not in it."""
    i = text.lower().find(q)
    if i < 0:
        return None
    return text[:i] + MARK_ON + text[i:i + len(q)] + MARK_OFF + text[i + len(q):]


class SubstringEngine:
    name = "substring"

    def match(self, items: list[dict], q: str) -> tuple[list[dict], dict[str, dict]]:
        """Items that match q, best first, plus per-id highlights ({"title", "snippet"} with marker characters)."""
        q = q.strip().lower()
        if not q:
            return items, {}
        found, hl = promptstore.search(items, q), {}
        for o in found:
            h = {}
            if (t := _mark(o["title"], q)):
                h["title"] = t
            if (snip := _snippet(o["text"], q)):
                h["snippet"] = snip
            if (note := _snippet(o["meta"]["note"], q)):
                h["note"] = note
            if (pur := _snippet(o["meta"].get("purpose", ""), q)):   # Studio only; Library prompts have no purpose
                h["purpose"] = pur
            tags = [_mark(t, q) for t in o["meta"]["tags"]]
            if any(tags):
                h["tags"] = [m or t for m, t in zip(tags, o["meta"]["tags"])]   # parallel to meta.tags
            if h:
                hl[o["id"]] = h
        return found, hl

    def reconcile(self, items: list[dict], wait: bool = False) -> dict | None:
        return None

    def rebuild(self, items: list[dict]) -> dict | None:
        return None

    def status(self) -> dict:
        return {"engine": self.name, "ready": True}


class MeiliEngine(SubstringEngine):
    name = "meilisearch"

    def __init__(self, url: str, key: str | None = None, index: str = INDEX, settings: dict = SETTINGS, doc=None,
                 highlight: tuple = ("title", "text", "note", "tags")):
        self.url, self.key = url.rstrip("/"), key
        self.index, self.settings, self.highlight = index, settings, list(highlight)
        if doc:
            self._doc = doc   # the document builder for this index (the Library's is the default below)
        self._lock = threading.RLock()
        self._seen: dict[str, float] = {}   # id -> `updated` of what the index holds
        self._synced = False
        self._down_until = 0.0
        self._error = ""
        self._checked = 0.0   # when the index's size was last compared with `_seen`

    # ---- HTTP ----

    def _req(self, method: str, path: str, body=None, timeout: float = 3):
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, method=method, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def _fail(self, e: Exception) -> None:
        self._synced, self._down_until, self._error = False, time.time() + RETRY_AFTER, str(e)[:160]

    def _wait(self, task: dict, timeout: float = 120) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if self._req("GET", f"/tasks/{task['taskUid']}")["status"] in ("succeeded", "failed", "canceled"):
                return
            time.sleep(0.2)

    # ---- index ----

    @staticmethod
    def _doc(o: dict) -> dict:
        m = o["meta"]
        return {"id": o["id"], "type": "prompt", "title": o["title"], "text": o["text"], "note": m["note"],
                "tags": m["tags"], "project": o.get("project", ""), "updated": o["updated"]}

    def _ensure_index(self) -> None:
        try:
            self._req("GET", f"/indexes/{self.index}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            self._wait(self._req("POST", "/indexes", {"uid": self.index, "primaryKey": "id"}))
        have = self._req("GET", f"/indexes/{self.index}/settings")
        if any(have.get(k) != v for k, v in self.settings.items()):
            self._wait(self._req("PATCH", f"/indexes/{self.index}/settings", self.settings))

    def reconcile(self, items: list[dict], wait: bool = False) -> dict | None:
        """Bring the index in line with the prompt files. Cheap when nothing changed (compares against what
        was last sent, no request). The first pass after startup or an outage reads the index's own ids."""
        if time.time() < self._down_until:
            return None
        with self._lock:
            try:
                if self._synced and time.time() - self._checked >= DRIFT_EVERY:
                    # Self-heal: another process, a restarted or recreated Meilisearch, or a test server can change the index behind our back. `_seen` would
                    # then claim documents the index no longer has and search would stay empty until the app restarted. One small request settles it.
                    self._checked = time.time()
                    try:
                        s = self._req("GET", f"/indexes/{self.index}/stats")
                        if not s.get("isIndexing") and s.get("numberOfDocuments") != len(self._seen):
                            self._synced = False   # read the index's own ids again below and repair the difference
                    except urllib.error.HTTPError as e:
                        if e.code != 404:
                            raise
                        self._synced = False   # the index itself is gone: it is created and refilled below
                if not self._synced:
                    self._ensure_index()
                    self._seen = {d["id"]: d["updated"] for d in self._fetch_state()}
                have = {o["id"]: o for o in items}
                stale = [o for pid, o in have.items() if self._seen.get(pid) != o["updated"]]
                gone = [pid for pid in self._seen if pid not in have]
                last = None
                for i in range(0, len(stale), 1000):
                    last = self._req("POST", f"/indexes/{self.index}/documents", [self._doc(o) for o in stale[i:i + 1000]], 30)
                if gone:
                    last = self._req("POST", f"/indexes/{self.index}/documents/delete-batch", gone, 30)
                if wait and last:
                    self._wait(last)
                for o in stale:
                    self._seen[o["id"]] = o["updated"]
                for pid in gone:
                    del self._seen[pid]
                self._synced, self._error = True, ""
                return {"indexed": len(stale), "removed": len(gone)}
            except (OSError, ValueError) as e:   # URLError, HTTPError, timeouts, bad JSON
                self._fail(e)
                return None

    def _fetch_state(self) -> list[dict]:
        out, offset = [], 0
        while True:
            r = self._req("GET", f"/indexes/{self.index}/documents?fields=id,updated&limit=1000&offset={offset}", timeout=30)
            out += r["results"]
            offset += 1000
            if offset >= r["total"]:
                return out

    def rebuild(self, items: list[dict]) -> dict | None:
        """Drop every document and re-add them from the files, in one batch."""
        with self._lock:
            try:
                self._ensure_index()
                self._wait(self._req("DELETE", f"/indexes/{self.index}/documents", timeout=30))
                self._seen, self._synced = {}, True
            except (OSError, ValueError) as e:
                self._fail(e)
                return None
        return self.reconcile(items, wait=True)

    # ---- query ----

    def _search(self, q: str, strategy: str) -> dict:
        return self._req("POST", f"/indexes/{self.index}/search", {
            "q": q, "limit": MAX_HITS, "matchingStrategy": strategy, "attributesToRetrieve": ["id"],
            "attributesToHighlight": self.highlight, "attributesToCrop": ["text", "note"], "cropLength": 30,
            "highlightPreTag": MARK_ON, "highlightPostTag": MARK_OFF})

    def match(self, items: list[dict], q: str) -> tuple[list[dict], dict[str, dict]]:
        if not q.strip():
            return items, {}
        if not self._synced or time.time() < self._down_until:
            return super().match(items, q)
        try:
            r = self._search(q, "all")   # every word must match: "slide title" no longer returns every prompt with "slide"
            if not r["hits"]:
                r = self._search(q, "last")   # nothing has all the words: drop words from the end, best matches still first
        except (OSError, ValueError) as e:
            self._fail(e)
            return super().match(items, q)
        by_id = {o["id"]: o for o in items}
        found, hl = [], {}
        for h in r["hits"]:
            o = by_id.get(h["id"])
            if not o:
                continue
            found.append(o)
            f, mine = h.get("_formatted", {}), {}
            if MARK_ON in f.get("title", ""):
                mine["title"] = f["title"]
            if MARK_ON in f.get("text", ""):
                mine["snippet"] = " ".join(f["text"].split())
            if MARK_ON in f.get("note", ""):
                mine["note"] = " ".join(f["note"].split())
            if MARK_ON in f.get("purpose", ""):
                mine["purpose"] = f["purpose"]   # Studio only
            if any(MARK_ON in t for t in f.get("tags", [])):
                mine["tags"] = f["tags"]   # parallel to meta.tags
            if mine:
                hl[o["id"]] = mine
        return found, hl

    def status(self) -> dict:
        usable = self._synced and time.time() >= self._down_until
        return {"engine": self.name if usable else "substring", "configured": self.name, "ready": usable,
                "url": self.url, "indexed": len(self._seen), "error": self._error}


def _studio_doc(o: dict) -> dict:
    m = o["meta"]
    return {"id": o["id"], "type": "studio", "title": o["title"], "text": o["text"], "note": m["note"], "purpose": m["purpose"],
            "tags": m["tags"], "status": m["status"], "updated": o["updated"]}


def _linkshell_doc(o: dict) -> dict:
    return {"id": o["id"], "type": "linkshell", "title": o["title"], "text": o["text"], "tags": o["meta"]["tags"], "updated": o["updated"]}


def _make(index: str = INDEX, settings: dict = SETTINGS, doc=None, highlight: tuple = ("title", "text", "note", "tags")):
    url = CONFIG["search"].get("url")
    return MeiliEngine(url, CONFIG["search"].get("key"), index, settings, doc, highlight) if url else SubstringEngine()


engine = _make()                    # Prompt Library
studio_engine = _make(STUDIO_INDEX, STUDIO_SETTINGS, _studio_doc, ("title", "text", "note", "purpose", "tags"))   # Prompt Studio
linkshell_engine = _make(LINKSHELL_INDEX, LINKSHELL_SETTINGS, _linkshell_doc, ("title", "text", "tags"))   # Linkshell projects
