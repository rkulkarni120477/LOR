from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SubmitRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class DecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _comment_required_on_reject(self) -> "DecisionRequest":
        if self.decision == "reject" and not (self.comment and self.comment.strip()):
            raise ValueError("a comment is required when rejecting")
        return self


class WorkflowStateOut(BaseModel):
    lo_id: str
    status: str
