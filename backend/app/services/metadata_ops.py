"""Bulk metadata updates and CSV import. Every item goes through the same save path as the form, so
custom field rules, controlled vocabularies and the editable-state rule all apply. Each item is
committed on its own; one failure does not undo the others."""

from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, NotFoundError
from app.core.security import Principal
from app.db.models import MetadataField, MetadataLOM
from app.schemas.lom import LOMMetadata
from app.services import metadata as metadata_service
from app.services import taxonomy
from app.services.access import require_object


def _save(session: Session, actor: Principal, lo_id: str, lom: dict[str, Any]) -> None:
    payload = LOMMetadata.model_validate(lom)
    metadata_service.update_metadata(session, lo_id, payload, actor)


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(err["msg"] for err in exc.errors()[:3])
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return getattr(exc, "message", str(exc))


def apply_changes(lom: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    new = dict(lom)
    if changes.get("subject") is not None:
        new["subject"] = changes["subject"] or None
    if changes.get("learning_resource_type") is not None:
        new["learning_resource_type"] = changes["learning_resource_type"] or None
    keywords = list(new.get("keywords") or [])
    for word in changes.get("add_keywords") or []:
        if not any(k.lower() == word.lower() for k in keywords):
            keywords.append(word)
    removing = {w.lower() for w in changes.get("remove_keywords") or []}
    new["keywords"] = [k for k in keywords if k.lower() not in removing]
    custom = dict(new.get("custom") or {})
    for key, value in (changes.get("custom") or {}).items():
        if value is None:
            custom.pop(key, None)
        else:
            custom[key] = value
    new["custom"] = custom
    return new


def bulk_update(
    session: Session, actor: Principal, ids: list[str], changes: dict[str, Any]
) -> dict[str, Any]:
    results = []
    for lo_id in dict.fromkeys(ids):
        try:
            meta = session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo_id))
            if meta is None:
                raise NotFoundError("learning object not found")
            new = apply_changes(taxonomy.current_lom(meta), changes)
            _save(session, actor, lo_id, new)
            results.append({"id": lo_id, "ok": True})
        except (DomainError, HTTPException, ValidationError) as exc:
            session.rollback()
            results.append({"id": lo_id, "ok": False, "message": _describe(exc)})
    return {"results": results, "succeeded": sum(1 for r in results if r["ok"])}


def import_csv(session: Session, actor: Principal, text: str, dry_run: bool) -> dict[str, Any]:
    rows = taxonomy._csv(text)
    if not rows:
        raise NotFoundError("the file has no data rows")
    if "id" not in rows[0]:
        raise DomainError("the first column must be id")
    fields = {f.key: f for f in session.scalars(select(MetadataField))}
    # A wrong header is wrong for every row, so refuse the whole file up front.
    allowed = {"id", *taxonomy.LOM_COLUMNS, *(f"custom.{k}" for k in fields)}
    for column in rows[0]:
        if column not in allowed:
            raise DomainError(f"unknown column '{column}'")
    results = []
    for row in rows:
        lo_id = row.get("id", "")
        try:
            if not lo_id:
                raise NotFoundError("row has no id")
            meta = session.scalar(select(MetadataLOM).where(MetadataLOM.lo_id == lo_id))
            if meta is None:
                raise NotFoundError("learning object not found")
            base = taxonomy.current_lom(meta)
            new = taxonomy.row_to_lom(row, base, fields)
            if dry_run:
                require_object(session, lo_id, actor, "edit")
                LOMMetadata.model_validate(new)
                problems = taxonomy.validate_metadata(session, new)
                if problems:
                    raise DomainError("; ".join(problems[:5]))
                results.append({"id": lo_id, "ok": True, "dry_run": True})
            else:
                _save(session, actor, lo_id, new)
                results.append({"id": lo_id, "ok": True})
        except (DomainError, HTTPException, ValidationError) as exc:
            session.rollback()
            results.append({"id": lo_id, "ok": False, "message": _describe(exc)})
    return {
        "dry_run": dry_run,
        "rows": len(rows),
        "succeeded": sum(1 for r in results if r["ok"]),
        "results": results,
    }
