"""Draft IEEE LOM metadata from package text via Claude (ChatBedrock).

Output is parsed and validated against ExtractedLOM. If the model's output is not valid, the node
falls back to manifest data with confidence 0.0 so a reviewer sees the gap, and the run continues.
"""

import json
import re

from app.agents.deps import GraphDeps
from app.agents.state import LORState
from app.agents.tools.file_parser import parse_package
from app.schemas.lom import ExtractedLOM

PROMPT = """You are cataloguing a learning object for an enterprise repository.
Return ONLY a JSON object with these keys: title (string), description (string),
language (BCP-47 code), keywords (array of strings), subject (string),
learning_resource_type (string), license (string or null), confidence (number 0..1).

Manifest title: {title}
Manifest license: {license}
Package files: {files}
Text excerpt:
{excerpt}
"""


def _extract_json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in model output")
    return json.loads(match.group(0))


def make_metadata_node(deps: GraphDeps):
    def metadata_extraction(state: LORState) -> dict:
        data = deps.storage.open(state["file_path"]).read()
        info = parse_package(data)
        prompt = PROMPT.format(
            title=info.manifest_title or "(none)",
            license=info.manifest_license or "(none)",
            files=", ".join(info.file_names[:50]) or "(none)",
            excerpt=info.text_excerpt or "(no text)",
        )
        try:
            raw = deps.llm_factory().invoke(prompt).content
            draft = ExtractedLOM.model_validate(_extract_json(str(raw)))
            extracted = draft.model_dump()
        except (
            ValueError,
            TypeError,
        ) as exc:  # JSONDecodeError and ValidationError are ValueErrors
            extracted = {
                "title": info.manifest_title or state.get("lo_id", "untitled"),
                "description": None,
                "language": None,
                "keywords": [],
                "subject": None,
                "learning_resource_type": None,
                "license": info.manifest_license,
                "confidence": 0.0,
            }
            return {
                "extracted_metadata": extracted,
                "messages": [f"metadata_extraction fallback: {type(exc).__name__}"],
            }
        return {
            "extracted_metadata": extracted,
            "messages": [f"metadata_extraction ok (confidence={draft.confidence:.2f})"],
        }

    return metadata_extraction
