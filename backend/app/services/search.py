"""Keyword and facet search over published learning objects' metadata."""

from opensearchpy.exceptions import OpenSearchException
from sqlalchemy import Select, String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import DomainError
from app.core.security import Principal
from app.db.models import LearningObject, MetadataLOM
from app.services.access import read_condition
from app.services.content import PUBLISHED
from app.services.search_index import matching_ids


def _base_query(q: str | None, actor: Principal | None = None) -> Select:
    query = (
        select(MetadataLOM)
        .join(LearningObject, LearningObject.id == MetadataLOM.lo_id)
        .where(
            LearningObject.status == PUBLISHED,
            LearningObject.archived_at.is_(None),
            LearningObject.deleted_at.is_(None),
        )
    )
    if actor is not None:
        query = query.where(read_condition(actor))
    if q:
        if get_settings().search_backend == "opensearch":
            try:
                return query.where(MetadataLOM.lo_id.in_(matching_ids(q.strip())))
            except OpenSearchException as exc:
                error = DomainError("Search service unavailable; please retry")
                error.status_code = 503
                error.code = "search_unavailable"
                raise error from exc
        # Every term must match somewhere: title, description, keywords or the full-text column.
        for term in q.lower().split()[:10]:
            pattern = f"%{term}%"
            query = query.where(
                or_(
                    MetadataLOM.title.ilike(pattern),
                    MetadataLOM.description.ilike(pattern),
                    cast(MetadataLOM.keywords, String).ilike(pattern),
                    LearningObject.search_text.like(pattern),
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
    actor: Principal | None = None,
) -> tuple[list[MetadataLOM], int, dict[str, list[tuple[str, int]]]]:
    base_query = _base_query(q, actor)
    filtered = base_query
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
    base = base_query.subquery()
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
