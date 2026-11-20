"""POST /api/v1/xapi/statements accepts one statement or a list. Malformed input returns 400."""

import json

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailure
from app.core.security import Principal, require_permission
from app.db.session import get_db
from app.schemas.xapi import XapiStatement, XapiStoredResponse
from app.services import xapi as xapi_service

router = APIRouter(prefix="/xapi", tags=["xapi"])


@router.post("/statements", response_model=XapiStoredResponse)
async def post_statements(
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("activity.write")),
) -> XapiStoredResponse:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise ValidationFailure("request body is not valid JSON") from exc

    raw_list = body if isinstance(body, list) else [body]
    if not raw_list or not all(isinstance(item, dict) for item in raw_list):
        raise ValidationFailure("expected a statement object or a non-empty list of objects")

    try:
        statements = [XapiStatement.model_validate(item) for item in raw_list]
    except ValidationError as exc:
        raise ValidationFailure(f"invalid xAPI statement: {exc.errors()[0]['msg']}") from exc

    ids = xapi_service.store_statements(db, statements)
    return XapiStoredResponse(ids=ids)
