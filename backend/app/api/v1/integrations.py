"""Administration and integrations: webhooks, deliveries, branding and an admin overview, plus
content interoperability bundles and AI-assisted authoring suggestions."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import (
    AISuggestion,
    ApprovalPolicy,
    Department,
    Group,
    LearningObject,
    User,
    Webhook,
    WebhookDelivery,
)
from app.db.session import get_db
from app.services import ai_authoring, integrations, interop
from app.services.access import require_object
from app.storage.base import StorageBackend

router = APIRouter(tags=["administration and integrations"])
MANAGE = Depends(require_permission("organization.manage"))


class WebhookIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    url: str = Field(min_length=8, max_length=1024)
    events: list[str] = Field(min_length=1, max_length=40)

    @field_validator("events")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return [e.strip()[:64] for e in value if e.strip()]


class WebhookUpdate(BaseModel):
    active: bool | None = None
    events: list[str] | None = Field(default=None, max_length=40)


class BrandingIn(BaseModel):
    app_name: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"\S")
    tagline: str | None = Field(default=None, max_length=160)
    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: str | None = Field(default=None, max_length=1024)
    footer_text: str | None = Field(default=None, max_length=300)

    @field_validator("logo_url")
    @classmethod
    def _https_logo(cls, value: str | None) -> str | None:
        if value and not value.startswith("https://"):
            raise ValueError("the logo must be an https URL")
        return value


class SuggestIn(BaseModel):
    kinds: list[
        Literal[
            "outline",
            "objectives",
            "summary",
            "quiz",
            "metadata",
            "classification",
            "accessibility",
        ]
    ] = Field(min_length=1, max_length=7)


class PayloadIn(BaseModel):
    payload: dict[str, Any]


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


def _suggestion(row: AISuggestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "lo_id": row.lo_id,
        "kind": row.kind,
        "payload": row.payload,
        "generator": row.generator,
        "status": row.status,
        "requested_by": row.requested_by,
        "decided_by": row.decided_by,
        "decision_note": row.decision_note,
        "edited": row.edited,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# --- overview ----------------------------------------------------------------------------------


@router.get("/admin/overview")
def overview(db: Session = Depends(get_db), actor: Principal = MANAGE) -> dict[str, Any]:
    def count(model) -> int:  # noqa: ANN001
        return db.scalar(select(func.count()).select_from(model)) or 0

    return {
        "users": count(User),
        "groups": count(Group),
        "departments": count(Department),
        "policies": count(ApprovalPolicy),
        "webhooks": count(Webhook),
        "items": count(LearningObject),
        "pending_webhook_deliveries": db.scalar(
            select(func.count())
            .select_from(WebhookDelivery)
            .where(WebhookDelivery.status == "pending")
        )
        or 0,
        "pending_ai_suggestions": db.scalar(
            select(func.count()).select_from(AISuggestion).where(AISuggestion.status == "pending")
        )
        or 0,
    }


# --- branding -------------------------------------------------------------------------------------


@router.get("/branding")
def get_branding(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Public: the sign-in page needs it before anyone is signed in."""
    row = integrations.branding(db)
    db.commit()
    return {
        "app_name": row.app_name,
        "tagline": row.tagline,
        "primary_color": row.primary_color,
        "logo_url": row.logo_url,
        "footer_text": row.footer_text,
    }


@router.put("/branding")
def put_branding(
    body: BrandingIn, db: Session = Depends(get_db), actor: Principal = MANAGE
) -> dict[str, Any]:
    row = integrations.set_branding(db, actor, **body.model_dump(exclude_unset=True))
    return {
        "app_name": row.app_name,
        "tagline": row.tagline,
        "primary_color": row.primary_color,
        "logo_url": row.logo_url,
        "footer_text": row.footer_text,
    }


# --- webhooks -------------------------------------------------------------------------------------


@router.get("/integrations/webhooks")
def list_webhooks(db: Session = Depends(get_db), actor: Principal = MANAGE) -> dict[str, Any]:
    rows = db.scalars(select(Webhook).order_by(Webhook.name)).all()
    return {"items": [integrations.describe(r) for r in rows]}


@router.post("/integrations/webhooks", status_code=201)
def create_webhook(
    body: WebhookIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: Principal = MANAGE,
) -> dict[str, Any]:
    row, secret = integrations.create(
        db, actor, settings, name=body.name, url=body.url, events=body.events
    )
    # The signing secret is returned once. It cannot be read back later.
    return {**integrations.describe(row), "secret": secret}


@router.put("/integrations/webhooks/{webhook_id}")
def update_webhook(
    webhook_id: int, body: WebhookUpdate, db: Session = Depends(get_db), actor: Principal = MANAGE
) -> dict[str, Any]:
    row = integrations.get(db, webhook_id)
    changes = body.model_dump(exclude_unset=True)
    if "active" in changes and changes["active"] is not None:
        row.active = changes["active"]
    if changes.get("events"):
        row.events = sorted(set(changes["events"]))
    db.commit()
    return integrations.describe(row)


@router.delete("/integrations/webhooks/{webhook_id}")
def delete_webhook(
    webhook_id: int, db: Session = Depends(get_db), actor: Principal = MANAGE
) -> dict[str, Any]:
    row = integrations.get(db, webhook_id)
    db.delete(row)
    db.commit()
    return {"deleted": True}


@router.post("/integrations/webhooks/{webhook_id}/test")
def test_webhook(
    webhook_id: int, db: Session = Depends(get_db), actor: Principal = MANAGE
) -> dict[str, bool]:
    row = integrations.get(db, webhook_id)
    integrations.test_event(db, row, actor)
    return {"queued": True}


@router.get("/integrations/deliveries")
def list_deliveries(
    webhook_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    actor: Principal = MANAGE,
) -> dict[str, Any]:
    query = select(WebhookDelivery).order_by(WebhookDelivery.id.desc()).limit(200)
    if webhook_id is not None:
        query = query.where(WebhookDelivery.webhook_id == webhook_id)
    if status:
        query = query.where(WebhookDelivery.status == status)
    rows = db.scalars(query).all()
    return {
        "items": [
            {
                "id": r.id,
                "webhook_id": r.webhook_id,
                "event": r.event,
                "status": r.status,
                "attempts": r.attempts,
                "response_code": r.response_code,
                "last_error": r.last_error,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/integrations/deliveries/dispatch")
def dispatch(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: Principal = MANAGE,
) -> dict[str, Any]:
    return integrations.dispatch(db, settings)


# --- content interoperability -----------------------------------------------------------------------  # noqa: E501


@router.get("/interop/{lo_id}/bundle")
def export_bundle(
    lo_id: str,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    actor: Principal = Depends(get_principal),
) -> Response:
    require_object(db, lo_id, actor, "download")
    lo = db.get(LearningObject, lo_id)
    if lo is None:
        raise NotFoundError("learning object not found")
    data, filename = interop.export_bundle(db, storage, lo)
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/interop/{lo_id}/xapi-activity")
def xapi_activity(
    lo_id: str, db: Session = Depends(get_db), actor: Principal = Depends(get_principal)
):
    require_object(db, lo_id, actor, "read")
    return interop.xapi_activity(db, lo_id)


@router.post("/interop/import", status_code=201)
async def import_bundle(
    bundle: UploadFile = File(...),
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    actor: Principal = Depends(require_permission("content.create")),
) -> dict[str, Any]:
    data = await bundle.read(settings.max_upload_bytes + 1)
    lo, warnings = interop.import_bundle(db, storage, settings, actor, data)
    return {"id": lo.id, "title": lo.title, "status": lo.status, "warnings": warnings}


# --- AI-assisted authoring ----------------------------------------------------------------------------  # noqa: E501


@router.post("/ai/{lo_id}/suggestions", status_code=201)
def request_suggestions(
    lo_id: str,
    body: SuggestIn,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    rows = ai_authoring.request_suggestions(db, storage, settings, actor, lo_id, list(body.kinds))
    return {"items": [_suggestion(r) for r in rows]}


@router.get("/ai/{lo_id}/suggestions")
def list_suggestions(
    lo_id: str,
    status: str | None = None,
    db: Session = Depends(get_db),
    actor: Principal = Depends(get_principal),
) -> dict[str, Any]:
    require_object(db, lo_id, actor, "read")
    query = select(AISuggestion).where(AISuggestion.lo_id == lo_id).order_by(AISuggestion.id)
    if status:
        query = query.where(AISuggestion.status == status)
    return {"items": [_suggestion(r) for r in db.scalars(query).all()]}


@router.put("/ai/suggestions/{suggestion_id}")
def edit_suggestion(
    suggestion_id: int,
    body: PayloadIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _suggestion(ai_authoring.edit(db, actor, suggestion_id, body.payload))


@router.post("/ai/suggestions/{suggestion_id}/accept")
def accept_suggestion(
    suggestion_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _suggestion(ai_authoring.decide(db, actor, suggestion_id, "accept", body.note))


@router.post("/ai/suggestions/{suggestion_id}/reject")
def reject_suggestion(
    suggestion_id: int,
    body: DecisionIn,
    db: Session = Depends(get_db),
    actor: Principal = Depends(require_permission("content.edit")),
) -> dict[str, Any]:
    return _suggestion(ai_authoring.decide(db, actor, suggestion_id, "reject", body.note))
