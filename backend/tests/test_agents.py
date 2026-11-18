"""Phase 7: LangGraph ingest supervisor (interrupt, resume) and ask graph, with Bedrock mocked."""

import json
import sqlite3
import uuid

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from sqlalchemy.orm import sessionmaker

from app.agents.deps import GraphDeps
from app.agents.graph import build_ask_graph, build_ingest_graph
from app.agents.tools.db_query import run_template
from app.agents.tools.file_parser import parse_package
from app.agents.tools.vector_retriever import VectorRetriever
from app.db.models import XapiStatement
from app.llm.guardrails import apply_guardrail
from app.storage.local import LocalStorage
from tests.conftest import FakeLLM, build_package

LLM_JSON = json.dumps(
    {
        "title": "Data Basics",
        "description": "Intro to data",
        "language": "en",
        "keywords": ["data"],
        "subject": "data-literacy",
        "learning_resource_type": "course",
        "license": "CC-BY-4.0",
        "confidence": 0.9,
    }
)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def checkpointer():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    return SqliteSaver(conn)


def _deps(storage, llm_response=LLM_JSON, threshold=0.7, retriever=None, session_factory=None):
    llm = FakeLLM(llm_response)
    return (
        GraphDeps(
            storage=storage,
            llm_factory=lambda: llm,
            retriever=retriever,
            session_factory=session_factory,
            compliance_threshold=threshold,
        ),
        llm,
    )


def _store(storage, data: bytes) -> str:
    key = f"{uuid.uuid4()}/v1/pkg.zip"
    storage.save(key, data)
    return key


def _config():
    return {"configurable": {"thread_id": f"t-{uuid.uuid4()}"}}


# --- file parser -----------------------------------------------------------------------------


def test_parser_counts_images_and_alt_text():
    info = parse_package(
        build_package(images=[("a.png", "Chart"), ("b.png", "")], license_text="CC-BY-4.0")
    )
    assert info.img_count == 2
    assert info.img_with_alt == 1
    assert info.manifest_license == "CC-BY-4.0"
    assert info.manifest_title == "Data Basics"


def test_parser_handles_invalid_zip():
    info = parse_package(b"not a zip")
    assert info.is_valid_zip is False


# --- ingest: high score path --------------------------------------------------------------------


def test_ingest_high_score_produces_metadata_and_completes(storage, checkpointer):
    key = _store(storage, build_package(images=[("a.png", "Chart")], license_text="CC-BY-4.0"))
    deps, llm = _deps(storage)
    graph = build_ingest_graph(deps, checkpointer)

    config = _config()
    state = graph.invoke({"lo_id": "lo-1", "file_path": key, "messages": []}, config)

    assert "__interrupt__" not in state
    assert state["extracted_metadata"]["title"] == "Data Basics"
    assert state["extracted_metadata"]["subject"] == "data-literacy"
    assert state["compliance_score"] == 1.0
    assert state["next_action"] == "ready_for_submission"
    assert len(llm.prompts) == 1


# --- ingest: low score pauses at interrupt, resume completes it ----------------------------------


def _low_score_package():
    # Missing alt text and missing license => score below 0.7.
    return build_package(images=[("a.png", "")], license_text=None)


def test_low_score_pauses_at_interrupt(storage, checkpointer):
    key = _store(storage, _low_score_package())
    deps, _ = _deps(storage)
    graph = build_ingest_graph(deps, checkpointer)

    config = _config()
    state = graph.invoke({"lo_id": "lo-2", "file_path": key, "messages": []}, config)

    assert "__interrupt__" in state
    payload = state["__interrupt__"][0].value
    assert payload["lo_id"] == "lo-2"
    assert payload["compliance_score"] < 0.7
    assert any("alt text" in issue for issue in payload["compliance_issues"])


def test_resume_with_approve_completes_run(storage, checkpointer):
    key = _store(storage, _low_score_package())
    deps, _ = _deps(storage)
    graph = build_ingest_graph(deps, checkpointer)
    config = _config()
    graph.invoke({"lo_id": "lo-3", "file_path": key, "messages": []}, config)

    final = graph.invoke(Command(resume={"decision": "approve", "comment": "ok"}), config)
    assert "__interrupt__" not in final
    assert final["review_decision"] == "approve"
    assert final["next_action"] == "ready_for_submission"


def test_resume_with_reject_returns_to_contributor(storage, checkpointer):
    key = _store(storage, _low_score_package())
    deps, _ = _deps(storage)
    graph = build_ingest_graph(deps, checkpointer)
    config = _config()
    graph.invoke({"lo_id": "lo-4", "file_path": key, "messages": []}, config)

    final = graph.invoke(Command(resume={"decision": "reject", "comment": "fix alt"}), config)
    assert final["review_decision"] == "reject"
    assert final["next_action"] == "return_to_contributor"


def test_invalid_llm_output_falls_back_without_crashing(storage, checkpointer):
    key = _store(storage, build_package(images=[("a.png", "Chart")], license_text="CC-BY-4.0"))
    deps, _ = _deps(storage, llm_response="sorry, I cannot help with that")
    graph = build_ingest_graph(deps, checkpointer)
    state = graph.invoke({"lo_id": "lo-5", "file_path": key, "messages": []}, _config())
    assert state["extracted_metadata"]["confidence"] == 0.0
    assert any("fallback" in m for m in state["messages"])


# --- taxonomy + retrieval ------------------------------------------------------------------------


def test_taxonomy_tags_come_from_vector_store(storage, checkpointer, fake_embeddings):
    from app.vectorstore.sqlite_vec import SqliteVecStore

    store = SqliteVecStore(":memory:", dimensions=fake_embeddings.DIMS)
    store.add("term:skills:data-literacy", fake_embeddings.embed_query("Data Basics Intro to data"))
    store.add("term:skills:leadership", fake_embeddings.embed_query("zzz unrelated qqq"))
    retriever = VectorRetriever(fake_embeddings, store)

    key = _store(storage, build_package(images=[("a.png", "Chart")], license_text="CC-BY-4.0"))
    deps, _ = _deps(storage, retriever=retriever)
    deps.taxonomy_threshold = 0.5
    graph = build_ingest_graph(deps, checkpointer)
    state = graph.invoke({"lo_id": "lo-6", "file_path": key, "messages": []}, _config())
    assert "skills:data-literacy" in state["taxonomy_tags"]


# --- ask graph and reporting -------------------------------------------------------------------


def test_ask_routes_completion_question_to_reporting(engine, db_session, storage):
    db_session.add(
        XapiStatement(
            id=str(uuid.uuid4()),
            actor_key="mailto:a@x.com",
            verb_id="http://adlnet.gov/expapi/verbs/completed",
            object_id="https://lor/lo-1",
            statement={},
        )
    )
    db_session.commit()
    deps, _ = _deps(storage, session_factory=sessionmaker(bind=engine))
    graph = build_ask_graph(deps)
    state = graph.invoke({"query": "How many completions do we have in total?", "messages": []})
    assert "completions_total" in state["answer"]
    assert "1" in state["answer"]


def test_ask_non_report_question_goes_to_search(storage):
    deps, _ = _deps(storage)  # no retriever configured -> search node reports that
    state = build_ask_graph(deps).invoke({"query": "best course on leadership", "messages": []})
    assert "not configured" in state["answer"]


def test_reporting_unsupported_template_lists_capabilities(engine, storage):
    from app.agents.nodes.reporting import make_reporting_node

    deps, _ = _deps(storage, session_factory=sessionmaker(bind=engine))
    node = make_reporting_node(deps)
    result = node({"query": "what is the weather in London", "messages": []})
    assert "I can answer" in result["answer"]


def test_reporting_templates_are_read_only_selects(engine, db_session):
    from sqlalchemy import Select

    from app.agents.tools.db_query import TEMPLATES

    for name, builder in TEMPLATES.items():
        stmt = builder(None)
        assert isinstance(stmt, Select), name
        assert run_template(db_session, name) is not None


def test_guardrails_pass_through_when_disabled(settings):
    result = apply_guardrail("hello", settings=settings)
    assert result.allowed is True
    assert result.text == "hello"
