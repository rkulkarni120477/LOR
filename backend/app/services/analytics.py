"""Analytics and reporting: usage, reuse, growth, workflow, storage and department reports, with
filters, chart series and drill-downs.

Every metric is scoped to the objects the requesting user can read (read_condition), so counts
never reveal items the user cannot see. Timestamps are stored as naive UTC; date filters are
converted the same way.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailure
from app.core.security import Principal
from app.db.models import (
    AuditLog,
    CollectionItem,
    CollectionView,
    Department,
    Download,
    Favorite,
    LearningObject,
    MetadataLOM,
    ReviewCase,
    StageTask,
    Version,
    WorkflowState,
    XapiStatement,
)
from app.services.access import read_condition

REPORTS = {
    "usage": "Usage",
    "reuse": "Reuse",
    "growth": "Growth",
    "workflow": "Workflow",
    "storage": "Storage",
    "departments": "Departments",
}
DRILL_DIMENSIONS = {"day", "month", "subject", "kind", "status", "department"}
MAX_ROWS = 500


@dataclass(frozen=True)
class Filters:
    start: datetime | None = None
    end: datetime | None = None
    subject: str | None = None
    status: str | None = None
    kind: str | None = None
    department_id: int | None = None


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def parse_filters(
    start: date | None,
    end: date | None,
    subject: str | None,
    status: str | None,
    kind: str | None,
    department_id: int | None,
) -> Filters:
    if start and end and start > end:
        raise ValidationFailure("the start date is after the end date")
    if end and (end - (start or end)).days > 3650:
        raise ValidationFailure("the range is limited to ten years")
    return Filters(
        start=datetime.combine(start, time.min) if start else None,
        end=datetime.combine(end + timedelta(days=1), time.min) if end else None,
        subject=subject or None,
        status=status or None,
        kind=kind or None,
        department_id=department_id,
    )


def _in_range(column, f: Filters):
    clauses = []
    if f.start is not None:
        clauses.append(column >= f.start)
    if f.end is not None:
        clauses.append(column < f.end)
    return and_(*clauses) if clauses else True


def scope(session: Session, actor: Principal, f: Filters):
    """Learning-object ids in scope: readable by the actor and matching the filters."""
    query = select(LearningObject.id).where(read_condition(actor))
    if f.status:
        query = query.where(LearningObject.status == f.status)
    if f.kind:
        query = query.where(LearningObject.kind == f.kind)
    if f.department_id is not None:
        query = query.where(LearningObject.department_id == f.department_id)
    if f.subject:
        query = query.join(MetadataLOM, MetadataLOM.lo_id == LearningObject.id).where(
            MetadataLOM.subject == f.subject
        )
    return query


def _day(value: datetime | None) -> str | None:
    return value.date().isoformat() if value else None


def _month(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m") if value else None


def _dates_between(f: Filters, default_days: int = 30) -> list[str]:
    end = (f.end - timedelta(days=1)).date() if f.end else datetime.now(UTC).date()
    start = f.start.date() if f.start else end - timedelta(days=default_days - 1)
    days = []
    current = start
    while current <= end and len(days) < 800:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _report(
    key: str,
    title: str,
    columns: list[str],
    rows: list[list[Any]],
    summary: dict[str, Any],
    chart: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "columns": columns,
        "rows": rows[:MAX_ROWS],
        "row_count": len(rows),
        "summary": summary,
        "chart": chart,
    }


# --- reports --------------------------------------------------------------------------------------


def usage(session: Session, actor: Principal, f: Filters) -> dict[str, Any]:
    ids = scope(session, actor, f)
    downloads = session.execute(
        select(Download.created_at, Download.actor_subject, Download.lo_id).where(
            Download.lo_id.in_(ids), _in_range(Download.created_at, f)
        )
    ).all()
    favorites = (
        session.execute(
            select(Favorite.created_at).where(
                Favorite.lo_id.in_(ids), _in_range(Favorite.created_at, f)
            )
        )
        .scalars()
        .all()
    )
    views = session.execute(
        select(CollectionView.viewed_at, CollectionView.viewer_subject).where(
            _in_range(CollectionView.viewed_at, f)
        )
    ).all()
    xapi = session.execute(
        select(XapiStatement.stored_at, XapiStatement.actor_key).where(
            _in_range(XapiStatement.stored_at, f)
        )
    ).all()
    per_day: dict[str, Counter] = defaultdict(Counter)
    for when, _, _ in downloads:
        per_day[_day(when)]["downloads"] += 1
    for when in favorites:
        per_day[_day(when)]["favorites"] += 1
    for when, _ in views:
        per_day[_day(when)]["collection_views"] += 1
    for when, _ in xapi:
        per_day[_day(when)]["xapi_statements"] += 1
    days = _dates_between(f)
    rows = [
        [
            d,
            per_day[d]["downloads"],
            per_day[d]["favorites"],
            per_day[d]["collection_views"],
            per_day[d]["xapi_statements"],
        ]
        for d in days
    ]
    by_object = Counter(lo for _, _, lo in downloads)
    titles = (
        dict(
            session.execute(
                select(LearningObject.id, LearningObject.title).where(
                    LearningObject.id.in_(list(by_object))
                )
            ).all()
        )
        if by_object
        else {}
    )
    top = [[titles.get(lo, lo), lo, n] for lo, n in by_object.most_common(10)]
    active = {s for _, s, _ in downloads} | {s for _, s in views} | {a for _, a in xapi}
    summary = {
        "downloads": len(downloads),
        "favorites_added": len(favorites),
        "collection_views": len(views),
        "xapi_statements": len(xapi),
        "active_users": len(active),
        "top_items": top,
    }
    return _report(
        "usage",
        "Usage",
        ["Date", "Downloads", "Favorites added", "Collection views", "xAPI statements"],
        rows,
        summary,
        {
            "type": "line",
            "drill": "day",
            "keys": ["Downloads", "Favorites added"],
            "points": [{"x": r[0], "values": r[1:3]} for r in rows],
        },
    )


def reuse(session: Session, actor: Principal, f: Filters) -> dict[str, Any]:
    ids = list(session.scalars(scope(session, actor, f)))
    columns = ["Item", "Id", "Collections", "Favorites", "Downloads"]
    if not ids:
        return _report(
            "reuse",
            "Reuse",
            columns,
            [],
            {"items": 0, "reused_items": 0, "reuse_rate": None, "duplicates_made": 0},
            None,
        )
    collections = dict(
        session.execute(
            select(CollectionItem.lo_id, func.count(func.distinct(CollectionItem.collection_id)))
            .where(CollectionItem.lo_id.in_(ids))
            .group_by(CollectionItem.lo_id)
        ).all()
    )
    favorites = dict(
        session.execute(
            select(Favorite.lo_id, func.count())
            .where(Favorite.lo_id.in_(ids))
            .group_by(Favorite.lo_id)
        ).all()
    )
    downloads = dict(
        session.execute(
            select(Download.lo_id, func.count())
            .where(Download.lo_id.in_(ids), _in_range(Download.created_at, f))
            .group_by(Download.lo_id)
        ).all()
    )
    titles = dict(
        session.execute(
            select(LearningObject.id, LearningObject.title).where(LearningObject.id.in_(ids))
        ).all()
    )
    rows = [
        [titles[i], i, collections.get(i, 0), favorites.get(i, 0), downloads.get(i, 0)] for i in ids
    ]
    rows.sort(key=lambda r: (-(r[2] + r[3] + r[4]), r[0].lower()))
    reused = [r for r in rows if r[2] >= 2 or r[3] >= 2]
    duplicates = (
        session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action.in_(["library.duplicate", "collection.duplicate"]),
                _in_range(AuditLog.occurred_at, f),
            )
        )
        or 0
    )
    summary = {
        "items": len(ids),
        "reused_items": len(reused),
        "reuse_rate": round(100 * len(reused) / len(ids), 1),
        "duplicates_made": duplicates,
    }
    buckets = Counter(min(r[2] + r[3], 5) for r in rows)
    chart = {
        "type": "bar",
        "drill": None,
        "keys": ["Items"],
        "points": [
            {"x": ("5+" if k == 5 else str(k)) + " uses", "values": [buckets.get(k, 0)]}
            for k in range(0, 6)
        ],
    }
    return _report("reuse", "Reuse", columns, rows, summary, chart)


def growth(session: Session, actor: Principal, f: Filters) -> dict[str, Any]:
    ids = scope(session, actor, f)
    created = Counter(
        _month(c)
        for c in session.scalars(
            select(LearningObject.created_at).where(
                LearningObject.id.in_(ids), _in_range(LearningObject.created_at, f)
            )
        )
    )
    published = Counter(
        _month(c)
        for c in session.scalars(
            select(WorkflowState.created_at).where(
                WorkflowState.to_state == "published",
                WorkflowState.lo_id.in_(ids),
                _in_range(WorkflowState.created_at, f),
            )
        )
    )
    running = 0
    if f.start is not None:
        running = (
            session.scalar(
                select(func.count()).where(
                    LearningObject.id.in_(ids), LearningObject.created_at < f.start
                )
            )
            or 0
        )
    rows = []
    for month in sorted(set(created) | set(published)):
        running += created.get(month, 0)
        rows.append([month, created.get(month, 0), published.get(month, 0), running])
    summary = {
        "created": sum(created.values()),
        "published": sum(published.values()),
        "items_in_scope": session.scalar(select(func.count()).select_from(ids.subquery())) or 0,
    }
    return _report(
        "growth",
        "Growth",
        ["Month", "Created", "Published", "Cumulative"],
        rows,
        summary,
        {
            "type": "line",
            "drill": "month",
            "keys": ["Created", "Published"],
            "points": [{"x": r[0], "values": r[1:3]} for r in rows],
        },
    )


def workflow(session: Session, actor: Principal, f: Filters) -> dict[str, Any]:
    ids = scope(session, actor, f)
    transitions = Counter(
        session.scalars(
            select(WorkflowState.to_state).where(
                WorkflowState.lo_id.in_(ids), _in_range(WorkflowState.created_at, f)
            )
        )
    )
    cases = session.execute(
        select(
            ReviewCase.lo_id, ReviewCase.status, ReviewCase.opened_at, ReviewCase.closed_at
        ).where(ReviewCase.lo_id.in_(ids), _in_range(ReviewCase.opened_at, f))
    ).all()
    states = Counter(status for _, status, _, _ in cases)
    durations = [
        (closed - opened).total_seconds() / 3600
        for _, status, opened, closed in cases
        if status == "approved" and opened and closed
    ]
    avg_hours = round(sum(durations) / len(durations), 1) if durations else None
    escalations = (
        session.scalar(
            select(func.count())
            .select_from(StageTask)
            .where(
                StageTask.case_id.in_(select(ReviewCase.id).where(ReviewCase.lo_id.in_(ids))),
                StageTask.escalated_at.isnot(None),
                _in_range(StageTask.escalated_at, f),
            )
        )
        or 0
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    open_ages = [
        (now - opened).total_seconds() / 86400
        for _, status, opened, _ in cases
        if status in {"open", "under_review"} and opened
    ]
    rows = [[state, count] for state, count in sorted(states.items())]
    rows += [["transition: " + k, v] for k, v in sorted(transitions.items())]
    summary = {
        "reviews_opened": len(cases),
        "approved": states.get("approved", 0),
        "rejected": states.get("rejected", 0),
        "changes_requested": states.get("changes_requested", 0),
        "withdrawn": states.get("withdrawn", 0),
        "open": states.get("open", 0) + states.get("under_review", 0),
        "average_hours_to_approval": avg_hours,
        "oldest_open_days": round(max(open_ages), 1) if open_ages else 0,
        "sla_escalations": escalations,
    }
    return _report(
        "workflow",
        "Workflow",
        ["Outcome", "Count"],
        rows,
        summary,
        {
            "type": "bar",
            "drill": "status",
            "keys": ["Count"],
            "points": [
                {"x": s, "values": [states.get(s, 0)]}
                for s in [
                    "open",
                    "under_review",
                    "approved",
                    "rejected",
                    "changes_requested",
                    "withdrawn",
                ]
            ],
        },
    )


def storage(session: Session, actor: Principal, f: Filters) -> dict[str, Any]:
    ids = scope(session, actor, f)
    total_items = session.scalar(select(func.count()).select_from(ids.subquery())) or 0
    kind_of = dict(
        session.execute(
            select(LearningObject.id, LearningObject.kind).where(LearningObject.id.in_(ids))
        ).all()
    )
    versions = session.execute(
        select(Version.lo_id, Version.storage_key, Version.size_bytes).where(Version.lo_id.in_(ids))
    ).all()
    counted: dict[str, int] = {}
    kind_bytes: Counter = Counter()
    for lo_id, key, size in versions:
        # Restored versions point at the same stored object; each object is counted once.
        if key not in counted:
            counted[key] = size
            kind_bytes[kind_of.get(lo_id, "file")] += size
    counts = Counter(kind_of.values())
    rows = [[kind, counts.get(kind, 0), kind_bytes.get(kind, 0)] for kind in sorted(counts)]
    total = sum(counted.values())
    summary = {
        "stored_bytes": total,
        "stored_objects": len(counted),
        "items": total_items,
        "average_bytes_per_item": round(total / total_items) if total_items else 0,
    }
    return _report(
        "storage",
        "Storage",
        ["Kind", "Items", "Stored bytes"],
        rows,
        summary,
        {
            "type": "bar",
            "drill": "kind",
            "keys": ["Stored bytes"],
            "points": [{"x": r[0], "values": [r[2]]} for r in rows],
        },
    )


def departments(session: Session, actor: Principal, f: Filters) -> dict[str, Any]:
    ids = scope(session, actor, f)
    total_items = session.scalar(select(func.count()).select_from(ids.subquery())) or 0
    names = dict(session.execute(select(Department.id, Department.name)).all())
    items = session.execute(
        select(
            LearningObject.id,
            LearningObject.department_id,
            LearningObject.status,
            LearningObject.created_by,
        ).where(LearningObject.id.in_(ids))
    ).all()
    downloads = Counter(
        session.scalars(
            select(Download.lo_id).where(Download.lo_id.in_(ids), _in_range(Download.created_at, f))
        )
    )
    stored: dict[str, tuple[str, int]] = {}
    for lo_id, key, size in session.execute(
        select(Version.lo_id, Version.storage_key, Version.size_bytes).where(Version.lo_id.in_(ids))
    ).all():
        stored.setdefault(key, (lo_id, size))
    bytes_of: Counter = Counter()
    for lo_id, size in stored.values():
        bytes_of[lo_id] += size
    buckets: dict[Any, dict[str, Any]] = defaultdict(
        lambda: {"items": 0, "published": 0, "downloads": 0, "bytes": 0, "users": set()}
    )
    for lo_id, dept_id, status, created_by in items:
        bucket = buckets["unassigned" if dept_id is None else dept_id]
        bucket["items"] += 1
        bucket["published"] += status == "published"
        bucket["downloads"] += downloads.get(lo_id, 0)
        bucket["bytes"] += bytes_of.get(lo_id, 0)
        bucket["users"].add(created_by)
    rows = []
    for key, b in sorted(buckets.items(), key=lambda kv: str(kv[0])):
        label = "Unassigned" if key == "unassigned" else names.get(key, f"Department {key}")
        rows.append(
            [label, key, b["items"], b["published"], b["downloads"], b["bytes"], len(b["users"])]
        )
    summary = {
        "departments": len([k for k in buckets if k != "unassigned"]),
        "items": total_items,
        "downloads": sum(b["downloads"] for b in buckets.values()),
    }
    return _report(
        "departments",
        "Departments",
        ["Department", "Id", "Items", "Published", "Downloads", "Stored bytes", "Contributors"],
        rows,
        summary,
        {
            "type": "bar",
            "drill": "department",
            "keys": ["Items"],
            "points": [{"x": r[0], "values": [r[2]]} for r in rows],
        },
    )


BUILDERS = {
    "usage": usage,
    "reuse": reuse,
    "growth": growth,
    "workflow": workflow,
    "storage": storage,
    "departments": departments,
}


def build(session: Session, actor: Principal, name: str, f: Filters) -> dict[str, Any]:
    if name not in BUILDERS:
        raise NotFoundError("unknown report")
    return BUILDERS[name](session, actor, f)


# --- drill-down -----------------------------------------------------------------------------------


def drill(
    session: Session, actor: Principal, dimension: str, value: str, f: Filters
) -> list[dict[str, Any]]:
    if dimension not in DRILL_DIMENSIONS:
        raise ValidationFailure("unknown drill-down dimension")
    ids = scope(session, actor, f)
    query = select(
        LearningObject.id,
        LearningObject.title,
        LearningObject.status,
        LearningObject.kind,
        LearningObject.created_at,
    ).where(LearningObject.id.in_(ids))
    if dimension == "status":
        query = query.where(LearningObject.status == value)
    elif dimension == "kind":
        query = query.where(LearningObject.kind == value)
    elif dimension == "department":
        query = query.where(
            LearningObject.department_id.is_(None)
            if value == "unassigned"
            else LearningObject.department_id == int(value)
        )
    elif dimension == "subject":
        query = query.join(MetadataLOM, MetadataLOM.lo_id == LearningObject.id).where(
            MetadataLOM.subject == (None if value == "" else value)
        )
    elif dimension == "month":
        year, month = (int(p) for p in value.split("-"))
        start = datetime(year, month, 1)
        end = datetime(year + (month // 12), month % 12 + 1, 1)
        query = query.where(LearningObject.created_at >= start, LearningObject.created_at < end)
    elif dimension == "day":
        day = date.fromisoformat(value)
        start = datetime.combine(day, time.min)
        downloaded = select(Download.lo_id).where(
            Download.created_at >= start, Download.created_at < start + timedelta(days=1)
        )
        query = query.where(LearningObject.id.in_(downloaded))
    rows = session.execute(query.order_by(LearningObject.title).limit(MAX_ROWS)).all()
    return [
        {
            "id": r[0],
            "title": r[1],
            "status": r[2],
            "kind": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]
