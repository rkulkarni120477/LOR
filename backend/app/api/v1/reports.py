from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import Principal, require_permission
from app.db.session import get_db
from app.services import reports as reports_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/completions")
def completions(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("reports.read")),
) -> dict:
    return reports_service.completion_summary(db)
