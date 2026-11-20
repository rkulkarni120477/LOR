"""OpenSearch projection. PostgreSQL remains the source of publication/access truth."""

from functools import lru_cache

from opensearchpy import OpenSearch, RequestError, helpers
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.db.models import LearningObject, SearchIndexJob


@lru_cache
def get_search_client() -> OpenSearch:
    settings = get_settings()
    kwargs = {
        "hosts": [settings.opensearch_url],
        "verify_certs": settings.opensearch_verify_certs,
        "timeout": 5,
        "max_retries": 2,
        "retry_on_timeout": True,
    }
    if settings.opensearch_username:
        kwargs["http_auth"] = (settings.opensearch_username, settings.opensearch_password)
    return OpenSearch(**kwargs)


def ensure_index(client=None):
    client = client or get_search_client()
    index = get_settings().opensearch_index
    if not client.indices.exists(index=index):
        try:
            client.indices.create(
                index=index,
                body={
                    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                    "mappings": {
                        "dynamic": "strict",
                        "properties": {
                            "title": {"type": "text"},
                            "description": {"type": "text"},
                            "keywords": {"type": "text"},
                            "subject": {"type": "keyword"},
                            "format": {"type": "keyword"},
                        },
                    },
                },
            )
        except RequestError as exc:
            if exc.error != "resource_already_exists_exception":
                raise


def schedule_index(session: Session, lo_id: str):
    if get_settings().search_backend == "opensearch":
        session.add(SearchIndexJob(lo_id=lo_id))


def index_object(session: Session, lo_id: str, client=None):
    client = client or get_search_client()
    index = get_settings().opensearch_index
    lo = session.scalar(
        select(LearningObject)
        .where(LearningObject.id == lo_id)
        .options(selectinload(LearningObject.metadata_record))
    )
    if lo is None or lo.status != "published" or lo.metadata_record is None:
        client.delete(index=index, id=lo_id, ignore=[404], refresh="wait_for")
        return
    meta = lo.metadata_record
    client.index(
        index=index,
        id=lo_id,
        refresh="wait_for",
        body={
            "title": lo.title,
            "description": meta.description or "",
            "keywords": meta.keywords or [],
            "subject": meta.subject,
            "format": meta.learning_resource_type,
        },
    )


def matching_ids(q: str) -> list[str]:
    """Scroll IDs only; callers recheck publication and compute counts/facets in SQL.

    This avoids leaking revoked content from an eventually consistent index. Large
    installations should replace candidate materialization with a PIT pagination contract.
    """
    client = get_search_client()
    return [
        hit["_id"]
        for hit in helpers.scan(
            client,
            index=get_settings().opensearch_index,
            query={
                "_source": False,
                "query": {
                    "multi_match": {
                        "query": q,
                        "fields": ["title^3", "description", "keywords^2"],
                        "operator": "and",
                    }
                },
            },
            size=500,
            request_timeout=5,
        )
    ]
