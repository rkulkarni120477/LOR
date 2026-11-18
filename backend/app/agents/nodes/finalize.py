"""Terminal nodes. They only set next_action; the API layer applies results to the database and
the workflow service performs the actual state transitions."""

from app.agents.state import LORState


def finalize(state: LORState) -> dict:
    return {
        "next_action": "ready_for_submission",
        "messages": ["finalize: ready_for_submission"],
    }


def return_to_contributor(state: LORState) -> dict:
    return {
        "next_action": "return_to_contributor",
        "messages": ["return_to_contributor: reviewer rejected"],
    }
