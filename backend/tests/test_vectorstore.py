"""Phase 6: sqlite-vec wrapper and retriever, using a fake embedding function (no AWS)."""

import pytest

from app.agents.tools.vector_retriever import VectorRetriever
from app.vectorstore.sqlite_vec import SqliteVecStore


@pytest.fixture
def store():
    s = SqliteVecStore(":memory:", dimensions=4)
    yield s
    s.close()


def test_add_then_search_returns_nearest_first(store):
    store.add("lo:a", [1.0, 0.0, 0.0, 0.0])
    store.add("lo:b", [0.0, 1.0, 0.0, 0.0])
    results = store.search([0.9, 0.1, 0.0, 0.0], k=2)
    assert results[0][0] == "lo:a"
    assert results[0][1] > results[1][1]


def test_add_replaces_existing_id(store):
    store.add("lo:a", [1.0, 0.0, 0.0, 0.0])
    store.add("lo:a", [0.0, 0.0, 0.0, 1.0])
    ids = [row_id for row_id, _ in store.search([0.0, 0.0, 0.0, 1.0], k=5)]
    assert ids.count("lo:a") == 1


def test_delete_removes_id(store):
    store.add("lo:a", [1.0, 0.0, 0.0, 0.0])
    store.add("lo:b", [0.0, 1.0, 0.0, 0.0])
    store.delete("lo:a")
    ids = [row_id for row_id, _ in store.search([1.0, 0.0, 0.0, 0.0], k=5)]
    assert "lo:a" not in ids
    assert "lo:b" in ids


def test_wrong_dimension_is_rejected(store):
    with pytest.raises(ValueError, match="expected 4 dimensions"):
        store.add("lo:a", [1.0, 0.0])


def test_retriever_filters_by_namespace(store, fake_embeddings):
    vec = fake_embeddings.embed_query("data literacy")

    # Build a 4-d store matching the 8-d fake? Use the retriever with a matching-size fake.
    class Fake4:
        def embed_query(self, text):
            return [1.0, 0.0, 0.0, 0.0]

    store.add("term:skills:data-literacy", [1.0, 0.0, 0.0, 0.0])
    store.add("lo:123", [1.0, 0.0, 0.0, 0.0])
    retriever = VectorRetriever(Fake4(), store)
    hits = retriever.retrieve("anything", k=5, prefix="term:")
    assert [h[0] for h in hits] == ["skills:data-literacy"]
    assert vec  # fake embeddings produce a vector of the expected size
    assert len(vec) == fake_embeddings.DIMS
