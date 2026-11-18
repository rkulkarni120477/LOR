"""LangGraph graphs.

Ingest (supervisor):
  START -> metadata_extraction -> taxonomy_tagging -> quality_compliance
     compliance_score < COMPLIANCE_THRESHOLD -> human_review (interrupt)
         approve -> finalize -> END
         reject  -> return_to_contributor -> END
     otherwise -> finalize -> END

Ask (router):
  START -> route -> reporting | search_recommendation -> END
"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer

from app.agents.deps import GraphDeps
from app.agents.nodes.finalize import finalize, return_to_contributor
from app.agents.nodes.human_review import human_review
from app.agents.nodes.metadata_extraction import make_metadata_node
from app.agents.nodes.quality_compliance import make_compliance_node
from app.agents.nodes.reporting import choose_template, make_reporting_node
from app.agents.nodes.search_recommendation import make_search_node
from app.agents.nodes.taxonomy_tagging import make_taxonomy_node
from app.agents.state import LORState


def route_after_compliance(state: LORState, threshold: float) -> str:
    score = state.get("compliance_score", 0.0)
    return "human_review" if score < threshold else "finalize"


def route_after_review(state: LORState) -> str:
    return "finalize" if state.get("review_decision") == "approve" else "return_to_contributor"


def build_ingest_graph(deps: GraphDeps, checkpointer: Checkpointer):
    graph = StateGraph(LORState)
    graph.add_node("metadata_extraction", make_metadata_node(deps))
    graph.add_node("taxonomy_tagging", make_taxonomy_node(deps))
    graph.add_node("quality_compliance", make_compliance_node(deps))
    graph.add_node("human_review", human_review)
    graph.add_node("finalize", finalize)
    graph.add_node("return_to_contributor", return_to_contributor)

    graph.add_edge(START, "metadata_extraction")
    graph.add_edge("metadata_extraction", "taxonomy_tagging")
    graph.add_edge("taxonomy_tagging", "quality_compliance")
    graph.add_conditional_edges(
        "quality_compliance",
        lambda state: route_after_compliance(state, deps.compliance_threshold),
        {"human_review": "human_review", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "human_review",
        route_after_review,
        {"finalize": "finalize", "return_to_contributor": "return_to_contributor"},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("return_to_contributor", END)
    return graph.compile(checkpointer=checkpointer)


def build_ask_graph(deps: GraphDeps, checkpointer: Checkpointer | None = None):
    def route(state: LORState) -> str:
        return "reporting" if choose_template(state.get("query", "")) else "search"

    graph = StateGraph(LORState)
    graph.add_node("route", lambda state: {})
    graph.add_node("reporting", make_reporting_node(deps))
    graph.add_node("search", make_search_node(deps))
    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", route, {"reporting": "reporting", "search": "search"})
    graph.add_edge("reporting", END)
    graph.add_edge("search", END)
    return graph.compile(checkpointer=checkpointer)
