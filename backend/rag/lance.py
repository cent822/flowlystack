"""LanceDB adapter for `vectors.Engine` (the only engine in v1).

Only this file imports `lancedb` and `pyarrow`. What the spike taught:
* the default PQ index gave 0.66 recall at 100k vectors, so the index is `IVF_HNSW_SQ` with cosine distance;
* rows written one by one sit outside the index and slow queries down until compaction, so `finish()` runs `optimize`;
* a small table is faster and exact without any index, so one is only built from `INDEX_MIN_ROWS` rows;
* **every write makes a version and compaction rewrites the whole table, so old versions pile up on disk** (1.2 GB for 6 MB of vectors after three days of
  use; `optimize()` alone keeps 7 days of versions). Nothing here reads an old version (every call goes through the store's one lock), so `_vacuum`
  keeps only the latest version, on open and after every `finish()`.
"""
from __future__ import annotations

import datetime
import json
import os
import warnings
from pathlib import Path

from .vectors import SCHEMA_VERSION, ModelChanged, VectorError

TABLE = "chunks"
INDEX_MIN_ROWS = 2000
EF_SEARCH = 100          # HNSW search effort: higher = better recall, a little slower
_META = "meta.json"


def _q(value: str) -> str:
    """A string as a SQL literal (the where-clauses below are built from ids and tags, which can hold any character)."""
    return "'" + str(value).replace("'", "''") + "'"


def _arr(values: list[str]) -> str:
    return "make_array(" + ", ".join(_q(v) for v in values) + ")"


def _where(where: dict | None) -> str | None:
    parts = []
    w = where or {}
    if w.get("collections"):
        parts.append(f"array_has_any(collections, {_arr(w['collections'])})")
    if w.get("tags"):
        parts.append(f"array_has_all(tags, {_arr(w['tags'])})")
    if w.get("source"):
        parts.append(f"source = {_q(w['source'])}")
    return " AND ".join(parts) or None


def trim(path: Path) -> bool:
    """Delete every old version of an existing index (what `_vacuum` does) without opening it for a model: used once at server start, because the store
    itself opens lazily (on the first search or indexing pass) and an index from before `_vacuum` can be GBs of old versions. True when a table was trimmed."""
    path = Path(path)
    if not (path / f"{TABLE}.lance").is_dir():
        return False
    import lancedb

    table = lancedb.connect(str(path)).open_table(TABLE)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        table.optimize(cleanup_older_than=datetime.timedelta(0))
    return True


class LanceEngine:
    def __init__(self):
        self._db = None
        self._table = None
        self.dim = 0

    def open(self, path: Path, model: str, dim: int) -> None:
        os.environ.setdefault("LANCE_INCLUDE_VECTOR_CENTROIDS", "false")   # silences a notice about a coming default
        import lancedb
        import pyarrow as pa

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        meta_file = path / _META
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
            except ValueError:
                raise VectorError(f"{meta_file} cannot be read; delete the folder {path} and rebuild the index") from None
            if (meta.get("model"), meta.get("dim")) != (model, dim) or meta.get("schema_version") != SCHEMA_VERSION:
                raise ModelChanged(f"The index was built with {meta.get('model')} ({meta.get('dim')} numbers per passage); "
                                   f"rebuild it for {model} ({dim})")
        self._db = lancedb.connect(str(path))
        schema = pa.schema([("id", pa.string()), ("vector", pa.list_(pa.float32(), dim)), ("source", pa.string()),
                            ("ref", pa.string()), ("collections", pa.list_(pa.string())), ("tags", pa.list_(pa.string())),
                            ("text_hash", pa.string())])
        names = self._db.list_tables() if hasattr(self._db, "list_tables") else self._db.table_names()
        names = getattr(names, "tables", names)
        self._table = self._db.open_table(TABLE) if TABLE in names else self._db.create_table(TABLE, schema=schema)
        self.dim = dim
        try:
            self._vacuum()   # an older index may carry thousands of old versions
        except Exception:
            pass   # a cleanup that fails must never stop the index from opening
        tmp = meta_file.with_name(_META + ".tmp")
        tmp.write_text(json.dumps({"model": model, "dim": dim, "schema_version": SCHEMA_VERSION}))
        tmp.replace(meta_file)

    def upsert(self, rows: list[dict]) -> None:
        if not rows:
            return
        data = [{"id": r["id"], "vector": [float(x) for x in r["vector"]], "source": r.get("source", ""), "ref": r.get("ref", ""),
                 "collections": list(r.get("collections", [])), "tags": list(r.get("tags", [])), "text_hash": r.get("text_hash", "")}
                for r in rows]
        (self._table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(data))

    def query(self, vector: list[float], k: int, where: dict | None = None) -> list[dict]:
        if self._table.count_rows() == 0:
            return []
        s = self._table.search([float(x) for x in vector]).metric("cosine")
        if self._indexed():
            s = s.ef(EF_SEARCH)
        sql = _where(where)
        if sql:
            s = s.where(sql, prefilter=True)
        out = []
        for r in s.limit(k).to_list():
            r["score"] = 1.0 - float(r.pop("_distance"))
            r.pop("vector", None)
            out.append(r)
        return out

    def delete(self, ids: list[str]) -> None:
        for i in range(0, len(ids), 500):
            self._table.delete(f"id IN ({', '.join(_q(x) for x in ids[i:i + 500])})")

    def delete_ref(self, ref: str) -> None:
        self._table.delete(f"ref = {_q(ref)}")

    def set_collections(self, ref: str, collections: list[str]) -> None:
        self._table.update(where=f"ref = {_q(ref)}", values_sql={"collections": _arr(collections) if collections else "make_array()"})

    def count(self) -> int:
        return self._table.count_rows()

    def _indexed(self) -> bool:
        return bool(self._table.list_indices())

    def finish(self) -> None:
        if not self._indexed() and self._table.count_rows() >= INDEX_MIN_ROWS:
            self._table.create_index(metric="cosine", vector_column_name="vector", index_type="IVF_HNSW_SQ", replace=True)
        self._vacuum()

    def _vacuum(self) -> None:
        """Compact the many small files single writes leave, index the rows added since, and delete every version except the latest."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)   # lancedb warns about a concurrent reader on an older version: there is none (one lock)
            self._table.optimize(cleanup_older_than=datetime.timedelta(0))

    def close(self) -> None:
        self._table = self._db = None
