"""Keyword and facet search over published learning objects' metadata."""

from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import LearningObject, MetadataLOM
from app.services.content import PUBLISHED


def _base_query(q: str | None) -> Select:
    query = (
        select(MetadataLOM)
        .join(LearningObject, LearningObject.id == MetadataLOM.lo_id)
        .where(LearningObject.status == PUBLISHED)
    )
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                MetadataLOM.title.ilike(pattern),
                MetadataLOM.description.ilike(pattern),
                cast(MetadataLOM.keywords, String).ilike(pattern),
            )
        )
    return query


def search(
    session: Session,
    *,
    q: str | None,
    subject: str | None,
    format: str | None,  # noqa: A002 - matches the public query parameter name
    page: int,
    page_size: int,
) -> tuple[list[MetadataLOM], int, dict[str, list[tuple[str, int]]]]:
    filtered = _base_query(q)
    if subject:
        filtered = filtered.where(MetadataLOM.subject == subject)
    if format:
        filtered = filtered.where(MetadataLOM.learning_resource_type == format)

    total = session.scalar(select(func.count()).select_from(filtered.subquery())) or 0
    hits = session.scalars(
        filtered.order_by(MetadataLOM.title).offset((page - 1) * page_size).limit(page_size)
    ).all()

    # Facet counts are computed over the query without its own facet filter, so users can
    # see the alternatives they could switch to.
    base = _base_query(q).subquery()
    facets: dict[str, list[tuple[str, int]]] = {}
    for column_name, column in (
        ("subject", base.c.subject),
        ("format", base.c.learning_resource_type),
    ):
        rows = session.execute(
            select(column, func.count()).where(column.isnot(None)).group_by(column)
        ).all()
        facets[column_name] = [(str(value), int(count)) for value, count in rows]
    return list(hits), total, facets
