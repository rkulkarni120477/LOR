from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import Principal, require_permission
from app.db.session import get_db
from app.schemas.lom import LOMMetadata
from app.services import metadata as metadata_service

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.put("/{lo_id}", response_model=LOMMetadata)
def put_metadata(
    lo_id: str,
    payload: LOMMetadata,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("content.edit")),
) -> LOMMetadata:
    meta = metadata_service.update_metadata(db, lo_id, payload, principal)
    return LOMMetadata.model_validate(meta.lom_json.get("lom", {}))
