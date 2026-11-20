"""ORM models. Foreign keys and indexes: learning_objects.status, metadata_lom.lo_id,
xapi_statements.actor_id (FK to users, nullable because xAPI actors may be unknown learners)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

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
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_subject: Mapped[str] = mapped_column(String(255), index=True)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
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
