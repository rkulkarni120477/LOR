"""sqlite-vec wrapper: add / search / delete on a vec0 table with cosine distance.

Ids are namespaced by the caller, e.g. "lo:<uuid>" or "term:<scheme>:<code>".
The extension is loaded on every connection in __init__.
"""

import sqlite3
import threading

import sqlite_vec

_SAFE_TABLE = "lo_vectors"


class SqliteVecStore:
    def __init__(self, path: str, dimensions: int, table: str = _SAFE_TABLE) -> None:
        if not table.isidentifier():
            raise ValueError("invalid table name")
        self._dims = dimensions
        self._table = table
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {self._table} USING vec0("
            f"id TEXT PRIMARY KEY, embedding float[{dimensions}] distance_metric=cosine)"
        )
        self._conn.commit()

    def _check(self, vector: list[float]) -> bytes:
        if len(vector) != self._dims:
            raise ValueError(f"expected {self._dims} dimensions, got {len(vector)}")
        return sqlite_vec.serialize_float32(vector)

    def add(self, id: str, text_embedding: list[float]) -> None:  # noqa: A002
        payload = self._check(text_embedding)
        with self._lock:
            self._conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (id,))
            self._conn.execute(
                f"INSERT INTO {self._table}(id, embedding) VALUES (?, ?)", (id, payload)
            )
            self._conn.commit()

    def search(self, query_embedding: list[float], k: int) -> list[tuple[str, float]]:
        """Return (id, similarity) pairs, most similar first. similarity = 1 - cosine distance."""
        payload = self._check(query_embedding)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, distance FROM {self._table} "
                "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                (payload, k),
            ).fetchall()
        return [(row_id, 1.0 - float(distance)) for row_id, distance in rows]

    def delete(self, id: str) -> None:  # noqa: A002
        with self._lock:
            self._conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (id,))
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
