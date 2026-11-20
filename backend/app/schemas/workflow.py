from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SubmitRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
    policy_id: int | None = Field(default=None, ge=1)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "request_changes"]
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _comment_required_on_reject(self) -> "DecisionRequest":
        if self.decision in {"reject", "request_changes"} and not (
            self.comment and self.comment.strip()
        ):
            raise ValueError("a comment is required when rejecting or requesting changes")
        return self


class WorkflowStateOut(BaseModel):
    lo_id: str
    status: str


class StageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    permission: str = Field(min_length=1, max_length=64)
    approvals_required: int = Field(default=1, ge=1, le=10)
    assignees: list[str] = Field(default_factory=list, max_length=50)
    sla_hours: int | None = Field(default=None, ge=1, le=24 * 90)
    escalation_role: str = Field(default="Repository Administrator", max_length=64)


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"\S")
    description: str = Field(default="", max_length=2000)
    stages: list[StageIn] = Field(min_length=1, max_length=10)


class PolicyUpdate(BaseModel):
    active: bool


class AssignIn(BaseModel):
    assignee_subject: str = Field(min_length=1, max_length=255)
