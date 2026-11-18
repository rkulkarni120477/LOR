"""DEV ONLY. Mounted by app.main only when ENV=development. Returns signed tokens for each role."""

from fastapi import APIRouter, Query

from app.core.dev_tokens import mint_tokens

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/tokens")
def dev_tokens(hours: float = Query(24.0, gt=0, le=168)) -> dict:
    return {
        "warning": "DEVELOPMENT ONLY. This endpoint does not exist when ENV is not development.",
        "tokens": mint_tokens(hours),
    }
