"""Metadata schema, controlled vocabularies, bulk and CSV metadata operations, quality scoring and
standards crosswalks. Business rules live in app.services.taxonomy and metadata_ops."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationFailure
from app.core.security import Principal, get_principal, require_permission
from app.db.models import LearningObject, MetadataField, MetadataLOM, TaxonomyTerm, Vocabulary
from app.db.session import get_db
from app.services import audit, metadata_ops, taxonomy
from app.services.access import can_read, read_condition

router = APIRouter(tags=["metadata and taxonomy"])
KEY = r"^[a-z][a-z0-9_]{1,63}$"


class FieldIn(BaseModel):
    key: str = Field(pattern=KEY)
    label: str = Field(min_length=1, max_length=120, pattern=r"\S")
    field_type: Literal["text", "number", "date", "boolean", "select"]
    options: list[str] = Field(default_factory=list, max_length=200)
    vocabulary: str | None = Field(default=None, max_length=64)
    required: bool = False
    help_text: str = Field(default="", max_length=500)

    @field_validator("options")
    @classmethod
    def _clean_options(cls, value: list[str]) -> list[str]:
        return [o.strip() for o in value if o.strip()]


class FieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"\S")
    required: bool | None = None
    active: bool | None = None
    options: list[str] | None = Field(default=None, max_length=200)
    vocabulary: str | None = Field(default=None, max_length=64)
    help_text: str | None = Field(default=None, max_length=500)


class VocabularyIn(BaseModel):
    name: str = Field(pattern=KEY)
    description: str = Field(default="", max_length=2000)
    locked: bool = False


class VocabularyUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    locked: bool | None = None


class TermIn(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    label: str = Field(min_length=1, max_length=255, pattern=r"\S")
    parent_code: str | None = Field(default=None, max_length=64)


class TermUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255, pattern=r"\S")
    status: Literal["active", "deprecated"] | None = None


class MergeIn(BaseModel):
    into_id: int


class ChangesIn(BaseModel):
    subject: str | None = Field(default=None, max_length=255)
    learning_resource_type: str | None = Field(default=None, max_length=100)
    add_keywords: list[str] = Field(default_factory=list, max_length=20)
    remove_keywords: list[str] = Field(default_factory=list, max_length=20)
    custom: dict[str, Any] = Field(default_factory=dict, max_length=20)


class BulkIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=200)
    changes: ChangesIn


class CsvIn(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    dry_run: bool = True


def _field_out(f: MetadataField) -> dict[str, Any]:
    return {
        "id": f.id,
        "key": f.key,
        "label": f.label,
        "field_type": f.field_type,
        "options": list(f.options or []),
        "vocabulary": f.vocabulary,
        "required": f.required,
        "active": f.active,
        "help_text": f.help_text,
    }


def _term_out(t: TaxonomyTerm) -> dict[str, Any]:
    return {
        "id": t.id,
        "code": t.code,
        "label": t.label,
        "status": t.status,
        "parent_id": t.parent_id,
        "merged_into_id": t.merged_into_id,
    }


def _csv_response(body: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


# --- schema --------------------------------------------------------------------------------


@router.get("/metadata/schema")
def schema(
    db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    fields = db.scalars(select(MetadataField).order_by(MetadataField.key)).all()
    return {
        "lom_fields": taxonomy.LOM_COLUMNS,
        "controlled_lom_fields": list(taxonomy.CONTROLLED_LOM_FIELDS),
        "custom_fields": [_field_out(f) for f in fields],
        "standards": [{"id": k, "name": v["name"]} for k, v in taxonomy.STANDARDS.items()],
    }


@router.post("/metadata/schema/fields", status_code=201)
def create_field(
    body: FieldIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
) -> dict[str, Any]:
    if body.key in taxonomy.LOM_COLUMNS or body.key in {"id", "status"}:
        raise ValidationFailure("that key is reserved for a standard field")
    if db.scalar(select(MetadataField.id).where(MetadataField.key == body.key)) is not None:
        raise ConflictError("a custom field with this key already exists")
    if body.field_type == "select" and not (body.options or body.vocabulary):
        raise ValidationFailure("a select field needs options or a vocabulary")
    if (
        body.vocabulary
        and db.scalar(select(Vocabulary.id).where(Vocabulary.name == body.vocabulary)) is None
    ):
        raise ValidationFailure("unknown vocabulary")
    row = MetadataField(**body.model_dump())
    db.add(row)
    audit.record(
        db,
        actor_subject=actor.subject,
        action="schema.field.create",
        entity_type="metadata_field",
        entity_id=body.key,
    )
    db.commit()
    return _field_out(row)


@router.put("/metadata/schema/fields/{field_id}")
def update_field(
    field_id: int,
    body: FieldUpdate,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
) -> dict[str, Any]:
    row = db.get(MetadataField, field_id)
    if row is None:
        raise NotFoundError("field not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    audit.record(
        db,
        actor_subject=actor.subject,
        action="schema.field.update",
        entity_type="metadata_field",
        entity_id=row.key,
        details=body.model_dump(exclude_unset=True),
    )
    db.commit()
    return _field_out(row)


# --- bulk, import, export ---------------------------------------------------------------------


@router.post("/metadata/bulk-update")
def bulk_update(
    body: BulkIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
) -> dict[str, Any]:
    return metadata_ops.bulk_update(db, actor, body.ids, body.changes.model_dump())


@router.post("/metadata/import")
def import_metadata(
    body: CsvIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
) -> dict[str, Any]:
    return metadata_ops.import_csv(db, actor, body.content, body.dry_run)


@router.get("/metadata/export")
def export_metadata(
    format: Literal["csv", "json"] = "csv",
    state: str | None = Query(None, max_length=32),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
):
    if format == "csv":
        return _csv_response(taxonomy.export_csv(db, actor, state), "metadata-export.csv")
    rows = db.execute(
        select(LearningObject, MetadataLOM)
        .join(MetadataLOM, MetadataLOM.lo_id == LearningObject.id)
        .where(read_condition(actor))
        .order_by(LearningObject.title)
    ).all()
    return {
        "items": [
            {"id": lo.id, "status": lo.status, **taxonomy.current_lom(meta)}
            for lo, meta in rows
            if state is None or lo.status == state
        ]
    }


# --- quality and standards ----------------------------------------------------------------


def _readable_meta(db: Session, lo_id: str, actor: Principal) -> MetadataLOM:
    if not can_read(db, lo_id, actor):
        raise NotFoundError("learning object not found")
    meta = db.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo_id))
    if meta is None:
        raise NotFoundError("no metadata for this item")
    return meta


@router.get("/metadata/{lo_id}/quality")
def item_quality(
    lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
) -> dict[str, Any]:
    meta = _readable_meta(db, lo_id, actor)
    return taxonomy.quality(db, taxonomy.current_lom(meta))


@router.get("/metadata/quality/summary")
def quality_summary(
    threshold: int = Query(60, ge=0, le=100),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    rows = db.execute(
        select(LearningObject, MetadataLOM)
        .join(MetadataLOM, MetadataLOM.lo_id == LearningObject.id)
        .where(read_condition(actor))
        .limit(2000)
    ).all()
    scored = []
    for lo, meta in rows:
        result = taxonomy.quality(db, taxonomy.current_lom(meta))
        scored.append(
            {
                "id": lo.id,
                "title": lo.title,
                "status": lo.status,
                "score": result["score"],
                "issues": result["issues"],
            }
        )
    average = round(sum(s["score"] for s in scored) / len(scored), 1) if scored else None
    return {
        "items": len(scored),
        "average_score": average,
        "below_threshold": sum(1 for s in scored if s["score"] < threshold),
        "threshold": threshold,
        "weakest": sorted(scored, key=lambda s: s["score"])[:10],
    }


@router.get("/metadata/{lo_id}/crosswalk")
def item_crosswalk(
    lo_id: str,
    standard: str = Query("dublin-core", max_length=64),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    meta = _readable_meta(db, lo_id, actor)
    return taxonomy.crosswalk(taxonomy.current_lom(meta), standard)


# --- vocabularies and terms ------------------------------------------------------------------


@router.get("/taxonomy/vocabularies")
def list_vocabularies(db: Session = Depends(get_db), actor: Principal = Depends(get_principal)):
    counts = dict(
        db.execute(
            select(TaxonomyTerm.scheme, func.count())
            .where(TaxonomyTerm.status == "active")
            .group_by(TaxonomyTerm.scheme)
        ).all()
    )
    rows = db.scalars(select(Vocabulary).order_by(Vocabulary.name)).all()
    return {
        "items": [
            {
                "id": v.id,
                "name": v.name,
                "description": v.description,
                "locked": v.locked,
                "active_terms": counts.get(v.name, 0),
            }
            for v in rows
        ]
    }


@router.post("/taxonomy/vocabularies", status_code=201)
def create_vocabulary(
    body: VocabularyIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
):
    if db.scalar(select(Vocabulary.id).where(Vocabulary.name == body.name)) is not None:
        raise ConflictError("a vocabulary with this name already exists")
    row = Vocabulary(name=body.name, description=body.description, locked=body.locked)
    db.add(row)
    audit.record(
        db,
        actor_subject=actor.subject,
        action="vocabulary.create",
        entity_type="vocabulary",
        entity_id=body.name,
    )
    db.commit()
    return {"name": row.name, "locked": row.locked}


@router.put("/taxonomy/vocabularies/{name}")
def update_vocabulary(
    name: str,
    body: VocabularyUpdate,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
):
    row = db.scalar(select(Vocabulary).where(Vocabulary.name == name))
    if row is None:
        raise NotFoundError("vocabulary not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    audit.record(
        db,
        actor_subject=actor.subject,
        action="vocabulary.update",
        entity_type="vocabulary",
        entity_id=name,
        details=body.model_dump(exclude_unset=True),
    )
    db.commit()
    return {"name": row.name, "locked": row.locked, "description": row.description}


@router.get("/taxonomy/vocabularies/{name}/terms")
def list_terms(
    name: str,
    status: str | None = Query(None, pattern="^(active|deprecated|merged)$"),
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
):
    query = select(TaxonomyTerm).where(TaxonomyTerm.scheme == name)
    if status:
        query = query.where(TaxonomyTerm.status == status)
    return {"items": [_term_out(t) for t in db.scalars(query.order_by(TaxonomyTerm.label))]}


@router.post("/taxonomy/vocabularies/{name}/terms", status_code=201)
def add_term(
    name: str,
    body: TermIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
):
    if db.scalar(select(Vocabulary.id).where(Vocabulary.name == name)) is None:
        raise NotFoundError("vocabulary not found")
    if (
        db.scalar(
            select(TaxonomyTerm.id).where(
                TaxonomyTerm.scheme == name, TaxonomyTerm.code == body.code
            )
        )
        is not None
    ):
        raise ConflictError("a term with this code already exists")
    parent_id = None
    if body.parent_code:
        parent = db.scalar(
            select(TaxonomyTerm).where(
                TaxonomyTerm.scheme == name, TaxonomyTerm.code == body.parent_code
            )
        )
        if parent is None:
            raise ValidationFailure("unknown parent code")
        parent_id = parent.id
    row = TaxonomyTerm(scheme=name, code=body.code, label=body.label, parent_id=parent_id)
    db.add(row)
    db.commit()
    return _term_out(row)


@router.put("/taxonomy/terms/{term_id}")
def update_term(
    term_id: int,
    body: TermUpdate,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
):
    row = db.get(TaxonomyTerm, term_id)
    if row is None:
        raise NotFoundError("term not found")
    if row.status == "merged":
        raise ConflictError("a merged term cannot be edited")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(row, key, value)
    audit.record(
        db,
        actor_subject=actor.subject,
        action="taxonomy.term.update",
        entity_type="taxonomy_term",
        entity_id=str(term_id),
        details=changes,
    )
    db.commit()
    return _term_out(row)


@router.post("/taxonomy/terms/{term_id}/merge")
def merge_term(
    term_id: int,
    body: MergeIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
):
    return taxonomy.merge_terms(db, actor, term_id, body.into_id)


@router.post("/taxonomy/vocabularies/{name}/import")
def import_terms(
    name: str,
    body: CsvIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("metadata.manage")),
):
    return taxonomy.import_vocabulary_csv(db, actor, name, body.content)


@router.get("/taxonomy/vocabularies/{name}/export")
def export_terms(
    name: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
):
    return _csv_response(taxonomy.export_vocabulary_csv(db, name), f"{name}-terms.csv")
