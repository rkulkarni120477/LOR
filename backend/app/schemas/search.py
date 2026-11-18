from pydantic import BaseModel

from app.schemas.common import Page
from app.schemas.lom import LOMMetadata


class SearchHit(BaseModel):
    id: str
    title: str
    description: str | None
    subject: str | None
    learning_resource_type: str | None
    keywords: list[str]


class Facet(BaseModel):
    value: str
    count: int


class SearchResponse(Page[SearchHit]):
    facets: dict[str, list[Facet]]


__all__ = ["SearchHit", "SearchResponse", "Facet", "LOMMetadata"]
