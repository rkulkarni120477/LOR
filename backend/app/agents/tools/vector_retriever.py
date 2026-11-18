"""Thin retriever over the vector store. Callers pass a namespace prefix, e.g. "term:" or "lo:"."""

from typing import Any

from app.vectorstore.sqlite_vec import SqliteVecStore


class VectorRetriever:
    def __init__(self, embeddings: Any, store: SqliteVecStore) -> None:
        self._embeddings = embeddings
        self._store = store

    def retrieve(self, text: str, k: int, prefix: str, min_similarity: float = 0.0):
        """Return (id_without_prefix, similarity) for matches at or above min_similarity."""
        vector = self._embeddings.embed_query(text)
        hits = self._store.search(vector, k=k * 4)  # over-fetch, then filter by namespace
        results = [
            (row_id.removeprefix(prefix), score)
            for row_id, score in hits
            if row_id.startswith(prefix) and score >= min_similarity
        ]
        return results[:k]
