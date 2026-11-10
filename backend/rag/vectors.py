"""The vector store behind Collections. Standard library only.

Two parts, both rebuildable caches of the documents and prompts:

* an **engine** (`lance.py` is the only one in v1) answers "which passages are closest to this vector". It is reached only
  through the small `Engine` interface below, so another engine can replace it by rebuilding from the copy.
* the **portable copy** (`VectorCopy`, a SQLite file) keeps every vector next to the hash of its text and the model that
  made it. Losing the engine's folder then costs a rebuild, never a re-embedding; deleting the copy costs embedding time,
  never data.

A passage's vector is identified by `sha256(text) + model`, so unchanged text is never embedded twice and two passages with
the same text share one stored vector.
"""
from __future__ import annotations

import hashlib
import sqlite3
import struct
import threading
from pathlib import Path
from typing import Iterable, Protocol

SCHEMA_VERSION = 1


class VectorError(Exception):
    """A readable problem with the vector store. `str(e)` can be shown to the user."""


class ModelChanged(VectorError):
    """The index was built with another embedding model or vector size: it has to be rebuilt (not silently mixed)."""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# A chunk row, as the engine stores it. `vector` is a list of floats; the rest is what search filters and results need.
#   {"id": "kd-…#3", "vector": [...], "source": "library|studio|document", "ref": "kd-…", "collections": [...],
#    "tags": [...], "text_hash": "…"}
# A filter (`where`) is {"collections": [any of], "tags": [all of], "source": "…"}; every part is optional.
# A hit is the stored row without its vector plus `score` (cosine similarity, higher is closer).


class Engine(Protocol):
    def open(self, path: Path, model: str, dim: int) -> None: ...   # raises ModelChanged when the folder was built otherwise
    def upsert(self, rows: list[dict]) -> None: ...                 # insert or replace by id
    def query(self, vector: list[float], k: int, where: dict | None = None) -> list[dict]: ...
    def delete(self, ids: list[str]) -> None: ...                   # a deleted id is never returned again
    def delete_ref(self, ref: str) -> None: ...                     # every passage of one document or prompt
    def set_collections(self, ref: str, collections: list[str]) -> None: ...   # moving a document rewrites only this column
    def count(self) -> int: ...
    def finish(self) -> None: ...                                   # keep it fast after bursts of small writes (compaction, index)
    def close(self) -> None: ...


# ------------------------------------------------------------------ portable copy
def _pack(v: list[float]) -> bytes:
    return struct.pack(f"<{len(v)}f", *v)


def _unpack(b: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(b) // 4}f", b))


class VectorCopy:
    """`embeddings.db`: {text_hash, model, dim, vector BLOB}. One connection behind a lock, like the rest of the app."""

    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("CREATE TABLE IF NOT EXISTS vecs (text_hash TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL,"
                             " vector BLOB NOT NULL, PRIMARY KEY (text_hash, model))")
            # what the indexer has already put into the keyword index (kw_sig) and the vector engine (vec_sig, with its model), per
            # document or prompt: a signature that no longer matches the source means that ref has to be indexed again
            self._db.execute("CREATE TABLE IF NOT EXISTS refs (ref TEXT PRIMARY KEY, kw_sig TEXT NOT NULL DEFAULT '',"
                             " vec_sig TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '')")

    def put(self, model: str, items: Iterable[tuple[str, list[float]]]) -> None:
        rows = [(h, model, len(v), _pack(v)) for h, v in items]
        with self._lock, self._db:
            self._db.executemany("INSERT OR REPLACE INTO vecs VALUES (?,?,?,?)", rows)

    def get(self, model: str, hashes: list[str]) -> dict[str, list[float]]:
        found: dict[str, list[float]] = {}
        with self._lock:
            for i in range(0, len(hashes), 500):   # stay under SQLite's variable limit
                part = hashes[i:i + 500]
                q = f"SELECT text_hash, vector FROM vecs WHERE model=? AND text_hash IN ({','.join('?' * len(part))})"
                found.update({h: _unpack(b) for h, b in self._db.execute(q, [model, *part])})
        return found

    def count(self, model: str | None = None) -> int:
        with self._lock:
            if model is None:
                return self._db.execute("SELECT COUNT(*) FROM vecs").fetchone()[0]
            return self._db.execute("SELECT COUNT(*) FROM vecs WHERE model=?", (model,)).fetchone()[0]

    def dim(self, model: str) -> int | None:
        """The vector size this model produced earlier, if any vector of it is stored."""
        with self._lock:
            row = self._db.execute("SELECT dim FROM vecs WHERE model=? LIMIT 1", (model,)).fetchone()
        return row[0] if row else None

    def refs(self) -> dict[str, dict]:
        with self._lock:
            return {r[0]: {"kw_sig": r[1], "vec_sig": r[2], "model": r[3]}
                    for r in self._db.execute("SELECT ref, kw_sig, vec_sig, model FROM refs")}

    def ref_set(self, ref: str, **cols) -> None:
        """Record what was indexed for a ref: any of kw_sig, vec_sig, model."""
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO refs (ref) VALUES (?)", (ref,))
            for k, v in cols.items():
                if k not in ("kw_sig", "vec_sig", "model"):
                    raise VectorError(f"unknown column {k}")
                self._db.execute(f"UPDATE refs SET {k}=? WHERE ref=?", (v, ref))

    def ref_delete(self, ref: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM refs WHERE ref=?", (ref,))

    def refs_forget(self, column: str) -> None:
        """Mark every ref as not indexed in 'kw' (keyword index) or 'vec' (vector engine) any more."""
        with self._lock, self._db:
            if column == "vec":
                self._db.execute("UPDATE refs SET vec_sig='', model=''")
            elif column == "kw":
                self._db.execute("UPDATE refs SET kw_sig=''")
            else:
                raise VectorError(f"unknown column {column}")

    def prune(self, keep_hashes: set[str], model: str) -> int:
        """Drop vectors of this model whose text is no longer used anywhere. Returns how many went."""
        with self._lock, self._db:
            have = [r[0] for r in self._db.execute("SELECT text_hash FROM vecs WHERE model=?", (model,))]
            gone = [(h, model) for h in have if h not in keep_hashes]
            self._db.executemany("DELETE FROM vecs WHERE text_hash=? AND model=?", gone)
        return len(gone)

    def close(self) -> None:
        with self._lock:
            self._db.close()


# ------------------------------------------------------------------ the store the rest of the app uses
class VectorStore:
    """Engine plus portable copy. Writes go to both; a read only needs the engine."""

    def __init__(self, engine: Engine, copy: VectorCopy, model: str, dim: int):
        self.engine, self.copy, self.model, self.dim = engine, copy, model, dim
        self._lock = threading.RLock()

    def upsert(self, chunks: list[dict]) -> None:
        """Each chunk is an engine row (see above) whose `text_hash` is set. Vectors are copied before the engine sees them."""
        for c in chunks:
            if len(c["vector"]) != self.dim:
                raise VectorError(f"{c['id']}: the vector has {len(c['vector'])} numbers, {self.model} gives {self.dim}")
        with self._lock:
            self.copy.put(self.model, {c["text_hash"]: c["vector"] for c in chunks}.items())
            self.engine.upsert(chunks)

    def query(self, vector: list[float], k: int = 6, where: dict | None = None) -> list[dict]:
        if len(vector) != self.dim:
            raise VectorError(f"The question vector has {len(vector)} numbers, the index expects {self.dim}")
        with self._lock:
            return self.engine.query(vector, k, where)

    def delete(self, ids: list[str]) -> None:
        with self._lock:
            self.engine.delete(ids)

    def delete_ref(self, ref: str) -> None:
        with self._lock:
            self.engine.delete_ref(ref)

    def set_collections(self, ref: str, collections: list[str]) -> None:
        with self._lock:
            self.engine.set_collections(ref, collections)

    def count(self) -> int:
        return self.engine.count()

    def finish(self) -> None:
        with self._lock:
            self.engine.finish()

    def rebuild(self, metas: Iterable[dict]) -> list[dict]:
        """Fill the engine from the portable copy. `metas` are chunk rows without a vector (id, source, ref, collections, tags,
        text_hash). Returns the metas whose vector is not in the copy: those still have to be embedded."""
        metas = list(metas)
        with self._lock:
            have = self.copy.get(self.model, [m["text_hash"] for m in metas])
            ready = [{**m, "vector": have[m["text_hash"]]} for m in metas if m["text_hash"] in have and len(have[m["text_hash"]]) == self.dim]
            for i in range(0, len(ready), 2000):
                self.engine.upsert(ready[i:i + 2000])
            self.engine.finish()
        done = {m["id"] for m in ready}
        return [m for m in metas if m["id"] not in done]

    def close(self) -> None:
        with self._lock:
            self.engine.close()
            self.copy.close()
