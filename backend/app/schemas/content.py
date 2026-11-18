from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.lom import LOMMetadata


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version_number: int
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    created_by: str
    created_at: datetime


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class ContentDetail(ContentOut):
    versions: list[VersionOut]
    metadata: LOMMetadata | None = None
