from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import Principal, require_permission
from app.db.session import get_db
from app.schemas.search import Facet, SearchHit, SearchResponse
from app.services import search as search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str | None = Query(None, max_length=200),
    subject: str | None = Query(None, max_length=255),
    format: str | None = Query(None, max_length=100),  # noqa: A002
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("content.read")),
) -> SearchResponse:
    hits, total, facets = search_service.search(
        db, q=q, subject=subject, format=format, page=page, page_size=page_size, actor=principal
    )
    return SearchResponse(
        items=[
            SearchHit(
                id=m.lo_id,
                title=m.title,
                description=m.description,
                subject=m.subject,
                learning_resource_type=m.learning_resource_type,
                keywords=list(m.keywords or []),
            )
            for m in hits
        ],
        page=page,
        page_size=page_size,
        total=total,
        facets={
            name: [Facet(value=v, count=c) for v, c in values] for name, values in facets.items()
        },
    )
