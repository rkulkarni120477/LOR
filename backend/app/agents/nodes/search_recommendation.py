"""RAG over learning object metadata for learner questions.

Retrieves the top matching published items by embedding, then asks Claude to answer using only
those items. The answer is passed through the optional guardrail.
"""

from app.agents.deps import GraphDeps
from app.agents.state import LORState
from app.llm.guardrails import apply_guardrail

PROMPT = """Answer the learner's question using ONLY the catalogue entries below. If none fit,
say so and suggest a broader search term. Cite entries by title.

Catalogue:
{context}

Question: {question}
"""


def make_search_node(deps: GraphDeps):
    def search_recommendation(state: LORState) -> dict:
        question = state.get("query", "")
        if deps.retriever is None:
            return {"answer": "Search index is not configured.", "messages": ["search: no index"]}
        hits = deps.retriever.retrieve(question, k=5, prefix="lo:")
        if not hits:
            return {
                "answer": "No matching learning objects were found.",
                "messages": ["search: 0 hits"],
            }
        context = "\n".join(f"- {lo_id} (relevance {score:.2f})" for lo_id, score in hits)
        raw = deps.llm_factory().invoke(PROMPT.format(context=context, question=question)).content
        checked = apply_guardrail(str(raw), source="OUTPUT")
        return {"answer": checked.text, "messages": [f"search: {len(hits)} hits"]}

    return search_recommendation
