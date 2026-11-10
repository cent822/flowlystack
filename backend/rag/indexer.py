"""The Collections indexer: keeps the keyword index and the vector store in step with
the documents of the collections and with the Library and Studio prompts ("My prompts"). Standard library plus the vector adapter.

*What is indexed.* Every document that is in a live collection and was read without failure, and every saved Library and Studio prompt
(the Trash is never indexed: a trashed prompt is simply no longer there). Each of these is a **ref** with a signature built from its
content and its collection membership. The portable copy's `refs` table remembers the signature each side has indexed (`kw_sig` for
the keyword index, `vec_sig` plus the model for the vectors); a ref whose signature differs is stale and gets indexed again. That makes
everything incremental, crash-safe (a ref is recorded only after it is fully written, so a restart just redoes the unfinished ones) and
cheap when only membership changed (vectors are looked up by text hash, nothing is embedded twice).

*Prompts follow the auto-index switch.* Documents and the Library and Studio prompts are embedded alike (model chosen, Ollama answering,
auto-index on). The user can stop the prompts with "Turn off auto-indexing" (the `prompts` switch, on by default); then they are searched by
keyword only until "Turn on auto-indexing" is pressed. The keyword side always covers them.

*The two sides are independent.* The keyword side needs no model and runs whenever Meilisearch is configured. The vector side needs the
embedding model chosen in Settings, an Ollama that answers, and the auto-index switch (or an explicit `run_once(force=True)`). Without a
model a document stays `waiting`. A changed model never rewrites the index silently: the status says `needs_rebuild` and nothing
happens until `rebuild()` is called after the user confirmed.

Run `run_once()` from a background thread. `cancel()` stops after the current batch and stays stopped until `resume()`.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from .. import collections as co
from .. import promptstore
from ..assistant.base import ProviderError
from . import chunking, embedding
from .keyword import KeywordIndex
from .vectors import ModelChanged, VectorCopy, VectorError, VectorStore, text_hash

PROMPTS_COLLECTION = "prompts"   # the built-in collection that covers the Library and Studio
BATCH = 16                       # passages per embedding request
RETRY_SECONDS = 30               # after a failed pass (Ollama down), wait this long before the next automatic try
FINISH_EVERY = 100               # refs between engine `finish()` calls (compaction), plus one at the end of a pass


class _Cancelled(Exception):
    pass


def prompt_passages(o: dict, source: str) -> list[dict]:
    """One passage per prompt (title, tags, purpose and text together); a very long prompt is cut like any long text."""
    m = o.get("meta", {})
    head = [o["title"]]
    if m.get("tags"):
        head.append("Tags: " + ", ".join(m["tags"]))
    if m.get("purpose"):
        head.append("Purpose: " + m["purpose"])
    body = (o.get("text") or "").strip()
    if not body:
        return []
    return [{"id": f"{o['id']}#{n}", "ref": o["id"], "n": n, "text": t, "locator": "", "title": o["title"], "tags": list(m.get("tags", [])),
             "collections": [PROMPTS_COLLECTION], "source": source}
            for n, t in enumerate(chunking.split_text("\n".join(head) + "\n\n" + body))]


class Indexer:
    def __init__(self, *, data_dir: Path, collections_root: Path | None, library_dir: Path | None, studio_dir: Path | None,
                 provider: Callable[[], object | None], model: Callable[[], str], auto: Callable[[], bool], keyword: KeywordIndex,
                 batch: int = BATCH, prompts: Callable[[], bool] = lambda: True):
        self.data_dir, self.root = Path(data_dir), collections_root
        self.library_dir, self.studio_dir = library_dir, studio_dir
        self.provider, self.model, self.auto, self.keyword, self.batch = provider, model, auto, keyword, batch
        self.prompts = prompts                       # are the Library and Studio prompts embedded? (the user's choice, see service.py)
        self.copy = VectorCopy(self.data_dir / "embeddings.db")
        self._store: VectorStore | None = None
        self._run = threading.Lock()                 # one pass at a time
        self._lock = threading.RLock()               # guards the fields below
        self._cancel = threading.Event()
        self._cancelled = False
        self._needs_rebuild = False
        self._error, self._retry_at = "", 0.0
        self._progress = self._fresh(False)
        self.force = False                           # set by "Index now": the next pass embeds even when the auto-index switch is off
        self._failures: dict[str, str] = {}          # ref -> reason, for documents that failed while indexing
        self._store_lock = threading.RLock()         # opening the engine, from the indexer thread or a search
        self._prompt_cache: dict[str, tuple] = {}    # prompt id -> (what it was built from, its passages): cutting every prompt on every look would be slow

    @staticmethod
    def _fresh(running: bool) -> dict:
        """`docs` maps each document being embedded in this pass to [passages done, passages total] (the rows draw their own bar from it)."""
        return {"running": running, "current": "", "refs_total": 0, "refs_done": 0, "passages_total": 0, "passages_done": 0,
                "docs": {}, "docs_total": 0, "docs_done": 0, "prompts_total": 0, "prompts_done": 0}

    def _vec_want(self, want: dict) -> dict:
        """The refs that get vectors: every document, and the prompts only when the user switched that on."""
        return want if self.prompts() else {r: i for r, i in want.items() if i["kind"] == "document"}

    # ------------------------------------------------------------ what should be indexed
    def desired(self) -> dict[str, dict]:
        """ref -> {ref, kind, name, sig, collections, load}, where load() returns the passages. Cheap to build: no passage text is read for
        documents (their signature comes from the file hash and the passages stamp)."""
        out: dict[str, dict] = {}
        for d in co.all_documents(self.root):
            if d["status"] == "failed":
                continue
            cols = sorted(d["collections"])
            out[d["id"]] = {"ref": d["id"], "kind": "document", "name": d["name"], "collections": cols, "count": d["passages"] or 0,
                            "sig": f"{d['sha256']}|{co.passages_stamp(d['id'], self.root)}|{','.join(cols)}" + (f"|{d['name']}" if d.get("renamed") else ""),
                            "load": lambda d=d, cols=cols: [
                                {"id": f"{d['id']}#{p['n']}", "ref": d["id"], "n": p["n"], "text": p["text"], "locator": p.get("locator", ""),
                                 "title": d["name"], "tags": [], "collections": cols, "source": "document"}
                                for p in co.passages(d["id"], self.root)]}
        for source, folder in (("library", self.library_dir), ("studio", self.studio_dir)):
            for o in promptstore.load_all(folder):
                m = o.get("meta", {})
                key = (source, o["updated"], o["title"], tuple(m.get("tags", [])), m.get("purpose", ""))
                hit = self._prompt_cache.get(o["id"])
                if not hit or hit[0] != key:
                    hit = self._prompt_cache[o["id"]] = (key, prompt_passages(o, source))
                ps = hit[1]
                if ps:
                    sig = hashlib.sha1("\x00".join(p["text"] for p in ps).encode()).hexdigest()
                    out[o["id"]] = {"ref": o["id"], "kind": source, "name": o["title"], "collections": [PROMPTS_COLLECTION], "count": len(ps), "sig": sig,
                                    "load": lambda ps=ps: ps}
        return out

    def passages_of(self, ref: str) -> list[dict]:
        """The current passages of one document or prompt (what search results show), or [] when it is gone."""
        if ref.startswith("kd-"):
            d = co.get_document(ref, self.root)
            if not d or not d["collections"]:
                return []
            return [{"id": f"{ref}#{p['n']}", "ref": ref, "n": p["n"], "text": p["text"], "locator": p.get("locator", ""), "title": d["name"],
                     "tags": [], "collections": sorted(d["collections"]), "source": "document"} for p in co.passages(ref, self.root)]
        source, folder = ("studio", self.studio_dir) if ref.startswith("ps-") else ("library", self.library_dir)
        o = promptstore.get(ref, folder)
        return prompt_passages(o, source) if o else []

    def iter_passages(self):
        """Every current passage, streamed (the keyword index's fallback scans this)."""
        for info in self.desired().values():
            yield from info["load"]()

    # ------------------------------------------------------------ vector store
    def _built_for(self) -> dict | None:
        """What the engine's folder says it was built with ({model, dim, ...}), or None when there is no index yet."""
        try:
            return json.loads((self.data_dir / "vectors" / "meta.json").read_text())
        except (OSError, ValueError):
            return None

    def _mismatch(self, model: str) -> str:
        """A readable reason when the index on disk was built with another model than the one chosen now, else ''."""
        built = self._built_for()
        if model and built and built.get("model") != model:
            return f"The index was built with {built.get('model')}; rebuild it for {model}"
        return ""

    def search_store(self) -> VectorStore | None:
        """The vector store for searching, or None while there is nothing to search (no model, nothing indexed yet, or the index
        was built with another model). Never talks to Ollama."""
        model = self.model()
        if not model or self._mismatch(model):
            return None
        with self._store_lock:
            if self._store and self._store.model == model:
                return self._store
            if not self._built_for():
                return None
            return self._open_store()

    def _open_store(self) -> VectorStore | None:
        with self._store_lock:
            return self._open_store_locked()

    def _open_store_locked(self) -> VectorStore | None:
        model = self.model()
        if not model:
            return None
        if (why := self._mismatch(model)):   # decided from the folder alone: no request to Ollama while the answer is "rebuild first"
            with self._lock:
                self._error = why
            return None
        if self._store and self._store.model == model:
            return self._store
        if self._store:
            self._store.engine.close()
            self._store = None
        from .lance import LanceEngine   # heavy import, only when vectors are really needed

        dim = (self._built_for() or {}).get("dim") or self.copy.dim(model)
        if dim is None:   # first time with this model: one tiny request tells us the vector size
            prov = self.provider()
            if prov is None:
                raise ProviderError("Ollama is not configured")
            dim = len(prov.embed(model, ["dimension probe"])[0])
        engine = LanceEngine()
        try:
            engine.open(self.data_dir / "vectors", model, dim)
        except ModelChanged as e:
            with self._lock:
                self._needs_rebuild, self._error = True, str(e)   # same model name but another vector size or format
            return None
        self._store = VectorStore(engine, self.copy, model, dim)
        with self._lock:
            self._needs_rebuild = False
        return self._store

    # ------------------------------------------------------------ passes
    def _stale(self, want: dict, rows: dict, model: str) -> tuple[list[str], list[str], list[str]]:
        kw = [r for r, i in want.items() if rows.get(r, {}).get("kw_sig") != i["sig"]]
        vec = [r for r, i in self._vec_want(want).items() if rows.get(r, {}).get("vec_sig") != i["sig"] or rows[r].get("model") != model] if model else []
        gone = [r for r in rows if r not in want]
        return kw, vec, gone

    def _sync_keyword(self, want, rows) -> int:
        if not self.keyword.configured:
            return 0
        kw, _, gone = self._stale(want, rows, "")
        done = 0
        for ref in gone:
            if rows[ref]["kw_sig"] and not self.keyword.drop_ref(ref):
                break
            self.copy.ref_set(ref, kw_sig="")
            if not rows[ref]["vec_sig"]:
                self.copy.ref_delete(ref)
        for ref in kw:
            if self._cancel.is_set():
                break
            if not self.keyword.put(ref, want[ref]["load"]()):
                break   # service down: leave the rest for the next pass
            self.copy.ref_set(ref, kw_sig=want[ref]["sig"])
            done += 1
        return done

    def _doc_status(self, info: dict, status: str, error: str = "") -> None:
        if info["kind"] == "document":
            co.set_status(info["ref"], status, error, self.root)

    def _doc_progress(self, ref: str, n: int) -> None:
        if ref in self._progress["docs"]:
            d = self._progress["docs"][ref]
            d[0] = min(d[1], d[0] + n)

    def _embed_ref(self, store: VectorStore, info: dict) -> int:
        model, prov = store.model, self.provider()
        if prov is None:
            raise ProviderError("Ollama is not configured")
        passages = info["load"]()
        hashes = [text_hash(p["text"]) for p in passages]
        have = self.copy.get(model, hashes)
        need = list(dict.fromkeys(h for h in hashes if h not in have))
        text_of = {h: p["text"] for h, p in zip(hashes, passages)}
        for i in range(0, len(need), self.batch):
            if self._cancel.is_set():
                raise _Cancelled()
            part = need[i:i + self.batch]
            vecs = prov.embed(model, [embedding.passage_text(model, text_of[h]) for h in part])
            self.copy.put(model, zip(part, vecs))   # kept right away, so an interrupted document resumes without re-embedding
            have.update(zip(part, vecs))
            with self._lock:
                self._progress["passages_done"] += len(part)
                self._doc_progress(info["ref"], len(part))
        with self._lock:
            self._progress["passages_done"] += len(passages) - len(need)   # the ones whose vector was already stored
            self._doc_progress(info["ref"], len(passages) - len(need))
        rows = [{"id": p["id"], "vector": have[h], "source": p["source"], "ref": p["ref"], "collections": p["collections"],
                 "tags": p["tags"], "text_hash": h} for p, h in zip(passages, hashes)]
        store.delete_ref(info["ref"])
        for i in range(0, len(rows), 500):
            store.upsert(rows[i:i + 500])
        return len(need)

    def _count_done(self, info: dict) -> None:
        self._progress["refs_done"] += 1
        self._progress["docs_done" if info["kind"] == "document" else "prompts_done"] += 1
        if info["ref"] in self._progress["docs"]:
            self._progress["docs"][info["ref"]][0] = self._progress["docs"][info["ref"]][1]

    def _sync_vectors(self, want, rows, vec, gone) -> int:
        store = self._open_store()
        if store is None:
            return 0
        done = 0
        for ref in gone:   # removed sources: their passages leave the vector engine
            if rows[ref]["vec_sig"]:
                store.delete_ref(ref)
            self.copy.ref_set(ref, vec_sig="", model="")
            if not rows[ref]["kw_sig"] or not self.keyword.configured:
                self.copy.ref_delete(ref)
        since_finish = 0
        for ref in vec:
            info = want[ref]
            with self._lock:
                self._progress["current"] = info["name"]
            self._doc_status(info, "indexing")
            try:
                self._embed_ref(store, info)
            except _Cancelled:
                self._doc_status(info, "waiting")
                raise
            except ProviderError:
                self._doc_status(info, "waiting")   # the file is fine; Ollama or the model is the problem
                raise
            except VectorError as e:
                self._doc_status(info, "failed", str(e))
                with self._lock:
                    self._failures[ref] = str(e)
                self._count_done(info)
                continue
            self.copy.ref_set(ref, vec_sig=info["sig"], model=store.model)
            self._doc_status(info, "ready")
            done += 1
            since_finish += 1
            with self._lock:
                self._count_done(info)
                self._failures.pop(ref, None)
            if since_finish >= FINISH_EVERY:
                store.finish()
                since_finish = 0
        if done or gone:
            store.finish()
        return done

    def due(self) -> bool:
        """Is an automatic pass worth starting now? (the background loop asks before it runs `run_once`)"""
        want, rows, model = self.desired(), self.copy.refs(), self.model()
        with self._lock:
            if self._cancelled or self._needs_rebuild or self._mismatch(model) or time.time() < self._retry_at:
                return False
        kw, vec, gone = self._stale(want, rows, model)
        return bool((self.keyword.configured and (kw or gone)) or (model and self.auto() and (vec or gone)))

    def run_once(self, force: bool = False) -> dict:
        """One pass. `force` runs the vector side even when the auto-index switch is off (the user pressed Index now / Resume)."""
        if not self._run.acquire(blocking=False):
            return {"skipped": "already running"}
        try:
            with self._lock:
                if force:
                    self._cancelled = False
                if self._cancelled:
                    return {"skipped": "cancelled"}
                self._cancel.clear()
                self._error = "" if not self._needs_rebuild else self._error
                self._progress = self._fresh(True)
            want, rows, model = self.desired(), self.copy.refs(), self.model()
            for d in co.all_documents(self.root):   # a document's status follows what is really indexed
                r = rows.get(d["id"], {})
                indexed = bool(model) and d["id"] in want and r.get("vec_sig") == want[d["id"]]["sig"] and r.get("model") == model
                if d["status"] == "ready" and not indexed:
                    co.set_status(d["id"], "waiting", root=self.root)   # it changed (or the model did) since it was indexed
                elif d["status"] == "waiting" and indexed:
                    co.set_status(d["id"], "ready", root=self.root)     # indexed, but a crash or a cancel left it waiting
            kw_n = self._sync_keyword(want, rows)
            rows = self.copy.refs()
            kw, vec, gone = self._stale(want, rows, model)
            vec_n = 0
            if model and (force or self.auto()) and not self._needs_rebuild and not self._mismatch(model) and (vec or gone):
                with self._lock:
                    self._progress["refs_total"] = len(vec)
                    self._progress["passages_total"] = sum(want[r]["count"] for r in vec)
                    self._progress["docs"] = {r: [0, want[r]["count"]] for r in vec if want[r]["kind"] == "document"}
                    self._progress["docs_total"] = len(self._progress["docs"])
                    self._progress["prompts_total"] = len(vec) - len(self._progress["docs"])
                try:
                    vec_n = self._sync_vectors(want, rows, vec, gone)
                except _Cancelled:
                    with self._lock:
                        self._cancelled = True
                except ProviderError as e:
                    with self._lock:
                        self._error, self._retry_at = str(e), time.time() + RETRY_SECONDS
            return {"keyword": kw_n, "vectors": vec_n}
        finally:
            with self._lock:
                self._progress["running"], self._progress["current"] = False, ""
            self._run.release()

    # ------------------------------------------------------------ controls
    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._cancel.set()

    def resume(self) -> None:
        with self._lock:
            self._cancelled, self._retry_at = False, 0.0

    def recover(self) -> int:
        """After a crash: documents left `indexing` are waiting again (the next pass redoes them; finished ones are not repeated)."""
        n = 0
        for d in co.all_documents(self.root):
            if d["status"] == "indexing":
                co.set_status(d["id"], "waiting", root=self.root)
                n += 1
        return n

    def rebuild(self) -> None:
        """Forget every vector in the engine and index everything again with the current model (after the user confirmed a model change).
        Vectors of other models stay in the portable copy, so going back to an earlier model re-embeds nothing."""
        with self._run:
            if self._store:
                self._store.engine.close()
                self._store = None
            shutil.rmtree(self.data_dir / "vectors", ignore_errors=True)
            self.copy.refs_forget("vec")
            for d in co.all_documents(self.root):
                if d["status"] != "waiting":
                    co.set_status(d["id"], "waiting", root=self.root)
            with self._lock:
                self._needs_rebuild, self._error, self._cancelled, self._retry_at = False, "", False, 0.0

    def rebuild_keyword(self) -> bool:
        """Empty the keyword index and send everything again (after Meilisearch lost its data, or for `POST /api/search/rebuild`)."""
        with self._run:
            if self.keyword.configured and not self.keyword.clear():
                return False
            self.copy.refs_forget("kw")
            return True

    def reindex_document(self, did: str) -> dict | None:
        """Read the stored file again; the new passages are indexed on the next pass."""
        return co.read_document(did, self.root)

    # ------------------------------------------------------------ status
    def status(self) -> dict:
        want, rows, model = self.desired(), self.copy.refs(), self.model()
        kw, vec, gone = self._stale(want, rows, model)
        with self._lock:
            prog, err, retry = dict(self._progress), self._error, self._retry_at
            rebuild, cancelled = self._needs_rebuild or bool(self._mismatch(model)), self._cancelled
            if self._mismatch(model):
                err = self._mismatch(model)
            failures = dict(self._failures)
        if rebuild:
            state = "needs_rebuild"
        elif prog["running"]:
            state = "running"
        elif not model:
            state = "waiting_model"
        elif cancelled:
            state = "cancelled"
        elif err and time.time() < retry:
            state = "error"
        elif vec and not self.auto():
            state = "off"
        else:
            state = "idle"
        by_kind = {k: sum(1 for i in want.values() if i["kind"] == k) for k in ("document", "library", "studio")}
        passages = {k: sum(i["count"] for i in want.values() if i["kind"] == k) for k in by_kind}
        return {"state": state, "model": model, "auto": bool(self.auto()), "error": err, "needs_rebuild": rebuild,
                "refs": len(want), "by_kind": by_kind, "passages": passages, "vector_pending": len(vec) if model else len(self._vec_want(want)),
                "keyword_pending": len(kw) if self.keyword.configured else 0, "keyword": self.keyword.status(),
                "vectors": self._store.count() if self._store else 0, "progress": prog, "prompts": self._prompts_status(want, rows, model),
                "failures": [{"ref": r, "name": want[r]["name"] if r in want else r, "error": e} for r, e in failures.items()]}

    def _prompts_status(self, want: dict, rows: dict, model: str) -> dict:
        """The Library and Studio prompts: how many there are, whether they get vectors, and how many still need them."""
        mine = {r: i for r, i in want.items() if i["kind"] != "document"}
        todo = [r for r, i in mine.items() if rows.get(r, {}).get("vec_sig") != i["sig"] or rows.get(r, {}).get("model") != model]
        return {"enabled": bool(self.prompts()), "count": len(mine), "pending": len(todo) if model else len(mine)}

    def close(self) -> None:
        with self._run:
            if self._store:
                self._store.engine.close()
                self._store = None
            self.copy.close()
