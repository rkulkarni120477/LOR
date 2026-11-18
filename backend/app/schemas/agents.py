from typing import Any, Literal

from pydantic import BaseModel, Field


class ResumeRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=2000)


class AgentRunResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "paused"]
    next_action: str | None = None
    compliance_score: float | None = None
    compliance_issues: list[str] = Field(default_factory=list)
    extracted_metadata: dict[str, Any] | None = None
    taxonomy_tags: list[str] = Field(default_factory=list)
    interrupt: dict[str, Any] | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
