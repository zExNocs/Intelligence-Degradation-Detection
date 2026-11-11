"""Resolve model-specific reasoning choices for forms and execution validation."""

from .models import DomainError

PROTOCOL_EFFORTS = {
    "openai_responses": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
    "openai_chat": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
    "anthropic_messages": ("low", "medium", "high", "max"),
}

# Keep verified model restrictions separate from protocol-wide wire values.
# https://developers.openai.com/api/docs/models/gpt-6.1-sol
OPENAI_MODEL_EFFORTS = {
    "gpt-6.1-sol": ("low", "medium", "high", "xhigh", "max"),
}


def reasoning_options(protocol: str, model: str) -> list[str]:
    """Return explicit effort values; upstream default always means omission."""
    if protocol not in PROTOCOL_EFFORTS:
        raise DomainError("protocol_unsupported", "Unknown model protocol.")
    if (
        protocol in {"openai_responses", "openai_chat"}
        and model in OPENAI_MODEL_EFFORTS
    ):
        return list(OPENAI_MODEL_EFFORTS[model])
    return list(PROTOCOL_EFFORTS[protocol])


def validate_reasoning(protocol: str, model: str, effort: str) -> None:
    """Reject known incompatible choices without silently changing a saved test."""
    options = reasoning_options(protocol, model)
    if effort != "default" and effort not in options:
        raise DomainError(
            "reasoning_unsupported",
            f"Reasoning effort '{effort}' is not supported for '{model}'. "
            f"Choose upstream default or: {', '.join(options)}.",
        )
