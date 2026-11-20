"""IEEE LOM-aligned metadata schemas (subset of the standard used by this repository)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LOMMetadata(BaseModel):
    """Editable LOM fields. PUT /metadata/{lo_id} replaces these fields."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    language: str | None = Field(default=None, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$")
    keywords: list[str] = Field(default_factory=list, max_length=50)
    subject: str | None = Field(default=None, max_length=255)
    learning_resource_type: str | None = Field(default=None, max_length=100)
    license: str | None = Field(default=None, max_length=255)
    rights_description: str | None = Field(default=None, max_length=5000)
    duration: str | None = Field(default=None, max_length=64, description="ISO 8601 duration")
    difficulty: str | None = Field(default=None, max_length=32)
    duration_minutes: int | None = Field(default=None, ge=0, le=100000)
    learning_standard: str | None = Field(default=None, max_length=100)
    alt_text_provided: bool | None = None
    captions_provided: bool | None = None
    # Values for the custom fields defined under Schema. Checked against those definitions on save.
    custom: dict[str, Any] = Field(default_factory=dict)

    @field_validator("custom")
    @classmethod
    def _bounded_custom(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 50:
            raise ValueError("at most 50 custom values")
        return value

    @field_validator("keywords")
    @classmethod
    def _strip_keywords(cls, value: list[str]) -> list[str]:
        return [k.strip() for k in value if k and k.strip()]


class ExtractedLOM(BaseModel):
    """Shape the metadata_extraction agent must produce (validated after LLM output)."""

    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=500)
    description: str | None = None
    language: str | None = None
    keywords: list[str] = Field(default_factory=list)
    subject: str | None = None
    learning_resource_type: str | None = None
    license: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
