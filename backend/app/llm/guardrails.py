"""Optional Amazon Bedrock Guardrails wrapper. Disabled unless GUARDRAILS_ENABLED=true."""

from dataclasses import dataclass

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    text: str
    reason: str | None = None


def apply_guardrail(text: str, source: str = "OUTPUT", settings: Settings | None = None):
    """Run text through the configured guardrail. source is "INPUT" or "OUTPUT".

    When disabled this is a pass-through, so tests and local runs need no AWS access.
    """
    s = settings or get_settings()
    if not s.guardrails_enabled:
        return GuardrailResult(allowed=True, text=text)
    if not s.bedrock_guardrail_id:
        raise RuntimeError("GUARDRAILS_ENABLED=true but BEDROCK_GUARDRAIL_ID is empty")

    import boto3

    client = boto3.client("bedrock-runtime", region_name=s.aws_region)
    response = client.apply_guardrail(
        guardrailIdentifier=s.bedrock_guardrail_id,
        guardrailVersion=s.bedrock_guardrail_version,
        source=source,
        content=[{"text": {"text": text}}],
    )
    if response.get("action") == "GUARDRAIL_INTERVENED":
        outputs = response.get("outputs", [])
        replacement = outputs[0]["text"] if outputs else "This response was blocked by policy."
        return GuardrailResult(allowed=False, text=replacement, reason="guardrail_intervened")
    return GuardrailResult(allowed=True, text=text)
