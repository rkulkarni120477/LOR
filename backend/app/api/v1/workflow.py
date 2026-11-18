from typing import Annotated

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.security import Principal, Role, require_roles
from app.db.session import get_db
from app.schemas.workflow import DecisionRequest, SubmitRequest, WorkflowStateOut
from app.services import workflow as workflow_service

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.post("/{lo_id}/submit", response_model=WorkflowStateOut)
def submit(
    lo_id: str,
    payload: Annotated[SubmitRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(Role.CONTRIBUTOR)),
) -> WorkflowStateOut:
    lo = workflow_service.submit(db, lo_id, principal, payload.comment if payload else None)
    return WorkflowStateOut(lo_id=lo.id, status=lo.status)


@router.post("/{lo_id}/decision", response_model=WorkflowStateOut)
def decision(
    lo_id: str,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(Role.REVIEWER)),
) -> WorkflowStateOut:
    lo = workflow_service.decide(db, lo_id, principal, payload.decision, payload.comment)
    return WorkflowStateOut(lo_id=lo.id, status=lo.status)


@router.post("/{lo_id}/publish", response_model=WorkflowStateOut)
def publish(
    lo_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(Role.REVIEWER, Role.ADMIN)),
) -> WorkflowStateOut:
    lo = workflow_service.publish(db, lo_id, principal)
    return WorkflowStateOut(lo_id=lo.id, status=lo.status)
