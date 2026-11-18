"""Metadata (IEEE LOM) updates. Metadata is editable only while the item is draft or rejected."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.security import Principal
from app.db.models import LearningObject, MetadataLOM
from app.schemas.lom import LOMMetadata
from app.services import audit

EDITABLE_STATES = {"draft", "rejected"}


def update_metadata(
    session: Session, lo_id: str, payload: LOMMetadata, actor: Principal
) -> MetadataLOM:
    lo = session.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    if lo.status not in EDITABLE_STATES:
        raise ConflictError(f"metadata cannot be edited while status is '{lo.status}'")

    meta = session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo_id))
    if meta is None:  # defensive: every LO gets a metadata row on creation
        meta = MetadataLOM(lo_id=lo_id, title=payload.title)
        session.add(meta)

    data = payload.model_dump()
    meta.title = data["title"]
    meta.description = data["description"]
    meta.language = data["language"]
    meta.keywords = data["keywords"]
    meta.subject = data["subject"]
    meta.learning_resource_type = data["learning_resource_type"]
    meta.license = data["license"]
    meta.rights_description = data["rights_description"]
    meta.duration = data["duration"]
    # Keep the full LOM document, including accessibility hints used by compliance checks.
    meta.lom_json = {**(meta.lom_json or {}), "lom": data}
    meta.updated_by = actor.subject
    meta.updated_at = datetime.now(UTC)
    lo.title = data["title"]

    audit.record(
        session,
        actor_subject=actor.subject,
        action="metadata.update",
        entity_type="learning_object",
        entity_id=lo_id,
        details={"fields": sorted(data.keys())},
    )
    session.commit()
    return meta
