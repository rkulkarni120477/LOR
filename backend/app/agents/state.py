"""Shared graph state. Keys are optional so each node returns only what it changes."""

import operator
from typing import Annotated, Any, TypedDict


class LORState(TypedDict, total=False):
    lo_id: str
    file_path: str  # storage key of the package (resolved by the storage backend)
    extracted_metadata: dict[str, Any]
    taxonomy_tags: list[str]
    compliance_score: float  # 0.0 .. 1.0
    compliance_issues: list[str]
    review_decision: str  # "approve" | "reject" | ""
    messages: Annotated[list[str], operator.add]
    next_action: str
    # Used by the search/RAG path (added to the spec's list):
    query: str
    answer: str
