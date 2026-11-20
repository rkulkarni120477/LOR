"""Version management: immutable metadata snapshots, major and minor versions, version-specific
approvals, comparisons, comments, retention, and full restoration.

Versions
    1.0 is the first snapshot. A new file version or an explicit promotion starts a new major
    (2.0). A metadata change, a submission, or a restore is a minor change (1.1, 1.2, ...).

Immutability
    A snapshot is written once. The ORM refuses updates and deletes on it. Retention is the only
    thing that removes snapshots, and it uses a bulk delete that is audited.

Approvals
    A review records the snapshot it was submitted with. Publishing is refused if the item has
    changed since that snapshot.
"""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import (
    LearningObject,
    MetadataSnapshot,
    RetentionPolicy,
    ReviewCase,
    Version,
    VersionComment,
    WorkflowState,
)
from app.services import audit, taxonomy
from app.services.search_index import schedule_index

EDITABLE_STATES = {"draft", "rejected"}
MAJOR_KINDS = {"create", "file", "promote"}
COMPARED_TOP_LEVEL = ("title", "status", "file_version", "file_sha256")


def label(row: MetadataSnapshot) -> str:
    return f"{row.major}.{row.minor}"


def _digest(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@event.listens_for(MetadataSnapshot, "before_update")
def _refuse_update(mapper, connection, target):  # noqa: ANN001
    raise RuntimeError("metadata snapshots are immutable")


@event.listens_for(MetadataSnapshot, "before_delete")
def _refuse_delete(mapper, connection, target):  # noqa: ANN001
    raise RuntimeError("metadata snapshots are removed only by the retention job")


def _content(lo: LearningObject) -> dict[str, Any]:
    meta = lo.metadata_record
    lom = taxonomy.current_lom(meta) if meta is not None else {}
    numbers = [v.version_number for v in lo.versions]
    latest = max(lo.versions, key=lambda v: v.version_number, default=None)
    return {
        "title": lo.title,
        "status": lo.status,
        "lom": lom,
        "file_version": max(numbers) if numbers else None,
        "file_sha256": latest.sha256 if latest is not None else None,
        "body": lo.body,
        "kind": lo.kind,
    }


def latest(session: Session, lo_id: str) -> MetadataSnapshot | None:
    return session.scalar(
        select(MetadataSnapshot)
        .where(MetadataSnapshot.lo_id == lo_id)
        .order_by(MetadataSnapshot.seq.desc())
        .limit(1)
    )


def ensure_snapshot(
    session: Session, lo: LearningObject, actor: Principal, kind: str, comment: str | None = None
) -> MetadataSnapshot:
    """Records the item's current state. Unchanged content returns the latest snapshot, unless the
    caller asks for an explicit promotion."""
    content = _content(lo)
    digest = _digest(content)
    previous = latest(session, lo.id)
    if previous is not None and previous.digest == digest and kind not in {"promote"}:
        return previous
    if previous is None:
        major, minor, seq = 1, 0, 1
    else:
        seq = previous.seq + 1
        if kind in MAJOR_KINDS:
            major, minor = previous.major + 1, 0
        else:
            major, minor = previous.major, previous.minor + 1
    row = MetadataSnapshot(
        lo_id=lo.id,
        seq=seq,
        major=major,
        minor=minor,
        kind=kind,
        file_version=content["file_version"],
        content=content,
        digest=digest,
        comment=comment,
        created_by=actor.subject,
    )
    session.add(row)
    session.flush()
    return row


def get(session: Session, lo_id: str, seq: int) -> MetadataSnapshot:
    row = session.scalar(
        select(MetadataSnapshot).where(MetadataSnapshot.lo_id == lo_id, MetadataSnapshot.seq == seq)
    )
    if row is None:
        raise NotFoundError("snapshot not found")
    return row


def verified(row: MetadataSnapshot) -> bool:
    return _digest(row.content) == row.digest


def summary(row: MetadataSnapshot) -> dict[str, Any]:
    return {
        "seq": row.seq,
        "label": label(row),
        "kind": row.kind,
        "file_version": row.file_version,
        "comment": row.comment,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "intact": verified(row),
    }


def history(session: Session, lo_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(MetadataSnapshot)
        .where(MetadataSnapshot.lo_id == lo_id)
        .order_by(MetadataSnapshot.seq)
    ).all()
    return [summary(r) for r in rows]


def promote(
    session: Session, lo: LearningObject, actor: Principal, comment: str
) -> MetadataSnapshot:
    row = ensure_snapshot(session, lo, actor, "promote", comment)
    audit.record(
        session,
        actor_subject=actor.subject,
        action="version.promote",
        entity_type="learning_object",
        entity_id=lo.id,
        details={"label": label(row)},
    )
    session.commit()
    return row


# --- comparison --------------------------------------------------------------------------------


def compare(a: MetadataSnapshot, b: MetadataSnapshot) -> dict[str, Any]:
    changes = []
    for key in COMPARED_TOP_LEVEL:
        if a.content.get(key) != b.content.get(key):
            changes.append({"field": key, "from": a.content.get(key), "to": b.content.get(key)})
    lom_a = a.content.get("lom") or {}
    lom_b = b.content.get("lom") or {}
    for key in sorted(set(lom_a) | set(lom_b)):
        if key == "custom":
            continue
        if lom_a.get(key) != lom_b.get(key):
            changes.append({"field": key, "from": lom_a.get(key), "to": lom_b.get(key)})
    custom_a, custom_b = lom_a.get("custom") or {}, lom_b.get("custom") or {}
    for key in sorted(set(custom_a) | set(custom_b)):
        if custom_a.get(key) != custom_b.get(key):
            changes.append(
                {"field": f"custom.{key}", "from": custom_a.get(key), "to": custom_b.get(key)}
            )
    return {"from": label(a), "to": label(b), "changes": changes, "unchanged": not changes}


# --- comments ------------------------------------------------------------------------------------


def add_comment(
    session: Session, lo_id: str, actor: Principal, body: str, snapshot_seq: int | None
) -> VersionComment:
    if snapshot_seq is not None:
        get(session, lo_id, snapshot_seq)
    row = VersionComment(
        lo_id=lo_id,
        snapshot_seq=snapshot_seq,
        author=actor.subject,
        body=body,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    return row


def comments(session: Session, lo_id: str) -> list[VersionComment]:
    return list(
        session.scalars(
            select(VersionComment).where(VersionComment.lo_id == lo_id).order_by(VersionComment.id)
        )
    )


# --- retention ---------------------------------------------------------------------------------


def retention_policy(session: Session) -> RetentionPolicy:
    row = session.get(RetentionPolicy, 1)
    if row is None:
        row = RetentionPolicy(id=1, keep_last=50, keep_majors=True)
        session.add(row)
        session.flush()
    return row


def set_retention(
    session: Session, actor: Principal, keep_last: int, keep_majors: bool
) -> RetentionPolicy:
    if keep_last < 5:
        raise ValidationFailure("keep at least 5 snapshots per item")
    row = retention_policy(session)
    row.keep_last = keep_last
    row.keep_majors = keep_majors
    row.updated_by = actor.subject
    row.updated_at = datetime.now(UTC)
    audit.record(
        session,
        actor_subject=actor.subject,
        action="retention.update",
        entity_type="retention_policy",
        entity_id="1",
        details={"keep_last": keep_last, "keep_majors": keep_majors},
    )
    session.commit()
    return row


def apply_retention(session: Session, actor: Principal) -> dict[str, int]:
    """Removes snapshots beyond the policy. The newest snapshot, majors (when kept) and any
    snapshot an approval refers to are never removed."""
    policy = retention_policy(session)
    removed = 0
    kept_protected = 0
    for lo_id in session.scalars(select(MetadataSnapshot.lo_id).distinct()).all():
        rows = session.scalars(
            select(MetadataSnapshot)
            .where(MetadataSnapshot.lo_id == lo_id)
            .order_by(MetadataSnapshot.seq)
        ).all()
        if len(rows) <= policy.keep_last:
            continue
        referenced = set(
            session.scalars(
                select(ReviewCase.snapshot_id).where(
                    ReviewCase.lo_id == lo_id, ReviewCase.snapshot_id.isnot(None)
                )
            )
        )
        protected = {rows[-1].id} | {r.id for r in rows if r.id in referenced}
        if policy.keep_majors:
            protected |= {r.id for r in rows if r.kind in MAJOR_KINDS}
        newest = {r.id for r in rows[-policy.keep_last :]}
        doomed = [r.id for r in rows if r.id not in newest and r.id not in protected]
        kept_protected += len([r for r in rows if r.id not in newest and r.id in protected])
        if doomed:
            # Core delete on purpose: the ORM guard blocks deletes, retention is the one exception.
            session.execute(
                delete(MetadataSnapshot.__table__).where(
                    MetadataSnapshot.__table__.c.id.in_(doomed)
                )
            )
            removed += len(doomed)
    audit.record(
        session,
        actor_subject=actor.subject,
        action="retention.apply",
        entity_type="retention_policy",
        entity_id="1",
        details={"removed": removed, "protected": kept_protected},
    )
    session.commit()
    return {"removed": removed, "protected": kept_protected}


# --- full restoration ----------------------------------------------------------------------------


def restore(session: Session, actor: Principal, lo: LearningObject, seq: int) -> dict[str, Any]:
    """Restores metadata, custom values, keywords, title and the linked file version from a
    snapshot. Only draft or rejected items can be restored, as with file restores."""
    if lo.status not in EDITABLE_STATES:
        raise ConflictError(f"cannot restore while the item is '{lo.status}'")
    row = get(session, lo.id, seq)
    if not verified(row):
        raise ConflictError("this snapshot fails its integrity check and cannot be restored")
    content = row.content
    if "body" in content:
        import copy

        lo.body = copy.deepcopy(content["body"])
        lo.kind = content.get("kind", lo.kind)
        lo.revision += 1
    lom = dict(content.get("lom") or {})
    problems = taxonomy.validate_metadata(session, lom)
    if problems:
        raise ConflictError(
            "snapshot no longer fits the current schema: " + "; ".join(problems[:3])
        )
    meta = lo.metadata_record
    if meta is None:
        raise ConflictError("item has no metadata record")
    taxonomy._write_record(meta, lom)
    lo.title = content.get("title") or lo.title
    file_note = "metadata restored"
    target_version = content.get("file_version")
    current_numbers = {v.version_number for v in lo.versions}
    current_top = max(current_numbers) if current_numbers else None
    if target_version is not None and current_top is not None and target_version != current_top:
        source = next((v for v in lo.versions if v.version_number == target_version), None)
        if source is not None:
            lo.versions.append(
                Version(
                    version_number=current_top + 1,
                    storage_key=source.storage_key,
                    original_filename=source.original_filename,
                    content_type=source.content_type,
                    size_bytes=source.size_bytes,
                    sha256=source.sha256,
                    created_by=actor.subject,
                )
            )
            file_note = f"metadata and file version {target_version} restored"
    previous = lo.status
    lo.status = "draft"
    if previous != "draft":
        session.add(
            WorkflowState(
                lo_id=lo.id,
                from_state=previous,
                to_state="draft",
                actor_subject=actor.subject,
                comment=f"Restored snapshot {label(row)}",
            )
        )
    session.flush()
    new_row = ensure_snapshot(session, lo, actor, "restore", f"Restored {label(row)}")
    audit.record(
        session,
        actor_subject=actor.subject,
        action="version.restore_snapshot",
        entity_type="learning_object",
        entity_id=lo.id,
        details={"from": label(row), "to": label(new_row), "note": file_note},
    )
    schedule_index(session, lo.id)
    session.commit()
    return {"label": label(new_row), "note": file_note, "status": lo.status}
