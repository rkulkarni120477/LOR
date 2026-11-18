"""Map the draft metadata onto taxonomy_terms using vector retrieval over term embeddings."""

from app.agents.deps import GraphDeps
from app.agents.state import LORState


def make_taxonomy_node(deps: GraphDeps):
    def taxonomy_tagging(state: LORState) -> dict:
        if deps.retriever is None:
            return {"taxonomy_tags": [], "messages": ["taxonomy_tagging skipped: no retriever"]}
        meta = state.get("extracted_metadata", {})
        text = " ".join(
            [
                meta.get("title") or "",
                meta.get("description") or "",
                " ".join(meta.get("keywords", [])),
            ]
        ).strip()
        if not text:
            return {"taxonomy_tags": [], "messages": ["taxonomy_tagging: no text"]}
        hits = deps.retriever.retrieve(
            text, k=5, prefix="term:", min_similarity=deps.taxonomy_threshold
        )
        tags = [term_id for term_id, _score in hits]
        return {"taxonomy_tags": tags, "messages": [f"taxonomy_tagging matched {len(tags)} terms"]}

    return taxonomy_tagging
