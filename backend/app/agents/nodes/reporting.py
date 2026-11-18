"""Answer completion questions by choosing one of a fixed set of query templates.

TODO(reporting): replace the keyword router with a Claude-based intent classifier that returns
a template name. The classifier output must still be checked against TEMPLATES before use.
"""

from app.agents.deps import GraphDeps
from app.agents.state import LORState
from app.agents.tools.db_query import TEMPLATES, run_template

SUPPORTED = (
    "total completions",
    "completions by object",
    "unique learners who completed",
    "number of published items",
)


def choose_template(question: str) -> str | None:
    q = question.lower()
    if "published" in q:
        return "published_count"
    if "learner" in q or "people" in q:
        return "unique_learners"
    if "completion" in q or "completed" in q:
        return (
            "completions_by_object"
            if ("object" in q or "by" in q or "which" in q)
            else "completions_total"
        )
    return None


def make_reporting_node(deps: GraphDeps):
    def reporting(state: LORState) -> dict:
        question = state.get("query", "")
        name = choose_template(question)
        if name is None or name not in TEMPLATES or deps.session_factory is None:
            return {
                "answer": "I can answer: " + "; ".join(SUPPORTED) + ".",
                "messages": ["reporting: unsupported question"],
            }
        with deps.session_factory() as session:
            rows = run_template(session, name)
        return {"answer": f"{name}: {rows}", "messages": [f"reporting: template {name}"]}

    return reporting
