"""Human-in-the-loop node: pauses with interrupt() and resumes with the reviewer's decision."""

from langgraph.types import interrupt

from app.agents.state import LORState


def human_review(state: LORState) -> dict:
    reviewer_payload = interrupt(
        {
            "lo_id": state.get("lo_id"),
            "compliance_score": state.get("compliance_score"),
            "compliance_issues": state.get("compliance_issues", []),
            "question": "Approve or reject this learning object?",
        }
    )
    decision = str(reviewer_payload.get("decision", "")).lower()
    if decision not in {"approve", "reject"}:
        raise ValueError("resume payload must include decision: approve | reject")
    return {
        "review_decision": decision,
        "messages": [f"human_review decision={decision}"],
    }
