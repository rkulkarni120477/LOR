"""Version 1 API. Mounted under /api/v1 by app.main."""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    analytics,
    auth,
    collections,
    content,
    identity,
    integrations,
    library,
    metadata,
    notifications,
    reports,
    repository,
    search,
    taxonomy,
    uploads,
    versioning,
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
    versioning,
    workflow,
    reports,
    collections,
    analytics,
    integrations,
    repository,
    agents,
    xapi,
):
    api_router.include_router(module.router)
