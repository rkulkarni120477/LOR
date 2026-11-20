from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Kind = Literal["file", "rich_text", "quiz", "assessment"]
QuizKind = Literal["quiz", "assessment"]
State = Literal["active", "archived", "deleted"]
BulkAction = Literal["archive", "unarchive", "delete", "restore"]


class Question(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    type: Literal["single_choice", "true_false"] = "single_choice"
    options: list[str] = Field(default_factory=list, max_length=10)
    correct: int = Field(ge=0, le=9)
    points: int = Field(default=1, ge=1, le=100)
    explanation: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def check_options(self):
        if self.type == "true_false":
            self.options = ["True", "False"]
        if not 2 <= len(self.options) <= 10:
            raise ValueError("a question needs between 2 and 10 options")
        if any(not option.strip() or len(option) > 500 for option in self.options):
            raise ValueError("options must be non-empty and at most 500 characters")
        if self.correct >= len(self.options):
            raise ValueError("the correct option index is out of range")
        return self


class Metadata(BaseModel):
    description: str = Field(default="", max_length=5000)
    subject: str | None = Field(default=None, max_length=255)
    learning_resource_type: str | None = Field(default=None, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: list[str]) -> list[str]:
        return [k.strip()[:100] for k in value if k.strip()]


class RichTextIn(Metadata):
    title: str = Field(min_length=1, max_length=500)
    html: str = Field(default="", max_length=200_000)
    is_template: bool = False


class QuizIn(Metadata):
    title: str = Field(min_length=1, max_length=500)
    kind: QuizKind = "quiz"
    passing_score: int = Field(default=70, ge=0, le=100)
    questions: list[Question] = Field(default_factory=list, max_length=200)
    is_template: bool = False


class DraftIn(BaseModel):
    """Autosave payload. `revision` is the revision the client last saw."""

    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    subject: str | None = Field(default=None, max_length=255)
    learning_resource_type: str | None = Field(default=None, max_length=100)
    keywords: list[str] | None = Field(default=None, max_length=30)
    html: str | None = Field(default=None, max_length=200_000)
    passing_score: int | None = Field(default=None, ge=0, le=100)
    questions: list[Question] | None = Field(default=None, max_length=200)
    is_template: bool | None = None


class BulkIn(BaseModel):
    action: BulkAction
    ids: list[str] = Field(min_length=1, max_length=100)


class LibraryItem(BaseModel):
    id: str
    title: str
    kind: str
    status: str
    is_template: bool
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    params: dict[str, str | bool | None] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def bounded(cls, value):
        if len(value) > 10:
            raise ValueError("too many search parameters")
        for key, item in value.items():
            if len(key) > 40 or (isinstance(item, str) and len(item) > 500):
                raise ValueError("search parameter is too long")
        return value
