"""Deterministic accessibility and rights checks. Produces compliance_score in [0, 1].

Checks (equal weight; a check that does not apply counts as passed):
  1. alt text: every <img> in the package has a non-empty alt attribute
  2. captions: if the package contains video, it also contains a caption file (.vtt/.srt)
  3. license: a license is declared, either in the manifest or in the draft metadata
"""

from app.agents.deps import GraphDeps
from app.agents.state import LORState
from app.agents.tools.file_parser import parse_package


def make_compliance_node(deps: GraphDeps):
    def quality_compliance(state: LORState) -> dict:
        data = deps.storage.open(state["file_path"]).read()
        info = parse_package(data)
        issues: list[str] = []
        checks: list[bool] = []

        alt_ok = info.img_count == 0 or info.img_with_alt == info.img_count
        checks.append(alt_ok)
        if not alt_ok:
            issues.append(f"{info.img_count - info.img_with_alt} image(s) missing alt text")

        captions_ok = not info.has_video or info.has_captions
        checks.append(captions_ok)
        if not captions_ok:
            issues.append("video present without caption file (.vtt or .srt)")

        meta = state.get("extracted_metadata", {})
        license_ok = bool(info.manifest_license or meta.get("license"))
        checks.append(license_ok)
        if not license_ok:
            issues.append("no license declared")

        if not info.is_valid_zip:
            issues.append("package is not a valid zip archive")
            checks = [False]

        score = round(sum(checks) / len(checks), 4)
        return {
            "compliance_score": score,
            "compliance_issues": issues,
            "messages": [f"quality_compliance score={score:.2f}"],
        }

    return quality_compliance
