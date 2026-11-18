"""Wires graphs to real dependencies: Bedrock models, the vector store, and SqliteSaver."""

import sqlite3
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from langgraph.types import Command

from app.agents.deps import GraphDeps
from app.agents.graph import build_ask_graph, build_ingest_graph
from app.agents.tools.vector_retriever import VectorRetriever
from app.api.deps import get_storage
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.llm.bedrock import get_chat_model, get_embeddings
from app.vectorstore.sqlite_vec import SqliteVecStore


class AgentRuntime:
    def __init__(self, ingest_graph: Any, ask_graph: Any) -> None:
        self._ingest = ingest_graph
        self._ask = ask_graph

    @staticmethod
    def _config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def run_ingest(self, thread_id: str, inputs: dict) -> dict:
        return self._ingest.invoke(inputs, config=self._config(thread_id))

    def resume_ingest(self, thread_id: str, resume_payload: dict) -> dict:
        return self._ingest.invoke(Command(resume=resume_payload), config=self._config(thread_id))

    def ask(self, question: str) -> Iterator[str]:
        """Run the ask graph, then yield the answer in word-sized chunks for SSE.

        NOTE: the answer is generated in one call and then chunked. True token streaming from
        Bedrock (ChatBedrock.stream) is a follow-up; the SSE contract does not change.
        """
        state = self._ask.invoke({"query": question, "messages": []})
        answer = str(state.get("answer", ""))
        words = answer.split(" ")
        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else word + " "


@lru_cache
def get_runtime() -> AgentRuntime:
    settings = get_settings()
    checkpoint_conn = sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False)
    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpointer = SqliteSaver(checkpoint_conn)
    vectors = SqliteVecStore(settings.vector_db_path, settings.embedding_dimensions)
    embeddings = get_embeddings(settings)
    deps = GraphDeps(
        storage=get_storage(),
        llm_factory=lambda: get_chat_model(settings),
        retriever=VectorRetriever(embeddings, vectors),
        session_factory=get_session_factory(),
        compliance_threshold=settings.compliance_threshold,
        taxonomy_threshold=settings.taxonomy_confidence_threshold,
        metadata_threshold=settings.metadata_confidence_threshold,
    )
    return AgentRuntime(
        ingest_graph=build_ingest_graph(deps, checkpointer),
        ask_graph=build_ask_graph(deps),
    )
