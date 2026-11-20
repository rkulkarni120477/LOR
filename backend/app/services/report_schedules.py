"""Scheduled reports. A run builds the report as the owner could see it when the schedule was
created, renders it, stores the file, and tells the owner and recipients where to find it."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import ReportRun, ScheduledReport, User
from app.services import analytics, audit, exporters
from app.services import notifications as notify_service
from app.storage.base import StorageBackend

CADENCE_DAYS = {"daily": 1, "weekly": 7}
MAX_RECIPIENTS = 20


def _now() -> datetime:
    return datetime.now(UTC)


def _owner(row: ScheduledReport) -> Principal:
    return Principal(
        subject=row.owner_subject,
        roles=frozenset(row.owner_roles or []),
        group_ids=frozenset(row.owner_group_ids or []),
        department_ids=frozenset(row.owner_department_ids or []),
    )


def _validate(report: str, fmt: str, cadence: str, recipients: list[str]) -> None:
    if report not in analytics.REPORTS:
        raise ValidationFailure("unknown report")
    if fmt not in exporters.FORMATS:
        raise ValidationFailure("format must be csv, xlsx or pdf")
    if cadence not in CADENCE_DAYS:
        raise ValidationFailure("cadence must be daily or weekly")
    if len(recipients) > MAX_RECIPIENTS:
        raise ValidationFailure(f"at most {MAX_RECIPIENTS} recipients")


def create(
    session: Session,
    actor: Principal,
    *,
    name: str,
    report: str,
    fmt: str,
    window_days: int,
    cadence: str,
    recipients: list[str],
) -> ScheduledReport:
    _validate(report, fmt, cadence, recipients)
    row = ScheduledReport(
        owner_subject=actor.subject,
        owner_roles=sorted(actor.roles),
        owner_group_ids=sorted(actor.group_ids),
        owner_department_ids=sorted(actor.department_ids),
        name=name.strip(),
        report=report,
        format=fmt,
        window_days=window_days,
        cadence=cadence,
        recipients=list(dict.fromkeys(recipients)),
        active=True,
        next_run_at=_now() + timedelta(days=CADENCE_DAYS[cadence]),
    )
    session.add(row)
    audit.record(
        session,
        actor_subject=actor.subject,
        action="schedule.create",
        entity_type="scheduled_report",
        entity_id=row.name,
        details={"report": report, "format": fmt},
    )
    session.commit()
    return row


def get_owned(session: Session, actor: Principal, schedule_id: int) -> ScheduledReport:
    row = session.get(ScheduledReport, schedule_id)
    if row is None or row.owner_subject != actor.subject:
        raise NotFoundError("schedule not found")
    return row


def update(
    session: Session,
    actor: Principal,
    schedule_id: int,
    *,
    active: bool | None,
    cadence: str | None,
    recipients: list[str] | None,
) -> ScheduledReport:
    row = get_owned(session, actor, schedule_id)
    if cadence is not None:
        _validate(
            row.report,
            row.format,
            cadence,
            recipients if recipients is not None else row.recipients,
        )
        row.cadence = cadence
    if recipients is not None:
        _validate(row.report, row.format, row.cadence, recipients)
        row.recipients = list(dict.fromkeys(recipients))
    if active is not None:
        row.active = active
        if active and row.next_run_at is None:
            row.next_run_at = _now() + timedelta(days=CADENCE_DAYS[row.cadence])
    session.commit()
    return row


def delete(session: Session, actor: Principal, schedule_id: int) -> None:
    row = get_owned(session, actor, schedule_id)
    session.delete(row)
    session.commit()


def run(
    session: Session,
    storage: StorageBackend,
    row: ScheduledReport,
    *,
    advance: bool,
    actor_label: str | None = None,
) -> ReportRun:
    owner = _owner(row)
    now = _now()
    end = now.replace(tzinfo=None)
    start = end - timedelta(days=row.window_days)
    f = analytics.Filters(start=start, end=end + timedelta(seconds=1))
    payload = analytics.build(session, owner, row.report, f)
    data = exporters.render(row.format, payload["title"], payload["columns"], payload["rows"])
    stamp = now.strftime("%Y%m%d-%H%M")
    filename = f"{row.report}-{stamp}.{row.format}"
    report_run = ReportRun(
        schedule_id=row.id,
        owner_subject=row.owner_subject,
        recipients=list(row.recipients or []),
        report=row.report,
        format=row.format,
        filename=filename,
        storage_key="",
        size_bytes=len(data),
        row_count=payload["row_count"],
    )
    session.add(report_run)
    session.flush()
    report_run.storage_key = f"reports/{report_run.id}.{row.format}"
    storage.save(report_run.storage_key, data)
    row.last_run_at = now
    if advance:
        row.next_run_at = now + timedelta(days=CADENCE_DAYS[row.cadence])
    recipients = list(dict.fromkeys([row.owner_subject, *row.recipients]))
    notify_service.notify(
        session,
        recipients,
        kind="report_ready",
        title=f"Report ready: {row.name}",
        body=f"{payload['title']} for the last {row.window_days} days is ready ({filename}). "
        f"Download it from Reports → Scheduled reports.",
    )
    audit.record(
        session,
        actor_subject=actor_label or row.owner_subject,
        action="schedule.run",
        entity_type="scheduled_report",
        entity_id=str(row.id),
        details={"run": report_run.id, "rows": payload["row_count"]},
    )
    session.commit()
    return report_run


def run_due(session: Session, storage: StorageBackend) -> dict[str, int]:
    now = _now().replace(tzinfo=None)
    due = session.scalars(
        select(ScheduledReport).where(
            ScheduledReport.active.is_(True), ScheduledReport.next_run_at.isnot(None)
        )
    ).all()
    ran = failed = 0
    for row in due:
        due_at = row.next_run_at.replace(tzinfo=None) if row.next_run_at.tzinfo else row.next_run_at
        if due_at > now:
            continue
        try:
            run(session, storage, row, advance=True, actor_label="scheduler")
            ran += 1
        except Exception:  # one broken schedule must not stop the others
            session.rollback()
            failed += 1
    return {"ran": ran, "failed": failed}


def runs_visible_to(session: Session, actor: Principal) -> list[ReportRun]:
    rows = session.scalars(select(ReportRun).order_by(ReportRun.id.desc()).limit(200)).all()
    return [
        r for r in rows if r.owner_subject == actor.subject or actor.subject in (r.recipients or [])
    ]


def run_for_download(session: Session, actor: Principal, run_id: int) -> ReportRun:
    row = session.get(ReportRun, run_id)
    if row is None or (
        row.owner_subject != actor.subject and actor.subject not in (row.recipients or [])
    ):
        raise NotFoundError("report run not found")
    return row


def known_subjects(session: Session, subjects: list[str]) -> list[str]:
    """Recipients must be known people. Unknown subjects are reported, not dropped."""
    known = set(session.scalars(select(User.subject).where(User.subject.in_(subjects))))
    missing = [s for s in subjects if s not in known]
    if missing:
        raise ValidationFailure("unknown recipients: " + ", ".join(missing[:5]))
    return subjects


def describe(row: ScheduledReport) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "report": row.report,
        "format": row.format,
        "window_days": row.window_days,
        "cadence": row.cadence,
        "recipients": list(row.recipients or []),
        "active": row.active,
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
    }
