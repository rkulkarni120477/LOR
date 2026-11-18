"""Dependencies injected into graph nodes. Tests supply fakes; production wires Bedrock."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.agents.tools.vector_retriever import VectorRetriever
from app.storage.base import StorageBackend


@dataclass
class GraphDeps:
    storage: StorageBackend
    # Factories are called lazily so no AWS client is created until a node runs.
    llm_factory: Callable[[], Any]
    retriever: VectorRetriever | None = None
    session_factory: Callable[[], Any] | None = None
    compliance_threshold: float = 0.7
    taxonomy_threshold: float = 0.5
    metadata_threshold: float = 0.6
