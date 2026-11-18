"""Agent endpoints. Ingest and resume return JSON; /ask streams Server-Sent Events."""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agents.runtime import AgentRuntime, get_runtime
from app.core.errors import NotFoundError
from app.core.security import Principal, Role, require_roles
from app.db.session import get_db
from app.schemas.agents import AgentRunResponse, AskRequest, ResumeRequest
from app.services import agent_runs

router = APIRouter(prefix="/agents", tags=["agents"])


@contextmanager
def _ai_service_errors():
    """Turn AWS/Bedrock failures into a clear 503 instead of a generic 500."""
    try:
        yield
    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=503,
            detail="AI service unavailable: AWS credentials were not found. "
            "Configure an AWS profile or IAM role (see infra/aws/README.md).",
        ) from exc
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"AI service unavailable: {type(exc).__name__}. Check AWS region and "
            "Bedrock model access.",
        ) from exc


def _to_response(thread_id: str, state: dict) -> AgentRunResponse:
    interrupts = state.get("__interrupt__")
    if interrupts:
        return AgentRunResponse(
            thread_id=thread_id,
            status="paused",
            compliance_score=state.get("compliance_score"),
            compliance_issues=state.get("compliance_issues", []),
            interrupt=interrupts[0].value if hasattr(interrupts[0], "value") else None,
        )
    return AgentRunResponse(
        thread_id=thread_id,
        status="completed",
        next_action=state.get("next_action"),
        compliance_score=state.get("compliance_score"),
        compliance_issues=state.get("compliance_issues", []),
        extracted_metadata=state.get("extracted_metadata"),
        taxonomy_tags=state.get("taxonomy_tags", []),
    )


@router.post("/ingest/{lo_id}", response_model=AgentRunResponse)
def ingest(
    lo_id: str,
    db: Session = Depends(get_db),
    runtime: AgentRuntime = Depends(get_runtime),
    principal: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
) -> AgentRunResponse:
    lo = agent_runs.load_package_key(db, lo_id, principal)
    thread_id = f"ingest:{lo_id}:{uuid.uuid4()}"
    with _ai_service_errors():
        state = runtime.run_ingest(
            thread_id,
            {"lo_id": lo_id, "file_path": lo, "messages": [], "review_decision": ""},
        )
    if state.get("__interrupt__") is None:
        agent_runs.apply_draft_metadata(db, lo_id, state, principal)
    return _to_response(thread_id, state)


@router.post("/resume/{thread_id}", response_model=AgentRunResponse)
def resume(
    thread_id: str,
    payload: ResumeRequest,
    db: Session = Depends(get_db),
    runtime: AgentRuntime = Depends(get_runtime),
    principal: Principal = Depends(require_roles(Role.REVIEWER)),
) -> AgentRunResponse:
    if not thread_id.startswith("ingest:"):
        raise NotFoundError("unknown agent thread")
    with _ai_service_errors():
        state = runtime.resume_ingest(
            thread_id,
            {
                "decision": payload.decision,
                "comment": payload.comment or "",
                "reviewer": principal.subject,
            },
        )
    lo_id = thread_id.split(":")[1]
    if state.get("__interrupt__") is None:
        agent_runs.apply_draft_metadata(db, lo_id, state, principal)
    return _to_response(thread_id, state)


@router.post("/ask")
def ask(
    payload: AskRequest,
    runtime: AgentRuntime = Depends(get_runtime),
    principal: Principal = Depends(require_roles(Role.LEARNER)),
) -> StreamingResponse:
    answer_chunks = runtime.ask(payload.question)

    def events() -> Iterator[str]:
        for chunk in answer_chunks:
            yield f"event: token\ndata: {json.dumps({'text': chunk})}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
