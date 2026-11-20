"""Workflow governance endpoints. Business rules live in app.services.workflow."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import ApprovalPolicy, PolicyStage
from app.db.session import get_db
from app.schemas.workflow import (
    AssignIn,
    DecisionRequest,
    PolicyIn,
    PolicyUpdate,
    SubmitRequest,
    WorkflowStateOut,
)
from app.services import workflow as workflow_service

router = APIRouter(prefix="/workflow", tags=["workflow"])


def _state(lo) -> WorkflowStateOut:  # noqa: ANN001
    return WorkflowStateOut(lo_id=lo.id, status=lo.status)


@router.post("/{lo_id}/submit", response_model=WorkflowStateOut)
def submit(
    lo_id: str,
    payload: Annotated[SubmitRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.submit")),
) -> WorkflowStateOut:
    lo = workflow_service.submit(
        db,
        lo_id,
        principal,
        payload.comment if payload else None,
        payload.policy_id if payload else None,
    )
    return _state(lo)


@router.post("/{lo_id}/resubmit", response_model=WorkflowStateOut)
def resubmit(
    lo_id: str,
    payload: Annotated[SubmitRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.submit")),
) -> WorkflowStateOut:
    lo = workflow_service.resubmit(
        db,
        lo_id,
        principal,
        payload.comment if payload else None,
        payload.policy_id if payload else None,
    )
    return _state(lo)


@router.post("/{lo_id}/withdraw", response_model=WorkflowStateOut)
def withdraw(
    lo_id: str,
    payload: Annotated[SubmitRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.submit")),
) -> WorkflowStateOut:
    return _state(
        workflow_service.withdraw(db, lo_id, principal, payload.comment if payload else None)
    )


@router.post("/{lo_id}/decision", response_model=WorkflowStateOut)
def decision(
    lo_id: str,
    payload: DecisionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> WorkflowStateOut:
    return _state(workflow_service.decide(db, lo_id, principal, payload.decision, payload.comment))


@router.post("/{lo_id}/review", response_model=WorkflowStateOut)
def review(
    lo_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.review")),
) -> WorkflowStateOut:
    return _state(workflow_service.claim_review(db, lo_id, principal))


@router.post("/{lo_id}/publish", response_model=WorkflowStateOut)
def publish(
    lo_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.publish")),
) -> WorkflowStateOut:
    return _state(workflow_service.publish(db, lo_id, principal))


@router.get("/{lo_id}/case")
def case(
    lo_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    view = workflow_service.case_view(db, lo_id, principal)
    if view is None:
        raise NotFoundError("no review has been started for this item")
    return view


@router.post("/{lo_id}/tasks/{task_id}/assign")
def assign(
    lo_id: str,
    task_id: int,
    payload: AssignIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict[str, Any]:
    task = workflow_service.assign(db, lo_id, principal, task_id, payload.assignee_subject)
    return {"task_id": task.id, "assignee": task.assignee_subject}


@router.get("/queue")
def my_queue(db: Session = Depends(get_db), principal: Principal = Depends(get_principal)):
    return {"items": workflow_service.queue(db, principal)}


@router.post("/sla/run")
def run_sla(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("organization.manage")),
) -> dict[str, int]:
    return workflow_service.run_sla(db, principal)


def _policy_out(policy: ApprovalPolicy, db: Session) -> dict[str, Any]:
    stages = db.scalars(
        select(PolicyStage).where(PolicyStage.policy_id == policy.id).order_by(PolicyStage.position)
    ).all()
    return {
        "id": policy.id,
        "name": policy.name,
        "description": policy.description,
        "active": policy.active,
        "stages": [
            {
                "position": s.position,
                "name": s.name,
                "permission": s.permission,
                "approvals_required": s.approvals_required,
                "assignees": list(s.assignees or []),
                "sla_hours": s.sla_hours,
                "escalation_role": s.escalation_role,
            }
            for s in stages
        ],
    }


@router.get("/policies")
def list_policies(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.policy")),
) -> dict[str, Any]:
    rows = db.scalars(select(ApprovalPolicy).order_by(ApprovalPolicy.name)).all()
    return {"items": [_policy_out(p, db) for p in rows]}


@router.post("/policies", status_code=201)
def create_policy(
    payload: PolicyIn,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.policy")),
) -> dict[str, Any]:
    stages = [s.model_dump() for s in payload.stages]
    policy = workflow_service.create_policy(
        db, principal, payload.name.strip(), payload.description, stages
    )
    return _policy_out(policy, db)


@router.put("/policies/{policy_id}")
def update_policy(
    policy_id: int,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("workflow.policy")),
) -> dict[str, Any]:
    policy = workflow_service.set_policy_active(db, principal, policy_id, payload.active)
    return _policy_out(policy, db)
