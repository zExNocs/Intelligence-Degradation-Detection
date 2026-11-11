"""Verify protocol parsing against realistic wire messages and terminal failures."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from intelligence_degradation_detection.adapters.gateway import (
    HttpModelGateway,
    proxy_address,
)
from intelligence_degradation_detection.domain.models import (
    Account,
    AccountInput,
    Credentials,
    DomainError,
    Output,
    Proxy,
    Settings,
)


def account(protocol: str = "openai_responses") -> Account:
    """Build a fixture account with a recognizable redaction sentinel."""
    return Account(
        config=AccountInput(
            name="Fixture", protocol=protocol, base_url="https://fixture.invalid"
        ),
        credentials=Credentials(api_key="fixture-private-key"),
    )


def stream(events: list[dict]) -> httpx.Response:
    """Encode semantic SSE events using normal blank-line boundaries."""
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(f"data: {json.dumps(event)}\n\n" for event in events),
    )


async def test_responses_collects_all_text_and_terminal_usage() -> None:
    """Ignore reasoning items, aggregate text blocks, and preserve usage and storage flags."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["reasoning"] == {"effort": "high"}
        return stream(
            [
                {"type": "response.output_text.delta", "delta": "part"},
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": [
                            {"type": "reasoning"},
                            {"content": [{"type": "output_text", "text": "A"}]},
                            {"content": [{"type": "output_text", "text": "B"}]},
                        ],
                        "usage": {
                            "input_tokens": 12,
                            "output_tokens": 20,
                            "output_tokens_details": {"reasoning_tokens": 7},
                        },
                    },
                },
            ]
        )

    progress: list[Output] = []
    output = await HttpModelGateway(httpx.MockTransport(handler)).invoke(
        account(), "fixture", "high", "prompt", Settings(), progress.append
    )
    assert output.text == "AB"
    assert output.usage.total_tokens == 32
    assert output.usage.reasoning_tokens == 7
    assert progress[-1].elapsed > 0


async def test_interrupted_stream_preserves_partial_evidence() -> None:
    """A text delta alone must never count as successful completion."""
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: stream(
                [{"type": "response.output_text.delta", "delta": "partial"}]
            )
        )
    )
    progress: list[Output] = []
    with pytest.raises(DomainError, match="without a terminal"):
        await gateway.invoke(
            account(), "fixture", "default", "prompt", Settings(), progress.append
        )
    assert progress[-1].text == "partial"
    assert progress[-1].usage.total_tokens is None


@pytest.mark.parametrize(
    "content_type", [None, "application/octet-stream", "application/json"]
)
async def test_sse_framing_does_not_require_a_content_type(
    content_type: str | None,
) -> None:
    """Read framed events when an intermediary omits or mislabels the media type."""
    completed = {
        "type": "response.completed",
        "response": {
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": "OK"}]}],
            "usage": {"input_tokens": 5, "output_tokens": 1},
        },
    }
    body = (
        "\ufeff: heartbeat\r\n\r\n"
        "event: response.output_text.delta\r\n"
        'data: {"type": "response.output_text.delta", "delta": "OK"}\r\n\r\n'
        f"data: {json.dumps(completed)}\r\n\r\ndata: [DONE]\r\n\r\n"
    )
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": content_type} if content_type else {},
                content=body.encode(),
            )
        )
    )
    result = await gateway.invoke(
        account(), "fixture", "default", "prompt", Settings(), lambda output: None
    )
    assert result.text == "OK"
    assert result.usage.total_tokens == 6
    assert result.first_token_seconds is not None


async def test_unlabelled_interrupted_stream_preserves_partial_output() -> None:
    """Detect framing without treating a truncated stream as a successful answer."""
    progress: list[Output] = []
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b'data: {"type":"response.output_text.delta","delta":"part"}\n\n',
            )
        )
    )
    with pytest.raises(DomainError, match="without a terminal"):
        await gateway.invoke(
            account(), "fixture", "default", "prompt", Settings(), progress.append
        )
    assert progress[-1].text == "part"


@pytest.mark.parametrize(
    "body",
    [b"data: {invalid}\n\n", b"<html>Not a model response</html>", b"{invalid}"],
)
async def test_malformed_unlabelled_responses_still_fail(body: bytes) -> None:
    """Reject broken JSON and unrelated documents without guessing an answer."""
    gateway = HttpModelGateway(
        httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )
    with pytest.raises(DomainError) as error:
        await gateway.invoke(
            account(), "fixture", "default", "prompt", Settings(), lambda output: None
        )
    assert error.value.code == "upstream_schema"


@pytest.mark.parametrize("streaming", [True, False])
async def test_unlabelled_chunked_data_preserves_unicode(streaming: bool) -> None:
    """Preserve multibyte text, JSON line separators and CRLF across tiny chunks."""
    text = "Chinese: 中文\u2028line\u2029paragraph"
    response = {
        "status": "completed",
        "output": [{"content": [{"type": "output_text", "text": text}]}],
    }
    if streaming:
        event = {"type": "response.completed", "response": response}
        body = (
            "\ufeffid: fixture\r\nretry: 1000\r\ndata:\r\n\r\n"
            f"data: {json.dumps(event, ensure_ascii=False)}\r\n\r\n"
        ).encode()
    else:
        body = (
            "\ufeff \r\n" + json.dumps(response, ensure_ascii=False, indent=2)
        ).encode()

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            """Split the BOM, UTF-8 characters and line endings at every byte."""
            for byte in body:
                yield bytes([byte])

    gateway = HttpModelGateway(
        httpx.MockTransport(lambda request: httpx.Response(200, stream=Chunks()))
    )
    result = await gateway.invoke(
        account(), "fixture", "default", "prompt", Settings(), lambda output: None
    )
    assert result.text == text


async def test_unlabelled_response_still_enforces_the_wire_size_limit() -> None:
    """Bound unframed input before attempting to decode a large document."""
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(200, content=b" " * (8 * 1024 * 1024 + 1))
        )
    )
    with pytest.raises(DomainError) as error:
        await gateway.invoke(
            account(), "fixture", "default", "prompt", Settings(), lambda output: None
        )
    assert error.value.code == "output_limit"


async def test_anthropic_usage_is_merged() -> None:
    """Merge message_start input usage with message_delta output usage."""
    events = [
        {
            "type": "message_start",
            "message": {"usage": {"input_tokens": 30, "output_tokens": 0}},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "hello"},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    output = await HttpModelGateway(
        httpx.MockTransport(lambda request: stream(events))
    ).invoke(
        account("anthropic_messages"),
        "fixture",
        "default",
        "prompt",
        Settings(),
        lambda output: None,
    )
    assert output.text == "hello"
    assert output.usage.total_tokens == 35


async def test_chat_json_and_secret_redaction() -> None:
    """Support non-streaming compatible servers while redacting rejected credentials."""
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]
                },
            )
        )
    )
    output = await gateway.invoke(
        account("openai_chat"),
        "fixture",
        "default",
        "prompt",
        Settings(),
        lambda output: None,
    )
    assert output.text == "OK" and output.usage.total_tokens is None
    rejected = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(
                401, json={"error": {"message": "Invalid fixture-private-key"}}
            )
        )
    )
    with pytest.raises(DomainError) as captured:
        await rejected.invoke(
            account(), "fixture", "default", "prompt", Settings(), lambda output: None
        )
    assert "fixture-private-key" not in str(captured.value)
    assert "HTTP 401" in str(captured.value)


def test_proxy_route_preserves_remote_dns_and_credentials() -> None:
    """Encode proxy credentials without changing the required remote-DNS route."""
    route = Proxy(
        protocol="socks5", host="::1", port=1080, username="a@b", password="p:q"
    )
    assert proxy_address(route) == "socks5h://a%40b:p%3Aq@[::1]:1080"


async def test_oauth_request_uses_subscription_route_contract() -> None:
    """Use source-owned OAuth credentials without injecting API-only parameters."""
    current = account()
    current.account_type = "oauth"
    current.credentials.access_token = "fixture-oauth-token"
    current.credentials.chatgpt_account_id = "fixture-owner"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "max_output_tokens" not in body
        assert request.headers["chatgpt-account-id"] == "fixture-owner"
        assert request.headers["authorization"] == "Bearer fixture-oauth-token"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": "OK"}]}],
            },
        )

    await HttpModelGateway(httpx.MockTransport(handler)).invoke(
        current, "fixture", "default", "prompt", Settings(), lambda output: None
    )


@pytest.mark.parametrize("effort", ["none", "minimal"])
async def test_incompatible_effort_never_reaches_upstream(effort: str) -> None:
    """Reject legacy invalid settings before creating a metered request."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400)

    with pytest.raises(DomainError, match="not supported"):
        await HttpModelGateway(httpx.MockTransport(handler)).invoke(
            account(), "gpt-6.1-sol", effort, "prompt", Settings(), lambda output: None
        )
    assert calls == []


async def test_upstream_default_effort_is_omitted() -> None:
    """Keep omission available for a model whose explicit effort set is restricted."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "reasoning" not in json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [{"content": [{"type": "output_text", "text": "OK"}]}],
            },
        )

    result = await HttpModelGateway(httpx.MockTransport(handler)).invoke(
        account(), "gpt-6.1-sol", "default", "prompt", Settings(), lambda output: None
    )
    assert result.text == "OK"


@pytest.mark.parametrize("auth_type", ["apikey", "oauth"])
async def test_catalogue_uses_account_specific_contract(auth_type: str) -> None:
    """Supply the required OAuth version without changing API-key catalogue URLs."""
    current = account()
    current.account_type = auth_type
    current.credentials.access_token = "fixture-oauth-token"
    current.credentials.chatgpt_account_id = "fixture-owner"
    current.config.models_path = "/models?custom=preserved"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["custom"] == "preserved"
        if auth_type == "oauth":
            assert request.url.params["client_version"]
            assert request.headers["authorization"] == "Bearer fixture-oauth-token"
            assert request.headers["chatgpt-account-id"] == "fixture-owner"
            return httpx.Response(200, json={"models": [{"slug": "fixture-model"}]})
        assert "client_version" not in request.url.params
        return httpx.Response(200, json={"data": [{"id": "fixture-model"}]})

    assert await HttpModelGateway(httpx.MockTransport(handler)).models(current) == [
        "fixture-model"
    ]


async def test_catalogue_errors_preserve_reason_and_redact_credentials() -> None:
    """Expose useful validation failures without echoing secrets from error messages."""
    current = account()
    current.credentials.chatgpt_account_id = "fixture-owner"
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={
                    "error": {
                        "message": "client_version required; fixture-private-key fixture-owner"
                    }
                },
            )
        )
    )
    with pytest.raises(DomainError) as captured:
        await gateway.models(current)
    assert "HTTP 400" in str(captured.value)
    assert "client_version required" in str(captured.value)
    assert "fixture-private-key" not in str(captured.value)
    assert "fixture-owner" not in str(captured.value)


@pytest.mark.parametrize("override", [None, "0.166.0"])
async def test_oauth_catalogue_version_exposes_selectable_models(
    override: str | None,
) -> None:
    """Prevent a successful but obsolete catalogue from exposing only review models."""
    current = account()
    current.account_type = "oauth"

    def handler(request: httpx.Request) -> httpx.Response:
        version = request.url.params["client_version"]
        if override:
            assert version == override
        models = [{"slug": "fixture-review", "visibility": "hide"}]
        if tuple(int(part) for part in version.split(".")) >= (0, 165, 0):
            models.extend(
                [
                    {"slug": "fixture-primary", "visibility": "list"},
                    {"slug": "fixture-secondary", "visibility": "list"},
                ]
            )
        return httpx.Response(200, json={"models": models})

    transport = httpx.MockTransport(handler)
    gateway = (
        HttpModelGateway(transport, codex_client_version=override)
        if override
        else HttpModelGateway(transport)
    )
    assert await gateway.models(current) == ["fixture-primary", "fixture-secondary"]


async def test_hidden_only_oauth_catalogue_is_reported_as_unusable() -> None:
    """Do not present an internal review model as the only available user model."""
    current = account()
    current.account_type = "oauth"
    gateway = HttpModelGateway(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"models": [{"slug": "fixture-review", "visibility": "hide"}]}
            )
        )
    )
    with pytest.raises(DomainError, match="no selectable models"):
        await gateway.models(current)


async def test_proxy_failure_does_not_retry_direct(monkeypatch) -> None:
    """Model and catalogue requests bind the same proxy and never retry without it."""
    current = account()
    current.credentials.proxy = Proxy(
        protocol="http",
        host="proxy.invalid",
        port=8080,
        username="fixture-user",
        password="fixture-password",
    )
    actual_client = httpx.AsyncClient
    routes = []

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("Fixture proxy unavailable")

    def client(**kwargs):
        routes.append(kwargs.pop("proxy"))
        assert kwargs["trust_env"] is False
        kwargs["transport"] = httpx.MockTransport(fail)
        return actual_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    gateway = HttpModelGateway()
    with pytest.raises(DomainError):
        await gateway.models(current)
    with pytest.raises(DomainError):
        await gateway.invoke(
            current, "fixture", "default", "prompt", Settings(), lambda output: None
        )
    assert routes == [proxy_address(current.credentials.proxy)] * 2
