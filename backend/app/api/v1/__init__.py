"""Version 1 API. Mounted under /api/v1 by app.main."""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    auth,
    collections,
    content,
    identity,
    library,
    metadata,
    notifications,
    reports,
    repository,
    search,
    taxonomy,
    uploads,
    workflow,
    xapi,
)

api_router = APIRouter()
for module in (
    auth,
    identity,
    content,
    library,
    metadata,
    notifications,
    search,
    taxonomy,
    uploads,
    workflow,
    reports,
    collections,
    repository,
    agents,
    xapi,
):
    api_router.include_router(module.router)
