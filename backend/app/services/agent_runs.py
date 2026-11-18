"""Connects agent results to the database. Agents never write the learning object's status."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import Principal
from app.db.models import MetadataLOM
from app.services import audit
from app.services.content import get_learning_object
from app.services.metadata import EDITABLE_STATES

_FILLABLE = (
    "description",
    "language",
    "subject",
    "learning_resource_type",
    "license",
)


def load_package_key(session: Session, lo_id: str, actor: Principal) -> str:
    """Return the storage key of the latest package version for ingest."""
    lo = get_learning_object(session, lo_id, actor)
    if not lo.versions:
        raise ValueError("learning object has no package version")
    if lo.status not in EDITABLE_STATES:
        from app.core.errors import ConflictError

        raise ConflictError(f"ingest is not allowed while status is '{lo.status}'")
    return lo.versions[-1].storage_key


def apply_draft_metadata(session: Session, lo_id: str, state: dict, actor: Principal) -> None:
    """Fill EMPTY metadata fields with agent drafts. Human-entered values are never overwritten."""
    extracted = state.get("extracted_metadata") or {}
    meta = session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo_id))
    if meta is None:
        return
    for field in _FILLABLE:
        if not getattr(meta, field) and extracted.get(field):
            setattr(meta, field, extracted[field])
    if not meta.keywords and extracted.get("keywords"):
        meta.keywords = list(extracted["keywords"])
    meta.extraction_confidence = extracted.get("confidence")
    meta.lom_json = {
        **(meta.lom_json or {}),
        "agent_draft": {
            "compliance_score": state.get("compliance_score"),
            "compliance_issues": state.get("compliance_issues", []),
            "taxonomy_tags": state.get("taxonomy_tags", []),
        },
    }
    audit.record(
        session,
        actor_subject=actor.subject,
        action="agent.ingest_draft",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"compliance_score": state.get("compliance_score")},
    )
    session.commit()
