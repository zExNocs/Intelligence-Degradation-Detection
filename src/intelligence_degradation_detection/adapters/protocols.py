"""Adapt supported wire protocols to a common streaming result contract."""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import JsonValue

from ..domain.models import Account, DomainError, Output, Settings, Usage

JsonObject = dict[str, JsonValue]


def object_value(value: JsonValue) -> JsonObject:
    """Validate a JSON object at the wire boundary."""
    if not isinstance(value, dict):
        raise DomainError(
            "upstream_schema", "The upstream returned an invalid object.", 502
        )
    return value


def token_count(value: JsonValue) -> int | None:
    """Accept only nonnegative integer usage supplied by the provider."""
    return value if type(value) is int and value >= 0 else None


def read_usage(raw: JsonObject, previous: Usage | None = None) -> Usage:
    """Merge partial usage events without inventing unavailable counts."""
    result = previous.model_copy(deep=True) if previous else Usage()
    for target, names in {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
    }.items():
        for name in names:
            count = token_count(raw.get(name))
            if count is not None:
                setattr(result, target, count)
                break
    output_detail = raw.get(
        "output_tokens_details", raw.get("completion_tokens_details")
    )
    input_detail = raw.get("input_tokens_details", raw.get("prompt_tokens_details"))
    if isinstance(output_detail, dict):
        result.reasoning_tokens = token_count(output_detail.get("reasoning_tokens"))
    if isinstance(input_detail, dict):
        result.cached_tokens = token_count(input_detail.get("cached_tokens"))
    if result.input_tokens is not None and result.output_tokens is not None:
        result.total_tokens = result.input_tokens + result.output_tokens
    return result


@dataclass
class StreamState:
    """Accumulate output while retaining an explicit terminal signal."""

    output: Output = field(default_factory=Output)
    complete: bool = False


class WireProtocol(Protocol):
    """Define request and response translation for one wire schema."""

    def payload(
        self, model: str, effort: str, prompt: str, settings: Settings
    ) -> JsonObject:
        """Build a single fresh-context request."""
        ...

    def event(self, event: JsonObject, state: StreamState) -> None:
        """Apply one semantic streaming event to the result."""
        ...

    def response(self, body: JsonObject, state: StreamState) -> None:
        """Decode a complete non-streaming response."""
        ...

    def headers(self, account: Account) -> dict[str, str]:
        """Create protocol authentication headers from server-held secrets."""
        ...


class ResponsesProtocol:
    """Implement OpenAI Responses including typed terminal events."""

    def payload(
        self, model: str, effort: str, prompt: str, settings: Settings
    ) -> JsonObject:
        """Use an isolated response with storage disabled."""
        result: JsonObject = {
            "model": model,
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": prompt}]}
            ],
            "stream": True,
            "store": False,
            "max_output_tokens": settings.max_output_tokens,
        }
        if effort != "default":
            result["reasoning"] = {"effort": effort}
        return result

    def headers(self, account: Account) -> dict[str, str]:
        """Authenticate API keys and source-owned OpenAI OAuth tokens."""
        credentials = account.credentials
        token = (
            credentials.access_token
            if account.account_type == "oauth"
            else credentials.api_key
        )
        result = {"Authorization": f"Bearer {token}"}
        if account.account_type == "oauth":
            result.update(
                {"Originator": "codex_cli_rs", "OpenAI-Beta": "responses=experimental"}
            )
            if credentials.chatgpt_account_id:
                result["ChatGPT-Account-Id"] = credentials.chatgpt_account_id
        return result

    def event(self, event: JsonObject, state: StreamState) -> None:
        """Keep output deltas separate from reasoning and terminal state."""
        kind = event.get("type")
        if kind == "response.output_text.delta":
            state.output.text += str(event.get("delta", ""))
        elif kind == "response.refusal.delta":
            state.output.text += str(event.get("delta", ""))
            state.output.finish_reason = "refusal"
        elif kind in {"response.completed", "response.incomplete", "response.failed"}:
            self.response(object_value(event.get("response")), state)
            if kind != "response.completed":
                state.output.finish_reason = str(kind).removeprefix("response.")
        elif kind == "error":
            raise DomainError(
                "upstream_error",
                str(event.get("message", "Upstream streaming error."))[:240],
                502,
            )

    def response(self, body: JsonObject, state: StreamState) -> None:
        """Aggregate text blocks across all output items."""
        blocks: list[str] = []
        items = body.get("output")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                contents = item.get("content")
                if not isinstance(contents, list):
                    continue
                for content in contents:
                    if (
                        isinstance(content, dict)
                        and content.get("type") == "output_text"
                    ):
                        blocks.append(str(content.get("text", "")))
                    elif isinstance(content, dict) and content.get("type") == "refusal":
                        blocks.append(str(content.get("refusal", "")))
                        state.output.finish_reason = "refusal"
        if blocks:
            state.output.text = "".join(blocks)
        if isinstance(body.get("usage"), dict):
            state.output.usage = read_usage(object_value(body["usage"]))
        state.complete = body.get("status") in {"completed", "incomplete", "failed"}
        if state.output.finish_reason != "refusal":
            state.output.finish_reason = str(body.get("status", "missing_terminal"))


class AnthropicProtocol:
    """Implement Anthropic Messages without translating reasoning settings blindly."""

    def payload(
        self, model: str, effort: str, prompt: str, settings: Settings
    ) -> JsonObject:
        """Build a fresh message with optional native output effort."""
        result: JsonObject = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": settings.max_output_tokens,
            "stream": True,
        }
        if effort != "default":
            if effort not in {"low", "medium", "high", "max"}:
                raise DomainError(
                    "effort_unsupported",
                    "This effort is not supported by Anthropic Messages.",
                )
            result["output_config"] = {"effort": effort}
        return result

    def headers(self, account: Account) -> dict[str, str]:
        """Use the Messages API authentication and version header."""
        return {
            "x-api-key": account.credentials.api_key,
            "anthropic-version": "2023-06-01",
        }

    def event(self, event: JsonObject, state: StreamState) -> None:
        """Merge initial and final usage and require message_stop."""
        kind = event.get("type")
        if kind == "message_start":
            message = object_value(event.get("message"))
            if isinstance(message.get("usage"), dict):
                state.output.usage = read_usage(object_value(message["usage"]))
        elif kind == "content_block_delta":
            delta = object_value(event.get("delta"))
            if delta.get("type") == "text_delta":
                state.output.text += str(delta.get("text", ""))
        elif kind == "message_delta":
            delta = object_value(event.get("delta"))
            state.output.finish_reason = str(delta.get("stop_reason", "unknown"))
            if isinstance(event.get("usage"), dict):
                state.output.usage = read_usage(
                    object_value(event["usage"]), state.output.usage
                )
        elif kind == "message_stop":
            state.complete = True
        elif kind == "error":
            error = object_value(event.get("error"))
            raise DomainError(
                "upstream_error",
                str(error.get("message", "Upstream streaming error."))[:240],
                502,
            )

    def response(self, body: JsonObject, state: StreamState) -> None:
        """Extract text content from a complete Messages response."""
        content = body.get("content")
        if isinstance(content, list):
            state.output.text = "".join(
                str(x.get("text", ""))
                for x in content
                if isinstance(x, dict) and x.get("type") == "text"
            )
        state.output.finish_reason = str(body.get("stop_reason", "missing_terminal"))
        state.complete = bool(body.get("stop_reason"))
        if isinstance(body.get("usage"), dict):
            state.output.usage = read_usage(object_value(body["usage"]))


class ChatProtocol:
    """Support explicitly selected Chat Completions compatibility endpoints."""

    def payload(
        self, model: str, effort: str, prompt: str, settings: Settings
    ) -> JsonObject:
        """Build one chat completion with reported stream usage."""
        result: JsonObject = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": settings.max_output_tokens,
        }
        if effort != "default":
            result["reasoning_effort"] = effort
        return result

    def headers(self, account: Account) -> dict[str, str]:
        """Use bearer authentication for compatible providers."""
        return {"Authorization": f"Bearer {account.credentials.api_key}"}

    def event(self, event: JsonObject, state: StreamState) -> None:
        """Read the primary choice and preserve its finish reason."""
        choices = event.get("choices")
        if isinstance(choices, list) and choices:
            choice = object_value(choices[0])
            delta = choice.get("delta", choice.get("message"))
            if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                state.output.text += str(delta["content"])
            if choice.get("finish_reason"):
                state.output.finish_reason = str(choice["finish_reason"])
                state.complete = True
        if isinstance(event.get("usage"), dict):
            state.output.usage = read_usage(
                object_value(event["usage"]), state.output.usage
            )

    def response(self, body: JsonObject, state: StreamState) -> None:
        """Decode the same primary-choice structure without streaming."""
        self.event(body, state)


def protocols() -> dict[str, WireProtocol]:
    """Register unique supported protocol implementations at startup."""
    return {
        "openai_responses": ResponsesProtocol(),
        "anthropic_messages": AnthropicProtocol(),
        "openai_chat": ChatProtocol(),
    }
