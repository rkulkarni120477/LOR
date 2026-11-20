"""One SQL policy for direct reads, lists, metrics, search, favorites and collections."""

from fastapi import HTTPException
from sqlalchemy import and_, exists, false, or_, select

from app.core.errors import NotFoundError
from app.db.models import LearningObject, ObjectGrant


def grant_condition(actor, permissions):
    targets = [and_(ObjectGrant.grantee_type == "user", ObjectGrant.grantee_id == actor.subject)]
    if actor.group_ids:
        targets.append(
            and_(
                ObjectGrant.grantee_type == "group",
                ObjectGrant.grantee_id.in_([str(i) for i in actor.group_ids]),
            )
        )
    if actor.department_ids:
        targets.append(
            and_(
                ObjectGrant.grantee_type == "department",
                ObjectGrant.grantee_id.in_([str(i) for i in actor.department_ids]),
            )
        )
    return exists(
        select(ObjectGrant.lo_id).where(
            ObjectGrant.lo_id == LearningObject.id,
            or_(*targets),
            ObjectGrant.permission.in_(permissions),
        )
    )


def read_condition(actor):
    """Soft-deleted items are invisible to everyone. Archived items are visible to their
    owner and to admins only. Other users see an item through the audience or a grant."""
    if not actor.can("content.read"):
        return false()
    visible = LearningObject.deleted_at.is_(None)
    if actor.is_admin:
        return visible
    audience = or_(
        LearningObject.visibility == "repository",
        and_(
            LearningObject.visibility == "department",
            LearningObject.department_id.in_(actor.department_ids),
        ),
    )
    states = ["published"]
    if actor.can("workflow.review") or actor.can("workflow.approve"):
        states += ["submitted", "under_review"]
    if actor.can("workflow.publish"):
        states += ["approved"]
    return and_(
        visible,
        or_(
            LearningObject.created_by == actor.subject,
            and_(
                LearningObject.archived_at.is_(None),
                or_(
                    grant_condition(actor, {"read", "edit", "review", "publish", "manage"}),
                    and_(audience, LearningObject.status.in_(states)),
                ),
            ),
        ),
    )


def can_read(session, lo_id, actor):
    return (
        session.scalar(
            select(LearningObject.id).where(LearningObject.id == lo_id, read_condition(actor))
        )
        is not None
    )


def require_object(session, lo_id, actor, action="read"):
    if not can_read(session, lo_id, actor):
        raise NotFoundError("learning object not found")
    if action == "read":
        return
    capability = {
        "edit": "content.edit",
        "manage": "content.edit",
        "review": "workflow.review",
        "approve": "workflow.approve",
        "publish": "workflow.publish",
        "download": "content.download",
    }[action]
    if not actor.can(capability):
        raise HTTPException(403, f"Requires permission: {capability}")
    lo = session.get(LearningObject, lo_id)
    if actor.is_admin or action == "download":
        return
    if action in {"edit", "manage"} and lo.created_by == actor.subject:
        return
    if action in {"review", "approve", "publish"} and lo.visibility == "repository":
        return
    grant = "review" if action == "approve" else action
    if (
        session.scalar(
            select(LearningObject.id).where(
                LearningObject.id == lo_id, grant_condition(actor, {grant, "manage"})
            )
        )
        is not None
    ):
        return
    if (
        action in {"review", "approve", "publish"}
        and lo.visibility == "department"
        and lo.department_id in actor.department_ids
    ):
        return
    raise HTTPException(403, "Object access does not allow this operation")
