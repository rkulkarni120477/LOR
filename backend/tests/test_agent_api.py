"""Agent endpoints end-to-end through HTTP, with Bedrock replaced by a fake LLM."""

import json
import sqlite3

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.agents.deps import GraphDeps
from app.agents.graph import build_ask_graph, build_ingest_graph
from app.agents.runtime import AgentRuntime, get_runtime
from app.db.models import MetadataLOM
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
        "license": None,
        "confidence": 0.85,
    }
)


@pytest.fixture
def runtime(client, engine, tmp_path):
    llm = FakeLLM(LLM_JSON)
    deps = GraphDeps(
        storage=LocalStorage(tmp_path / "storage"),
        llm_factory=lambda: llm,
        session_factory=sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
        compliance_threshold=0.7,
    )
    checkpointer = SqliteSaver(sqlite3.connect(":memory:", check_same_thread=False))
    rt = AgentRuntime(
        ingest_graph=build_ingest_graph(deps, checkpointer),
        ask_graph=build_ask_graph(deps),
    )
    client.app.dependency_overrides[get_runtime] = lambda: rt
    return rt


def _upload(client, token_factory, package: bytes) -> str:
    response = client.post(
        "/api/v1/content",
        data={"title": "Data Basics"},
        files={"file": ("pkg.zip", package, "application/zip")},
        headers={"Authorization": f"Bearer {token_factory(['Contributor'], sub='contrib-1')}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_ingest_high_score_completes_and_writes_draft_metadata(
    client, token_factory, runtime, db_session
):
    lo_id = _upload(
        client, token_factory, build_package(images=[("a.png", "Chart")], license_text="CC-BY-4.0")
    )
    response = client.post(
        f"/api/v1/agents/ingest/{lo_id}",
        headers={"Authorization": f"Bearer {token_factory(['Contributor'], sub='contrib-1')}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["extracted_metadata"]["subject"] == "data-literacy"

    meta = db_session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo_id))
    db_session.refresh(meta)
    assert meta.subject == "data-literacy"
    assert meta.extraction_confidence == pytest.approx(0.85)


def test_ingest_low_score_pauses_then_resume_completes(client, token_factory, runtime):
    lo_id = _upload(client, token_factory, build_package(images=[("a.png", "")], license_text=None))
    contributor = {"Authorization": f"Bearer {token_factory(['Contributor'], sub='contrib-1')}"}
    paused = client.post(f"/api/v1/agents/ingest/{lo_id}", headers=contributor)
    assert paused.status_code == 200, paused.text
    body = paused.json()
    assert body["status"] == "paused"
    assert body["interrupt"]["lo_id"] == lo_id
    assert body["compliance_score"] < 0.7

    resumed = client.post(
        f"/api/v1/agents/resume/{body['thread_id']}",
        json={"decision": "approve", "comment": "accepted risk"},
        headers={"Authorization": f"Bearer {token_factory(['Reviewer'], sub='reviewer-1')}"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["next_action"] == "ready_for_submission"


def test_resume_requires_reviewer_role(client, token_factory, runtime):
    response = client.post(
        "/api/v1/agents/resume/ingest:x:y",
        json={"decision": "approve"},
        headers={"Authorization": f"Bearer {token_factory(['Contributor'])}"},
    )
    assert response.status_code == 403


def test_ask_streams_server_sent_events(client, token_factory, runtime):
    response = client.post(
        "/api/v1/agents/ask",
        json={"question": "what is the weather in London"},
        headers={"Authorization": f"Bearer {token_factory(['Learner'], sub='learner-1')}"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: token" in response.text
    assert "event: done" in response.text
