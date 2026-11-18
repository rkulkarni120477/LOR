"""Version 1 API. Mounted under /api/v1 by app.main."""

from fastapi import APIRouter

from app.api.v1 import agents, content, metadata, reports, search, workflow, xapi

api_router = APIRouter()
for module in (content, metadata, search, workflow, reports, agents, xapi):
    api_router.include_router(module.router)
