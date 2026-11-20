"""Metadata and taxonomy: custom fields, controlled vocabularies, term status and merging, quality
scoring, standards crosswalks, and CSV import/export.

Metadata values live on the LOM record (lom_json["lom"]). Custom values sit under "custom". Every
metadata save is checked here, so the rules hold for forms, bulk updates and imports alike.
"""

import csv
import io
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import (
    LearningObject,
    MetadataField,
    MetadataLOM,
    TaxonomyTerm,
    Vocabulary,
)
from app.services import audit
from app.services.access import read_condition

FIELD_TYPES = {"text", "number", "date", "boolean", "select"}
CONTROLLED_LOM_FIELDS = ("subject", "learning_resource_type")
EDITABLE_STATES = {"draft", "rejected"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOM_COLUMNS = [
    "title",
    "description",
    "language",
    "subject",
    "learning_resource_type",
    "keywords",
    "license",
    "rights_description",
    "duration",
    "alt_text_provided",
    "captions_provided",
]
CSV_LIST_SEPARATOR = ";"


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == []


# --- custom fields -----------------------------------------------------------------


def active_fields(session: Session) -> list[MetadataField]:
    return list(
        session.scalars(
            select(MetadataField).where(MetadataField.active.is_(True)).order_by(MetadataField.key)
        )
    )


def vocabulary_labels(session: Session, name: str) -> set[str]:
    return set(
        session.scalars(
            select(TaxonomyTerm.label).where(
                TaxonomyTerm.scheme == name, TaxonomyTerm.status == "active"
            )
        )
    )


def _check_custom_value(session: Session, field: MetadataField, value: Any) -> str | None:
    kind = field.field_type
    if kind == "text":
        if not isinstance(value, str) or len(value) > 2000:
            return f"{field.label}: expected text up to 2000 characters"
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{field.label}: expected a number"
    elif kind == "date":
        if not isinstance(value, str) or not DATE_RE.match(value):
            return f"{field.label}: expected a date as YYYY-MM-DD"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return f"{field.label}: expected true or false"
    elif kind == "select":
        allowed = set(field.options or [])
        if field.vocabulary:
            allowed |= vocabulary_labels(session, field.vocabulary)
        if value not in allowed:
            return f"{field.label}: '{value}' is not an allowed value"
    return None


def validate_metadata(session: Session, data: dict[str, Any]) -> list[str]:
    """Returns human-readable problems with a metadata document. An empty list means valid."""
    errors: list[str] = []
    custom = data.get("custom") or {}
    fields = {f.key: f for f in session.scalars(select(MetadataField))}
    for key in custom:
        if key not in fields or not fields[key].active:
            errors.append(f"unknown custom field '{key}'")
    for field in active_fields(session):
        value = custom.get(field.key)
        if _empty(value):
            if field.required:
                errors.append(f"{field.label} is required")
            continue
        problem = _check_custom_value(session, field, value)
        if problem:
            errors.append(problem)
    for name in CONTROLLED_LOM_FIELDS:
        vocab = session.scalar(select(Vocabulary).where(Vocabulary.name == name))
        value = data.get(name)
        if vocab is not None and vocab.locked and not _empty(value):
            if value not in vocabulary_labels(session, name):
                errors.append(f"{name}: '{value}' is not in the controlled vocabulary")
    return errors


def controlled_ok(session: Session, data: dict[str, Any]) -> bool:
    for name in CONTROLLED_LOM_FIELDS:
        vocab = session.scalar(select(Vocabulary).where(Vocabulary.name == name))
        value = data.get(name)
        if vocab is not None and vocab.locked and not _empty(value):
            if value not in vocabulary_labels(session, name):
                return False
    return True


# --- quality scoring ----------------------------------------------------------------------


def quality(session: Session, data: dict[str, Any]) -> dict[str, Any]:
    custom = data.get("custom") or {}
    required_custom = [f for f in active_fields(session) if f.required]
    required_ok = all(not _empty(custom.get(f.key)) for f in required_custom)
    checks = [
        (
            "description",
            15,
            len((data.get("description") or "").strip()) >= 40,
            "Write a description of at least 40 characters",
        ),
        ("keywords", 10, len(data.get("keywords") or []) >= 3, "Add at least three keywords"),
        ("language", 5, bool(data.get("language")), "Set the language"),
        ("subject", 10, bool(data.get("subject")), "Set a subject"),
        (
            "learning_resource_type",
            10,
            bool(data.get("learning_resource_type")),
            "Set a learning resource type",
        ),
        ("license", 10, bool(data.get("license")), "Set a license"),
        ("duration", 5, bool(data.get("duration")), "Set a duration"),
        (
            "controlled_values",
            10,
            controlled_ok(session, data),
            "Use values from the controlled vocabularies",
        ),
        ("required_custom_fields", 10, required_ok, "Fill in the required custom fields"),
        (
            "alt_text",
            8,
            data.get("alt_text_provided") is True,
            "Confirm alternative text for images",
        ),
        ("captions", 7, data.get("captions_provided") is True, "Confirm captions for video"),
    ]
    total = sum(points for _, points, passed, _ in checks if passed)
    return {
        "score": total,
        "max": sum(points for _, points, _, _ in checks),
        "checks": [
            {"key": key, "points": points if passed else 0, "max": points, "passed": bool(passed)}
            for key, points, passed, _ in checks
        ],
        "issues": [hint for _, _, passed, hint in checks if not passed],
    }


# --- standards crosswalk ----------------------------------------------------------------

DUBLIN_CORE_MAP = {
    "title": "dc:title",
    "description": "dc:description",
    "language": "dc:language",
    "keywords": "dc:subject",
    "subject": "dc:subject",
    "learning_resource_type": "dc:type",
    "license": "dc:rights",
    "rights_description": "dc:rights",
    "duration": "dcterms:extent",
}
STANDARDS = {
    "dublin-core": {"name": "Dublin Core (simple and terms)", "map": DUBLIN_CORE_MAP},
}


def crosswalk(data: dict[str, Any], standard: str) -> dict[str, Any]:
    if standard not in STANDARDS:
        raise NotFoundError("unknown standard")
    mapping = STANDARDS[standard]["map"]
    mapped: dict[str, Any] = {}
    for lom_key, target in mapping.items():
        value = data.get(lom_key)
        if _empty(value):
            continue
        if target in mapped:
            existing = mapped[target]
            values = existing if isinstance(existing, list) else [existing]
            mapped[target] = values + (value if isinstance(value, list) else [value])
        else:
            mapped[target] = value
    unmapped = [k for k in (data.get("custom") or {})]
    return {"standard": standard, "mapped": mapped, "unmapped_custom_fields": unmapped}


# --- record access ------------------------------------------------------------------------


def current_lom(meta: MetadataLOM) -> dict[str, Any]:
    stored = dict((meta.lom_json or {}).get("lom") or {})
    base = {
        "title": meta.title,
        "description": meta.description or "",
        "language": meta.language,
        "keywords": list(meta.keywords or []),
        "subject": meta.subject,
        "learning_resource_type": meta.learning_resource_type,
        "license": meta.license,
        "rights_description": meta.rights_description,
        "duration": meta.duration,
    }
    for key, value in base.items():
        stored.setdefault(key, value)
    stored.setdefault("custom", {})
    return stored


def _write_record(meta: MetadataLOM, lom: dict[str, Any]) -> None:
    meta.lom_json = {**(meta.lom_json or {}), "lom": lom}
    meta.title = lom.get("title") or meta.title
    meta.description = lom.get("description")
    meta.language = lom.get("language")
    meta.keywords = list(lom.get("keywords") or [])
    meta.subject = lom.get("subject")
    meta.learning_resource_type = lom.get("learning_resource_type")
    meta.license = lom.get("license")
    meta.rights_description = lom.get("rights_description")
    meta.duration = lom.get("duration")


# --- merging ---------------------------------------------------------------------------------


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def merge_terms(session: Session, actor: Principal, from_id: int, into_id: int) -> dict[str, int]:
    """Folds one term into another. Items and child terms follow. Items in a non-editable state
    (submitted, approved, published) are counted as skipped, since their metadata is locked."""
    source = session.get(TaxonomyTerm, from_id)
    target = session.get(TaxonomyTerm, into_id)
    if source is None or target is None:
        raise NotFoundError("term not found")
    if source.id == target.id or source.scheme != target.scheme:
        raise ValidationFailure("terms must be different and in the same vocabulary")
    if target.status != "active":
        raise ValidationFailure("the target term must be active")
    updated = skipped = 0
    rows = session.execute(
        select(MetadataLOM, LearningObject).join(
            LearningObject, LearningObject.id == MetadataLOM.lo_id
        )
    ).all()
    for meta, lo in rows:
        lom = current_lom(meta)
        touched = False
        if _same(lom.get("subject"), source.label):
            lom["subject"] = target.label
            touched = True
        if _same(lom.get("learning_resource_type"), source.label):
            lom["learning_resource_type"] = target.label
            touched = True
        keywords = list(lom.get("keywords") or [])
        replaced = [target.label if _same(k, source.label) else k for k in keywords]
        if replaced != keywords:
            deduped = list(dict.fromkeys(replaced))
            lom["keywords"] = deduped
            touched = True
        custom = dict(lom.get("custom") or {})
        for field in session.scalars(
            select(MetadataField).where(MetadataField.vocabulary == source.scheme)
        ):
            if field.key in custom and _same(str(custom[field.key]), source.label):
                custom[field.key] = target.label
                touched = True
        lom["custom"] = custom
        if not touched:
            continue
        if lo.status not in EDITABLE_STATES:
            skipped += 1
            continue
        _write_record(meta, lom)
        updated += 1
    children = 0
    for child in session.scalars(select(TaxonomyTerm).where(TaxonomyTerm.parent_id == source.id)):
        child.parent_id = target.id
        children += 1
    source.status = "merged"
    source.merged_into_id = target.id
    audit.record(
        session,
        actor_subject=actor.subject,
        action="taxonomy.merge",
        entity_type="taxonomy_term",
        entity_id=str(source.id),
        details={
            "into": target.id,
            "items_updated": updated,
            "items_skipped": skipped,
            "children_moved": children,
        },
    )
    session.commit()
    return {"items_updated": updated, "items_skipped": skipped, "children_moved": children}


# --- CSV ------------------------------------------------------------------------------------


def _csv(text: str) -> list[dict[str, str]]:
    if len(text) > 2_000_000:
        raise ValidationFailure("the file is too large")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationFailure("the file has no header row")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "1"}:
        return True
    if lowered in {"false", "no", "0"}:
        return False
    return None


def row_to_lom(
    row: dict[str, str], base: dict[str, Any], fields: dict[str, MetadataField]
) -> dict[str, Any]:
    """Applies one CSV row to a current LOM document. Blank cells leave values unchanged."""
    lom = dict(base)
    custom = dict(lom.get("custom") or {})
    for column, raw in row.items():
        if column in ("id", ""):
            continue
        if column.startswith("custom."):
            key = column.removeprefix("custom.")
            if key not in fields:
                raise ValidationFailure(f"unknown custom column '{column}'")
            if raw != "":
                custom[key] = _coerce(fields[key], raw)
        elif column in LOM_COLUMNS:
            if raw == "":
                continue
            if column == "keywords":
                lom[column] = [k.strip() for k in raw.split(CSV_LIST_SEPARATOR) if k.strip()]
            elif column in ("alt_text_provided", "captions_provided"):
                lom[column] = _bool(raw)
            else:
                lom[column] = raw
        else:
            raise ValidationFailure(f"unknown column '{column}'")
    lom["custom"] = custom
    return lom


def _coerce(field: MetadataField, raw: str) -> Any:
    if field.field_type == "number":
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError as exc:
            raise ValidationFailure(f"{field.label}: '{raw}' is not a number") from exc
    if field.field_type == "boolean":
        value = _bool(raw)
        if value is None:
            raise ValidationFailure(f"{field.label}: expected true or false")
        return value
    return raw


def export_csv(session: Session, actor: Principal, state: str | None = None) -> str:
    fields = active_fields(session)
    header = ["id", "status", *LOM_COLUMNS, *[f"custom.{f.key}" for f in fields]]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    query = select(LearningObject, MetadataLOM).join(
        MetadataLOM, MetadataLOM.lo_id == LearningObject.id
    )
    query = query.where(read_condition(actor))
    if state:
        query = query.where(LearningObject.status == state)
    for lo, meta in session.execute(query.order_by(LearningObject.title)).all():
        lom = current_lom(meta)
        values = []
        for column in LOM_COLUMNS:
            value = lom.get(column)
            if column == "keywords":
                value = CSV_LIST_SEPARATOR.join(value or [])
            elif isinstance(value, bool):
                value = "true" if value else "false"
            values.append("" if value is None else value)
        custom = lom.get("custom") or {}
        writer.writerow([lo.id, lo.status, *values, *[custom.get(f.key, "") for f in fields]])
    return out.getvalue()


def import_vocabulary_csv(
    session: Session, actor: Principal, name: str, text: str
) -> dict[str, int]:
    vocab = session.scalar(select(Vocabulary).where(Vocabulary.name == name))
    if vocab is None:
        raise NotFoundError("vocabulary not found")
    rows = _csv(text)
    created = updated = 0
    by_code: dict[str, TaxonomyTerm] = {}
    for row in rows:
        code, label = row.get("code", ""), row.get("label", "")
        if not code or not label:
            raise ValidationFailure("every row needs a code and a label")
        term = session.scalar(
            select(TaxonomyTerm).where(TaxonomyTerm.scheme == name, TaxonomyTerm.code == code)
        )
        if term is None:
            term = TaxonomyTerm(scheme=name, code=code, label=label)
            session.add(term)
            created += 1
        else:
            term.label = label
            updated += 1
        by_code[code] = term
    session.flush()
    for row in rows:
        parent_code = row.get("parent_code", "")
        if parent_code:
            parent = by_code.get(parent_code) or session.scalar(
                select(TaxonomyTerm).where(
                    TaxonomyTerm.scheme == name, TaxonomyTerm.code == parent_code
                )
            )
            if parent is None:
                raise ValidationFailure(f"unknown parent code '{parent_code}'")
            by_code[row["code"]].parent_id = parent.id
    audit.record(
        session,
        actor_subject=actor.subject,
        action="taxonomy.import",
        entity_type="vocabulary",
        entity_id=name,
        details={"created": created, "updated": updated},
    )
    session.commit()
    return {"created": created, "updated": updated}


def export_vocabulary_csv(session: Session, name: str) -> str:
    if session.scalar(select(Vocabulary.id).where(Vocabulary.name == name)) is None:
        raise NotFoundError("vocabulary not found")
    terms = session.scalars(
        select(TaxonomyTerm).where(TaxonomyTerm.scheme == name).order_by(TaxonomyTerm.code)
    ).all()
    codes = {t.id: t.code for t in terms}
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["code", "label", "parent_code", "status"])
    for t in terms:
        writer.writerow([t.code, t.label, codes.get(t.parent_id, ""), t.status])
    return out.getvalue()
