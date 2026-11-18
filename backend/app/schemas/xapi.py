"""Minimal xAPI statement shape: actor, verb, object. Extra properties are allowed and stored."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class XapiActor(BaseModel):
    model_config = ConfigDict(extra="allow")

    objectType: str | None = None
    mbox: str | None = Field(default=None, pattern=r"^mailto:.+@.+$")
    account: dict[str, Any] | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _requires_identifier(self) -> "XapiActor":
        if not self.mbox and not self.account:
            raise ValueError("actor needs an mbox or account identifier")
        return self

    @property
    def key(self) -> str:
        if self.mbox:
            return self.mbox
        return f"{self.account.get('homePage', '')}|{self.account.get('name', '')}"


class XapiVerb(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^https?://\S+$")
    display: dict[str, str] | None = None


class XapiObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^https?://\S+$")
    objectType: str | None = None


class XapiStatement(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = Field(default=None, min_length=36, max_length=36)
    actor: XapiActor
    verb: XapiVerb
    object: XapiObject
    result: dict[str, Any] | None = None
    timestamp: datetime | None = None

    @field_validator("id")
    @classmethod
    def _id_is_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return value
        import uuid

        uuid.UUID(value)  # raises ValueError -> 400
        return value


class XapiStoredResponse(BaseModel):
    ids: list[str]
