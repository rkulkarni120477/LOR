"""Workflow state machine.

    draft -> submitted -> approved | rejected
    approved -> published
    rejected -> draft            (contributor revises and resubmits)  [addition to the spec]

Every transition writes a workflow_states row and an audit_log row in the same commit.
"""

from typing import Final

from sqlalchemy.orm import Session

from app.core.errors import InvalidTransitionError, NotFoundError, SeparationOfDutiesError
from app.core.security import Principal, Role
from app.db.models import LearningObject, WorkflowState
from app.services import audit
from app.services.search_index import schedule_index

DRAFT: Final = "draft"
SUBMITTED: Final = "submitted"
APPROVED: Final = "approved"
REJECTED: Final = "rejected"
PUBLISHED: Final = "published"

ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    DRAFT: frozenset({SUBMITTED}),
    SUBMITTED: frozenset({APPROVED, REJECTED}),
    APPROVED: frozenset({PUBLISHED}),
    REJECTED: frozenset({DRAFT}),
    PUBLISHED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def _load(session: Session, lo_id: str) -> LearningObject:
    lo = session.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    return lo


def transition(
    session: Session,
    lo: LearningObject,
    target: str,
    actor: Principal,
    comment: str | None = None,
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
    session.commit()
    return lo


def submit(session: Session, lo_id: str, actor: Principal, comment: str | None = None):
    lo = _load(session, lo_id)
    return transition(session, lo, SUBMITTED, actor, comment)


def decide(
    session: Session,
    lo_id: str,
    actor: Principal,
    decision: str,
    comment: str | None = None,
):
    lo = _load(session, lo_id)
    # Four-eyes rule: a Reviewer cannot approve or reject their own submission. Admin is exempt
    # by design (superuser), so an Admin may approve an item they submitted.
    if actor.subject == lo.created_by and Role.ADMIN.value not in actor.roles:
        raise SeparationOfDutiesError("reviewers cannot decide on their own submissions")
    target = APPROVED if decision == "approve" else REJECTED
    return transition(session, lo, target, actor, comment)


def publish(session: Session, lo_id: str, actor: Principal):
    lo = _load(session, lo_id)
    return transition(session, lo, PUBLISHED, actor)
