"""Workflow governance: configurable multi-stage and parallel approvals, reviewer assignments,
change requests, resubmission, SLAs with escalation, and notifications.

Learning-object status (unchanged from before):
    draft -> submitted | under_review -> approved | rejected
    rejected -> draft (revise) | submitted (resubmit)
    approved -> published

A review case is one submission round. Its stages come from a policy, and the stages are copied
into the case at submission, so later policy edits never move a running case.

    open --(stage approvals reached, not last)--> open (next stage)
    open --(last stage approved)-----------------> approved
    open --(reject)-----------------------------> rejected
    open --(request changes)--------------------> changes_requested
    open --(withdraw)---------------------------> withdrawn
    any non-final round --(resubmit)-----------> superseded, new round opened

Every transition writes a workflow_states row and an audit_log row in the same commit.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    SeparationOfDutiesError,
    ValidationFailure,
)
from app.core.permissions import ROLE_PERMISSIONS, canonical
from app.core.security import Principal, Role
from app.db.models import (
    ApprovalPolicy,
    LearningObject,
    PolicyStage,
    ReviewCase,
    StageTask,
    WorkflowState,
    utcnow,
)
from app.services import audit, versioning
from app.services import notifications as notify_service
from app.services.access import require_object
from app.services.search_index import schedule_index

DRAFT: Final = "draft"
SUBMITTED: Final = "submitted"
UNDER_REVIEW: Final = "under_review"
APPROVED: Final = "approved"
REJECTED: Final = "rejected"
PUBLISHED: Final = "published"

OPEN_CASE_STATES: Final = frozenset({"open", "under_review"})
MAX_STAGES: Final = 10
MAX_ESCALATION_ROLE: Final = "Repository Administrator"

ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    DRAFT: frozenset({SUBMITTED}),
    SUBMITTED: frozenset({UNDER_REVIEW, APPROVED, REJECTED, DRAFT}),
    UNDER_REVIEW: frozenset({APPROVED, REJECTED, DRAFT}),
    APPROVED: frozenset({PUBLISHED}),
    REJECTED: frozenset({DRAFT, SUBMITTED}),
    PUBLISHED: frozenset(),
}

# Used when no policy is named. Behaves like the original single-approval workflow.
DEFAULT_STAGES: Final[list[dict[str, Any]]] = [
    {
        "position": 1,
        "name": "Approval",
        "permission": "workflow.approve",
        "approvals_required": 1,
        "assignees": [],
        "sla_hours": None,
        "escalation_role": MAX_ESCALATION_ROLE,
    }
]


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def _load(session: Session, lo_id: str) -> LearningObject:
    lo = session.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    return lo


def _is_super(actor: Principal) -> bool:
    return Role.SUPER_ADMIN.value in canonical(actor.roles)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def transition(
    session: Session,
    lo: LearningObject,
    target: str,
    actor: Principal,
    comment: str | None = None,
    *,
    commit: bool = True,
) -> LearningObject:
    current = lo.status
    if not can_transition(current, target):
        raise InvalidTransitionError(f"cannot move from '{current}' to '{target}'")
    lo.status = target
    session.add(
        WorkflowState(
            lo_id=lo.id,
            from_state=current,
            to_state=target,
            actor_subject=actor.subject,
            comment=comment,
        )
    )
    audit.record(
        session,
        actor_subject=actor.subject,
        action=f"workflow.{target}",
        entity_type="learning_object",
        entity_id=lo.id,
        details={"from": current, "to": target, "comment": comment},
    )
    schedule_index(session, lo.id)
    if commit:
        session.commit()
    return lo


# --- policies ----------------------------------------------------------------------


def resolve_policy(session: Session, policy_id: int | None) -> tuple[int | None, str, list[dict]]:
    if policy_id is None:
        return None, "Default", [dict(s) for s in DEFAULT_STAGES]
    policy = session.get(ApprovalPolicy, policy_id)
    if policy is None or not policy.active:
        raise ValidationFailure("approval policy not found or inactive")
    rows = session.scalars(
        select(PolicyStage).where(PolicyStage.policy_id == policy_id).order_by(PolicyStage.position)
    ).all()
    if not rows:
        raise ValidationFailure("approval policy has no stages")
    stages = [
        {
            "position": r.position,
            "name": r.name,
            "permission": r.permission,
            "approvals_required": r.approvals_required,
            "assignees": list(r.assignees or []),
            "sla_hours": r.sla_hours,
            "escalation_role": r.escalation_role,
        }
        for r in rows
    ]
    return policy.id, policy.name, stages


def create_policy(
    session: Session, actor: Principal, name: str, description: str, stages: list[dict[str, Any]]
) -> ApprovalPolicy:
    if not stages or len(stages) > MAX_STAGES:
        raise ValidationFailure(f"a policy needs between 1 and {MAX_STAGES} stages")
    known = {p for perms in ROLE_PERMISSIONS.values() for p in perms if p != "*"}
    for index, stage in enumerate(stages, start=1):
        if stage["permission"] not in known:
            raise ValidationFailure(f"unknown permission '{stage['permission']}'")
        if stage["escalation_role"] not in ROLE_PERMISSIONS:
            raise ValidationFailure(f"unknown escalation role '{stage['escalation_role']}'")
        assignees = stage.get("assignees") or []
        if assignees and stage["approvals_required"] > len(assignees):
            raise ValidationFailure(
                f"stage {index} needs more named assignees than approvals required"
            )
        stage["position"] = index
    if session.scalar(select(ApprovalPolicy.id).where(ApprovalPolicy.name == name)) is not None:
        raise ValidationFailure("a policy with this name already exists")
    policy = ApprovalPolicy(name=name, description=description, created_by=actor.subject)
    session.add(policy)
    session.flush()
    for stage in stages:
        session.add(
            PolicyStage(
                policy_id=policy.id,
                position=stage["position"],
                name=stage["name"],
                permission=stage["permission"],
                approvals_required=stage["approvals_required"],
                assignees=list(stage.get("assignees") or []),
                sla_hours=stage.get("sla_hours"),
                escalation_role=stage["escalation_role"],
            )
        )
    audit.record(
        session,
        actor_subject=actor.subject,
        action="policy.create",
        entity_type="approval_policy",
        entity_id=str(policy.id),
        details={"name": name},
    )
    session.commit()
    return policy


def set_policy_active(
    session: Session, actor: Principal, policy_id: int, active: bool
) -> ApprovalPolicy:
    policy = session.get(ApprovalPolicy, policy_id)
    if policy is None:
        raise NotFoundError("approval policy not found")
    policy.active = active
    audit.record(
        session,
        actor_subject=actor.subject,
        action="policy.activate" if active else "policy.deactivate",
        entity_type="approval_policy",
        entity_id=str(policy_id),
    )
    session.commit()
    return policy


# --- case helpers --------------------------------------------------------------------


def open_case(session: Session, lo_id: str) -> ReviewCase | None:
    return session.scalar(
        select(ReviewCase)
        .where(ReviewCase.lo_id == lo_id, ReviewCase.status.in_(OPEN_CASE_STATES))
        .order_by(ReviewCase.round.desc())
    )


def latest_case(session: Session, lo_id: str) -> ReviewCase | None:
    return session.scalar(
        select(ReviewCase).where(ReviewCase.lo_id == lo_id).order_by(ReviewCase.round.desc())
    )


def _stage_def(case: ReviewCase, position: int) -> dict[str, Any]:
    return next(s for s in case.stages if s["position"] == position)


def _open_stage(session: Session, case: ReviewCase, lo: LearningObject) -> None:
    stage = _stage_def(case, case.stage_position)
    due = utcnow() + timedelta(hours=stage["sla_hours"]) if stage.get("sla_hours") else None
    named = list(stage.get("assignees") or [])
    slots: list[str | None] = named if named else [None] * stage["approvals_required"]
    for assignee in slots:
        session.add(
            StageTask(
                case_id=case.id,
                stage_position=case.stage_position,
                permission=stage["permission"],
                assignee_subject=assignee,
                due_at=due,
            )
        )
    session.flush()
    if named:
        recipients = named
    else:
        recipients = notify_service.permission_holders(session, stage["permission"])
    recipients = [r for r in recipients if r != case.submitted_by]
    notify_service.notify(
        session,
        recipients,
        kind="task_assigned",
        title=f"Review needed: {lo.title}",
        body=f"Stage '{stage['name']}' of {case.policy_name} is waiting for your decision.",
        lo_id=lo.id,
    )


def _cancel_open_tasks(session: Session, case: ReviewCase) -> None:
    # Checked in memory: the caller may have just changed a task that is still pending a flush.
    session.flush()
    for task in session.scalars(select(StageTask).where(StageTask.case_id == case.id)):
        if task.state == "open":
            task.state = "cancelled"


def _notify_submitter(
    session: Session, case: ReviewCase, lo: LearningObject, kind: str, title: str, body: str
) -> None:
    notify_service.notify(
        session,
        [case.submitted_by],
        kind=kind,
        title=f"{title}: {lo.title}",
        body=body,
        lo_id=lo.id,
    )


# --- submission and resubmission ---------------------------------------------------------


def submit(
    session: Session,
    lo_id: str,
    actor: Principal,
    comment: str | None = None,
    policy_id: int | None = None,
) -> LearningObject:
    require_object(session, lo_id, actor, "edit")
    lo = _load(session, lo_id)
    if open_case(session, lo_id) is not None:
        raise InvalidTransitionError("this item already has a review in progress")
    resolved_id, policy_name, stages = resolve_policy(session, policy_id)
    snapshot = versioning.ensure_snapshot(session, lo, actor, "submit")
    transition(session, lo, SUBMITTED, actor, comment, commit=False)
    previous = latest_case(session, lo_id)
    if previous is not None and previous.status in {"changes_requested", "rejected"}:
        previous.status = "superseded"
    round_number = (previous.round + 1) if previous is not None else 1
    case = ReviewCase(
        id=str(uuid.uuid4()),
        lo_id=lo_id,
        round=round_number,
        status="open",
        policy_id=resolved_id,
        policy_name=policy_name,
        stages=stages,
        stage_position=1,
        submitted_by=actor.subject,
        snapshot_id=snapshot.id,
    )
    session.add(case)
    session.flush()
    _open_stage(session, case, lo)
    session.commit()
    return lo


def resubmit(
    session: Session,
    lo_id: str,
    actor: Principal,
    comment: str | None = None,
    policy_id: int | None = None,
) -> LearningObject:
    lo = _load(session, lo_id)
    if lo.status != REJECTED:
        raise InvalidTransitionError("only rejected items can be resubmitted")
    previous = latest_case(session, lo_id)
    if previous is None or (previous.submitted_by != actor.subject and not _is_super(actor)):
        raise HTTPException(403, "only the submitter can resubmit")
    # A resubmission keeps the review path it was on, unless the submitter names another policy.
    return submit(session, lo_id, actor, comment,
                  policy_id if policy_id is not None else previous.policy_id)


def withdraw(session: Session, lo_id: str, actor: Principal, comment: str | None = None):
    lo = _load(session, lo_id)
    case = open_case(session, lo_id)
    if case is None:
        raise InvalidTransitionError("there is no review in progress to withdraw")
    if case.submitted_by != actor.subject and not _is_super(actor):
        raise HTTPException(403, "only the submitter can withdraw")
    _cancel_open_tasks(session, case)
    case.status = "withdrawn"
    case.closed_at = utcnow()
    transition(session, lo, DRAFT, actor, comment, commit=False)
    session.commit()
    return lo


# --- decisions ------------------------------------------------------------------------


def decide(
    session: Session,
    lo_id: str,
    actor: Principal,
    decision: str,
    comment: str | None = None,
) -> LearningObject:
    # Visibility is checked here. The capability that matters is the stage's own permission,
    # checked below, so a stage can be assigned to any role.
    require_object(session, lo_id, actor, "read")
    lo = _load(session, lo_id)
    case = open_case(session, lo_id)
    if case is None:
        raise InvalidTransitionError("no review is waiting for a decision")
    # Four-eyes rule: the submitter cannot decide their own submission. Super Administrators
    # are exempt by design.
    if actor.subject == case.submitted_by and not _is_super(actor):
        raise SeparationOfDutiesError("reviewers cannot decide on their own submissions")
    stage = _stage_def(case, case.stage_position)
    allowed = {stage["permission"]}
    if decision != "approve":
        allowed.add("workflow.review")
    if not any(actor.can(p) for p in allowed):
        raise HTTPException(403, f"this stage requires {stage['permission']}")
    if decision in {"reject", "request_changes"} and not (comment and comment.strip()):
        raise ValidationFailure("a comment is required")

    stage_tasks = session.scalars(
        select(StageTask).where(
            StageTask.case_id == case.id, StageTask.stage_position == case.stage_position
        )
    ).all()
    if any(t.decided_by == actor.subject for t in stage_tasks):
        raise ValidationFailure("you have already decided this stage")
    open_tasks = [t for t in stage_tasks if t.state == "open"]
    can_decide_pool = any(actor.can(p) for p in allowed)
    mine = [t for t in open_tasks if t.assignee_subject == actor.subject] or [
        t for t in open_tasks if t.assignee_subject is None and can_decide_pool
    ]
    if not mine:
        raise HTTPException(403, "this review is assigned to someone else")
    task = mine[0]
    task.decided_by = actor.subject
    task.decided_at = utcnow()
    task.comment = comment

    if decision == "approve":
        task.state = "approved"
        # The current task is already marked approved above, so it is counted once here.
        approvals = sum(1 for t in stage_tasks if t.state == "approved")
        if approvals < stage["approvals_required"]:
            audit.record(
                session,
                actor_subject=actor.subject,
                action="workflow.approval_recorded",
                entity_type="learning_object",
                entity_id=lo.id,
                details={
                    "stage": stage["name"],
                    "approvals": approvals,
                    "required": stage["approvals_required"],
                },
            )
            session.commit()
            return lo
        _cancel_open_tasks(session, case)
        last = case.stage_position >= len(case.stages)
        if last:
            case.status = "approved"
            case.closed_at = utcnow()
            transition(session, lo, APPROVED, actor, comment, commit=False)
            _notify_submitter(session, case, lo, "approved", "Approved", comment or "")
        else:
            case.stage_position += 1
            case.status = "open"
            audit.record(
                session,
                actor_subject=actor.subject,
                action="workflow.stage_approved",
                entity_type="learning_object",
                entity_id=lo.id,
                details={"stage": stage["name"], "next_stage": case.stage_position},
            )
            _open_stage(session, case, lo)
            _notify_submitter(
                session,
                case,
                lo,
                "stage_approved",
                "Stage approved",
                f"'{stage['name']}' is approved; the next stage has started.",
            )
        session.commit()
        return lo

    if decision == "reject":
        task.state = "rejected"
        _cancel_open_tasks(session, case)
        case.status = "rejected"
        case.closed_at = utcnow()
        transition(session, lo, REJECTED, actor, comment, commit=False)
        _notify_submitter(session, case, lo, "rejected", "Rejected", comment or "")
    else:
        task.state = "changes_requested"
        _cancel_open_tasks(session, case)
        case.status = "changes_requested"
        case.closed_at = utcnow()
        transition(session, lo, REJECTED, actor, comment, commit=False)
        _notify_submitter(
            session, case, lo, "changes_requested", "Changes requested", comment or ""
        )
    session.commit()
    return lo


def claim_review(session: Session, lo_id: str, actor: Principal) -> LearningObject:
    """Marks an in-progress review as under review, for the Reviewer working on it."""
    require_object(session, lo_id, actor, "review")
    lo = _load(session, lo_id)
    case = open_case(session, lo_id)
    if case is None:
        raise InvalidTransitionError("no review is waiting")
    if case.status == "open":
        case.status = "under_review"
    transition(session, lo, UNDER_REVIEW, actor, commit=False)
    session.commit()
    return lo


# --- assignment and escalation ------------------------------------------------------------


def assign(
    session: Session, lo_id: str, actor: Principal, task_id: int, assignee: str
) -> StageTask:
    if not actor.can("workflow.assign"):
        raise HTTPException(403, "Requires permission: workflow.assign")
    lo = _load(session, lo_id)
    case = open_case(session, lo_id)
    task = session.get(StageTask, task_id)
    if case is None or task is None or task.case_id != case.id or task.state != "open":
        raise NotFoundError("open review task not found")
    previous = task.assignee_subject
    task.assignee_subject = assignee
    audit.record(
        session,
        actor_subject=actor.subject,
        action="workflow.assign",
        entity_type="learning_object",
        entity_id=lo.id,
        details={"task": task_id, "from": previous, "to": assignee},
    )
    notify_service.notify(
        session,
        [assignee],
        kind="task_assigned",
        title=f"Review assigned to you: {lo.title}",
        body=f"You were assigned stage '{_stage_def(case, task.stage_position)['name']}'.",
        lo_id=lo.id,
    )
    session.commit()
    return task


def run_sla(session: Session, actor: Principal) -> dict[str, int]:
    """Flags overdue tasks and escalates each once to the stage's escalation role."""
    now = utcnow()
    escalated = 0
    tasks = session.scalars(
        select(StageTask).where(
            StageTask.state == "open",
            StageTask.due_at.isnot(None),
            StageTask.escalated_at.is_(None),
        )
    ).all()
    for task in tasks:
        if _aware(task.due_at) > now:
            continue
        case = session.get(ReviewCase, task.case_id)
        if case is None or case.status not in OPEN_CASE_STATES:
            continue
        lo = session.get(LearningObject, case.lo_id)
        stage = _stage_def(case, task.stage_position)
        task.escalated_at = now
        escalated += 1
        recipients = notify_service.role_holders(session, stage["escalation_role"])
        if task.assignee_subject:
            recipients.append(task.assignee_subject)
        notify_service.notify(
            session,
            recipients,
            kind="escalation",
            title=f"Overdue review: {lo.title}",
            body=f"Stage '{stage['name']}' passed its {stage['sla_hours']}-hour SLA.",
            lo_id=lo.id,
        )
    audit.record(
        session,
        actor_subject=actor.subject,
        action="workflow.sla_run",
        entity_type="workflow",
        entity_id="sla",
        details={"escalated": escalated},
    )
    session.commit()
    return {"escalated": escalated}


# --- queues and views -------------------------------------------------------------------


def queue(session: Session, actor: Principal) -> list[dict[str, Any]]:
    tasks = session.scalars(
        select(StageTask)
        .join(ReviewCase, ReviewCase.id == StageTask.case_id)
        .where(StageTask.state == "open", ReviewCase.status.in_(OPEN_CASE_STATES))
        .order_by(StageTask.due_at.is_(None), StageTask.due_at, StageTask.id)
    ).all()
    now = utcnow()
    result = []
    for task in tasks:
        mine = task.assignee_subject == actor.subject or (
            task.assignee_subject is None and actor.can(task.permission)
        )
        if not mine or task.decided_by == actor.subject:
            continue
        case = session.get(ReviewCase, task.case_id)
        lo = session.get(LearningObject, case.lo_id)
        due = _aware(task.due_at)
        result.append(
            {
                "task_id": task.id,
                "lo_id": lo.id,
                "title": lo.title,
                "stage": _stage_def(case, task.stage_position)["name"],
                "round": case.round,
                "policy": case.policy_name,
                "pooled": task.assignee_subject is None,
                "due_at": due.isoformat() if due else None,
                "overdue": bool(due and due < now),
            }
        )
    return result


def case_view(session: Session, lo_id: str, actor: Principal) -> dict[str, Any] | None:
    require_object(session, lo_id, actor, "read")
    case = latest_case(session, lo_id)
    if case is None:
        return None
    tasks = session.scalars(
        select(StageTask)
        .where(StageTask.case_id == case.id)
        .order_by(StageTask.stage_position, StageTask.id)
    ).all()
    history = session.scalars(
        select(WorkflowState).where(WorkflowState.lo_id == lo_id).order_by(WorkflowState.id)
    ).all()
    return {
        "id": case.id,
        "round": case.round,
        "status": case.status,
        "policy": case.policy_name,
        "stage_position": case.stage_position,
        "submitted_by": case.submitted_by,
        "stages": case.stages,
        "tasks": [
            {
                "id": t.id,
                "stage": t.stage_position,
                "permission": t.permission,
                "assignee": t.assignee_subject,
                "state": t.state,
                "decided_by": t.decided_by,
                "comment": t.comment,
                "due_at": t.due_at.isoformat() if t.due_at else None,
            }
            for t in tasks
        ],
        "history": [
            {
                "from": h.from_state,
                "to": h.to_state,
                "by": h.actor_subject,
                "comment": h.comment,
                "at": h.created_at.isoformat(),
            }
            for h in history
        ],
    }


def publish(session: Session, lo_id: str, actor: Principal) -> LearningObject:
    require_object(session, lo_id, actor, "publish")
    lo = _load(session, lo_id)
    # Separation of duties: whoever approved the item cannot also publish it.
    last = latest_case(session, lo_id)
    if last is not None and last.status == "approved":
        current = versioning.latest(session, lo_id)
        if current is not None and last.snapshot_id != current.id:
            raise ConflictError("the item changed after it was approved; resubmit for approval")
    if last is not None and last.status == "approved" and not _is_super(actor):
        approvers = {
            t.decided_by
            for t in session.scalars(
                select(StageTask).where(StageTask.case_id == last.id, StageTask.state == "approved")
            )
        }
        if actor.subject in approvers:
            raise SeparationOfDutiesError("the approver of an item cannot also publish it")
    return transition(session, lo, PUBLISHED, actor)
