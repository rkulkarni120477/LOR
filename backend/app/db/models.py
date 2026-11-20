"""ORM models. Foreign keys and indexes: learning_objects.status, metadata_lom.lo_id,
xapi_statements.actor_id (FK to users, nullable because xAPI actors may be unknown learners)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    actor_subject: Mapped[str] = mapped_column(String(255), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    answers: Mapped[list[int]] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PreviewTicket(Base):
    __tablename__ = "preview_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PackageActivity(Base):
    __tablename__ = "package_activity"
    __table_args__ = (
        UniqueConstraint("lo_id", "version_id", "subject", name="uq_package_activity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    roles_managed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user_roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )

    user: Mapped[User] = relationship(back_populates="user_roles")
    role: Mapped[Role] = relationship()


class LearningObject(Base):
    __tablename__ = "learning_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_by: Mapped[str] = mapped_column(String(255), index=True)
    visibility: Mapped[str] = mapped_column(
        String(16), default="repository", server_default="repository", index=True
    )
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    # Content kind: "file" (uploaded package), "rich_text", "quiz" or "assessment".
    kind: Mapped[str] = mapped_column(String(16), default="file", server_default="file")
    # Structured body for rich_text (sanitized HTML) and quiz/assessment (questions).
    body: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Optimistic-concurrency counter for autosave. Each accepted save increments it.
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Normalized plain text of title, description and body, for full-text matching.
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    versions: Mapped[list[Version]] = relationship(
        back_populates="learning_object",
        cascade="all, delete-orphan",
        order_by="Version.version_number",
    )
    metadata_record: Mapped[MetadataLOM | None] = relationship(
        back_populates="learning_object", uselist=False, cascade="all, delete-orphan"
    )


class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("lo_id", "version_number", name="uq_versions_lo_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # "clean" or "quarantined". Quarantined bytes are never served.
    scan_status: Mapped[str] = mapped_column(String(16), default="clean", server_default="clean")
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    package_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    thumbnail_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    learning_object: Mapped[LearningObject] = relationship(back_populates="versions")


class MetadataLOM(Base):
    """One row per learning object. Editable IEEE LOM fields are columns; the full LOM
    document is kept in lom_json so fields not modelled as columns are not lost."""

    __tablename__ = "metadata_lom"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    subject: Mapped[str | None] = mapped_column(String(255), index=True)
    learning_resource_type: Mapped[str | None] = mapped_column(String(100), index=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    license: Mapped[str | None] = mapped_column(String(255))
    rights_description: Mapped[str | None] = mapped_column(Text)
    duration: Mapped[str | None] = mapped_column(String(64))
    lom_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    updated_by: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    learning_object: Mapped[LearningObject] = relationship(back_populates="metadata_record")


class TaxonomyTerm(Base):
    __tablename__ = "taxonomy_terms"
    __table_args__ = (UniqueConstraint("scheme", "code", name="uq_taxonomy_scheme_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scheme: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("taxonomy_terms.id"))
    # active | deprecated (kept for existing items, not offered) | merged (points at merged_into_id)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    merged_into_id: Mapped[int | None] = mapped_column(
        ForeignKey("taxonomy_terms.id"), nullable=True
    )


class WorkflowState(Base):
    """Append-only history of workflow transitions for a learning object."""

    __tablename__ = "workflow_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32))
    actor_subject: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    actor_subject: Mapped[str] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class XapiStatement(Base):
    __tablename__ = "xapi_statements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_key: Mapped[str] = mapped_column(String(512), index=True)  # raw mbox or account id
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    verb_id: Mapped[str] = mapped_column(String(512), index=True)
    object_id: Mapped[str] = mapped_column(String(512), index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    statement: Mapped[dict[str, Any]] = mapped_column(JSON)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Collection(Base):
    """Collections nest through parent_id. Shares and publication apply to the whole subtree."""

    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    # "private" | "published". Published collections are readable by every repository user.
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True, nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionShare(Base):
    __tablename__ = "collection_shares"

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    grantee_type: Mapped[str] = mapped_column(String(16), primary_key=True)  # user|group|department
    grantee_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    permission: Mapped[str] = mapped_column(String(8))  # view|edit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionView(Base):
    """One row per view of a collection. Feeds analytics."""

    __tablename__ = "collection_views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    viewer_subject: Mapped[str] = mapped_column(String(255), index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class RecentAccess(Base):
    """Latest access per user and target. Kind is "collection" or "object"."""

    __tablename__ = "recent_access"

    owner_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class FavoriteCollection(Base):
    __tablename__ = "favorite_collections"

    owner_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FavoriteFolder(Base):
    """Explicit folders, so an empty folder can exist. Favorite folders also exist implicitly."""

    __tablename__ = "favorite_folders"

    owner_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[str] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class Favorite(Base):
    __tablename__ = "favorites"

    owner_subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), primary_key=True
    )
    folder: Mapped[str] = mapped_column(String(255), default="AI in Education")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Download(Base):
    __tablename__ = "downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    actor_subject: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SearchIndexJob(Base):
    """Transactional outbox: content commits never depend on broker availability."""

    __tablename__ = "search_index_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(String(36), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))


class GroupMember(Base):
    __tablename__ = "group_members"
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class GroupRole(Base):
    __tablename__ = "group_roles"
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class ObjectGrant(Base):
    __tablename__ = "object_grants"
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), primary_key=True
    )
    grantee_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    grantee_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    permission: Mapped[str] = mapped_column(String(16), primary_key=True)


class OIDCLogin(Base):
    __tablename__ = "oidc_logins"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    verifier: Mapped[str] = mapped_column(String(128))
    nonce: Mapped[str] = mapped_column(String(128))
    return_path: Mapped[str] = mapped_column(String(512), default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UploadSession(Base):
    """A resumable multipart upload. The object is assembled and processed on completion."""

    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    part_size: Mapped[int] = mapped_column(Integer)
    part_count: Mapped[int] = mapped_column(Integer)
    # "uploading" -> "completed" | "aborted". "uploaded" means all parts are in, not yet completed.
    status: Mapped[str] = mapped_column(String(16), default="uploading", index=True)
    backend_upload_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512))
    learning_object_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UploadPart(Base):
    __tablename__ = "upload_parts"

    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("upload_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    part_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ApprovalPolicy(Base):
    """A named sequence of approval stages. A case snapshots its policy when it is submitted."""

    __tablename__ = "approval_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyStage(Base):
    __tablename__ = "policy_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("approval_policies.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    # The permission a decider needs for this stage, e.g. workflow.approve.
    permission: Mapped[str] = mapped_column(String(64))
    # Parallel approval: this many distinct approvals move the stage on.
    approvals_required: Mapped[int] = mapped_column(Integer, default=1)
    # Named deciders. Empty means any holder of the permission may decide.
    assignees: Mapped[list[str]] = mapped_column(JSON, default=list)
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalation_role: Mapped[str] = mapped_column(String(64), default="Repository Administrator")


class ReviewCase(Base):
    """One submission round for a learning object. Changes and resubmissions open a new round."""

    __tablename__ = "review_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    round: Mapped[int] = mapped_column(Integer, default=1)
    # open | under_review | approved | changes_requested | rejected | withdrawn | superseded
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    policy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policy_name: Mapped[str] = mapped_column(String(120), default="Default")
    # Frozen copy of the stages at submission, so later policy edits do not move running cases.
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    stage_position: Mapped[int] = mapped_column(Integer, default=1)
    submitted_by: Mapped[str] = mapped_column(String(255), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The metadata snapshot this review approves. Publishing requires it to still be current.
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class StageTask(Base):
    __tablename__ = "stage_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("review_cases.id", ondelete="CASCADE"), index=True
    )
    stage_position: Mapped[int] = mapped_column(Integer)
    permission: Mapped[str] = mapped_column(String(64))
    # None means a pool task: any holder of the permission may decide it.
    assignee_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # open | approved | rejected | changes_requested | cancelled
    state: Mapped[str] = mapped_column(String(24), default="open", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    """In-app notification. Email for the same event is queued in email_outbox."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_subject: Mapped[str] = mapped_column(String(255), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    lo_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_email: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    # pending | sent | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Vocabulary(Base):
    """A controlled vocabulary. Terms belong to it through TaxonomyTerm.scheme == name.
    When locked, values for the LOM fields of the same name must be active terms."""

    __tablename__ = "vocabularies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetadataField(Base):
    """A custom metadata field, validated on every metadata save."""

    __tablename__ = "metadata_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    # text | number | date | boolean | select
    field_type: Mapped[str] = mapped_column(String(16))
    # For select fields: either an explicit option list or the name of a vocabulary.
    options: Mapped[list[str]] = mapped_column(JSON, default=list)
    vocabulary: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    help_text: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetadataSnapshot(Base):
    """Immutable record of an item's metadata and file at one point. Insert-only: the ORM refuses
    updates and deletes. Retention removes old rows through an audited bulk delete."""

    __tablename__ = "metadata_snapshots"
    __table_args__ = (UniqueConstraint("lo_id", "seq", name="uq_snapshot_lo_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    major: Mapped[int] = mapped_column(Integer)
    minor: Mapped[int] = mapped_column(Integer)
    # create | metadata | file | restore | promote
    kind: Mapped[str] = mapped_column(String(16))
    file_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VersionComment(Base):
    __tablename__ = "version_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    snapshot_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RetentionPolicy(Base):
    """Single row (id 1). Keeps the newest keep_last snapshots per item; majors can be kept too."""

    __tablename__ = "retention_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keep_last: Mapped[int] = mapped_column(Integer, default=50)
    keep_majors: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduledReport(Base):
    """A recurring report. The owner's roles, groups and department are captured when it is
    created, so each run sees only what the owner could see then."""

    __tablename__ = "scheduled_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    owner_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    owner_group_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    owner_department_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    name: Mapped[str] = mapped_column(String(120))
    report: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(8))
    window_days: Mapped[int] = mapped_column(Integer, default=30)
    cadence: Mapped[str] = mapped_column(String(8), default="weekly")
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )  # noqa: E501
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list)
    report: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str] = mapped_column(String(200))
    storage_key: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Webhook(Base):
    """Outbound event subscription. HMAC signing needs the secret itself, so it is stored in the
    database (restrict access to it) and returned once when the webhook is created."""

    __tablename__ = "webhooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    url: Mapped[str] = mapped_column(String(1024))
    events: Mapped[list[str]] = mapped_column(JSON, default=list)
    secret: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_id: Mapped[int] = mapped_column(
        ForeignKey("webhooks.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    # pending | delivered | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Branding(Base):
    """Single row (id 1). Shown on the sign-in page and in the header."""

    __tablename__ = "branding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_name: Mapped[str] = mapped_column(String(80), default="ELOR")
    tagline: Mapped[str] = mapped_column(
        String(160), default="Enterprise Learning Object Repository"
    )  # noqa: E501
    primary_color: Mapped[str] = mapped_column(String(7), default="#1762c4")
    logo_url: Mapped[str] = mapped_column(String(1024), default="")
    footer_text: Mapped[str] = mapped_column(String(300), default="")
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AISuggestion(Base):
    """A machine-drafted suggestion. It has no effect until a person accepts it."""

    __tablename__ = "ai_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lo_id: Mapped[str] = mapped_column(
        ForeignKey("learning_objects.id", ondelete="CASCADE"), index=True
    )
    # outline | objectives | summary | quiz | metadata | classification | accessibility
    kind: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    generator: Mapped[str] = mapped_column(String(32))
    # pending | accepted | rejected | applied-note (accepted, but not applicable to this item type)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(255))
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
