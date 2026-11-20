"""Analytics and reporting: reports, drill-downs, exports and scheduled reports. Rules live in
app.services.analytics, exporters and report_schedules."""

from datetime import date
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_storage
from app.core.errors import NotFoundError
from app.core.security import Principal, get_principal, require_permission
from app.db.models import ReportRun, ScheduledReport
from app.db.session import get_db
from app.services import analytics, exporters
from app.services import report_schedules as schedules
from app.storage.base import StorageBackend

router = APIRouter(prefix="/analytics", tags=["analytics and reporting"])
READ = require_permission("reports.read")


def _filters(
    start: date | None,
    end: date | None,
    subject: str | None,
    status: str | None,
    kind: str | None,
    department_id: int | None,
) -> analytics.Filters:
    return analytics.parse_filters(start, end, subject, status, kind, department_id)


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    report: Literal["usage", "reuse", "growth", "workflow", "storage", "departments"]
    format: Literal["csv", "xlsx", "pdf"] = "csv"
    window_days: int = Field(default=30, ge=1, le=3650)
    cadence: Literal["daily", "weekly"] = "weekly"
    recipients: list[str] = Field(default_factory=list, max_length=20)


class ScheduleUpdate(BaseModel):
    active: bool | None = None
    cadence: Literal["daily", "weekly"] | None = None
    recipients: list[str] | None = Field(default=None, max_length=20)


@router.get("/catalog")
def catalog(principal: Principal = Depends(READ)) -> dict[str, Any]:
    return {
        "reports": [{"key": k, "title": v} for k, v in analytics.REPORTS.items()],
        "formats": list(exporters.FORMATS),
        "drill_dimensions": sorted(analytics.DRILL_DIMENSIONS),
    }


# Schedules and runs are declared before the report route, so the paths never collide.


@router.get("/schedules")
def list_schedules(
    db: Session = Depends(get_db), principal: Principal = Depends(READ)
) -> dict[str, Any]:
    rows = db.scalars(
        select(ScheduledReport)
        .where(ScheduledReport.owner_subject == principal.subject)
        .order_by(ScheduledReport.name)
    ).all()
    return {"items": [schedules.describe(r) for r in rows]}


@router.post("/schedules", status_code=201)
def create_schedule(
    body: ScheduleIn, db: Session = Depends(get_db), principal: Principal = Depends(READ)
) -> dict[str, Any]:
    recipients = schedules.known_subjects(db, body.recipients) if body.recipients else []
    row = schedules.create(
        db,
        principal,
        name=body.name,
        report=body.report,
        fmt=body.format,
        window_days=body.window_days,
        cadence=body.cadence,
        recipients=recipients,
    )
    return schedules.describe(row)


@router.put("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(READ),
) -> dict[str, Any]:
    recipients = (
        schedules.known_subjects(db, body.recipients) if body.recipients is not None else None
    )
    row = schedules.update(
        db, principal, schedule_id, active=body.active, cadence=body.cadence, recipients=recipients
    )
    return schedules.describe(row)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: int, db: Session = Depends(get_db), principal: Principal = Depends(READ)
) -> dict[str, Any]:
    schedules.delete(db, principal, schedule_id)
    return {"deleted": True}


@router.post("/schedules/{schedule_id}/run")
def run_schedule_now(
    schedule_id: int,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(READ),
) -> dict[str, Any]:
    row = schedules.get_owned(db, principal, schedule_id)
    run = schedules.run(db, storage, row, advance=False)
    return {"run_id": run.id, "rows": run.row_count, "filename": run.filename}


@router.post("/schedules/run-due")
def run_due(
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(require_permission("organization.manage")),
) -> dict[str, int]:
    return schedules.run_due(db, storage)


@router.get("/runs")
def list_runs(
    db: Session = Depends(get_db), principal: Principal = Depends(get_principal)
) -> dict[str, Any]:
    rows = schedules.runs_visible_to(db, principal)
    return {
        "items": [
            {
                "id": r.id,
                "filename": r.filename,
                "report": r.report,
                "format": r.format,
                "rows": r.row_count,
                "size_bytes": r.size_bytes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/runs/{run_id}/download")
def download_run(
    run_id: int,
    db: Session = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
    principal: Principal = Depends(get_principal),
) -> Response:
    row: ReportRun = schedules.run_for_download(db, principal, run_id)
    try:
        with storage.open(row.storage_key) as stream:
            data = stream.read()
    except FileNotFoundError as exc:
        raise NotFoundError("report file not found") from exc
    return Response(
        content=data,
        media_type=exporters.FORMATS[row.format],
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


# --- reports --------------------------------------------------------------------------------------


@router.get("/reports/{name}")
def report(
    name: str,
    start: date | None = None,
    end: date | None = None,
    subject: str | None = Query(None, max_length=255),
    status: str | None = Query(None, max_length=32),
    kind: str | None = Query(None, max_length=32),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(READ),
) -> dict[str, Any]:
    f = _filters(start, end, subject, status, kind, department_id)
    return analytics.build(db, principal, name, f)


@router.get("/reports/{name}/export")
def export_report(
    name: str,
    format: Literal["csv", "xlsx", "pdf"] = "csv",
    start: date | None = None,
    end: date | None = None,
    subject: str | None = Query(None, max_length=255),
    status: str | None = Query(None, max_length=32),
    kind: str | None = Query(None, max_length=32),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(READ),
) -> Response:
    f = _filters(start, end, subject, status, kind, department_id)
    payload = analytics.build(db, principal, name, f)
    data = exporters.render(format, payload["title"], payload["columns"], payload["rows"])
    filename = f"{name}-report.{format}"
    return Response(
        content=data,
        media_type=exporters.FORMATS[format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/drill")
def drill(
    dimension: str = Query(..., max_length=32),
    value: str = Query("", max_length=255),
    start: date | None = None,
    end: date | None = None,
    subject: str | None = Query(None, max_length=255),
    status: str | None = Query(None, max_length=32),
    kind: str | None = Query(None, max_length=32),
    department_id: int | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(READ),
) -> dict[str, Any]:
    f = _filters(start, end, subject, status, kind, department_id)
    return {"items": analytics.drill(db, principal, dimension, value, f)}
