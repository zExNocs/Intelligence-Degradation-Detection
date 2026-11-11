"""Execute bounded HTTP requests through explicit account-owned routes."""

import asyncio
import codecs
import json
import re
import ssl
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from ..domain.models import Account, DomainError, Output, Proxy, Settings
from ..domain.reasoning import validate_reasoning
from .protocols import StreamState, WireProtocol, object_value, protocols

# Pin the catalogue contract used by source-owned Codex OAuth accounts.
CODEX_CATALOGUE_VERSION = "0.165.0"


def proxy_address(proxy: Proxy | None) -> str | None:
    """Preserve proxy authentication and use remote DNS for SOCKS routes."""
    if proxy is None:
        return None
    protocol = "socks5h" if proxy.protocol == "socks5" else proxy.protocol
    host = f"[{proxy.host}]" if ":" in proxy.host else proxy.host
    auth = (
        f"{quote(proxy.username, safe='')}:{quote(proxy.password, safe='')}@"
        if proxy.username
        else ""
    )
    return f"{protocol}://{auth}{host}:{proxy.port}"


def sanitized(message: str, account: Account, prompt: str = "") -> str:
    """Remove account credentials and echoed prompt content from public errors."""
    sensitive = [
        account.credentials.api_key,
        account.credentials.access_token,
        account.credentials.chatgpt_account_id,
        *account.credentials.headers.values(),
        prompt,
    ]
    if account.credentials.proxy:
        sensitive.extend(
            [account.credentials.proxy.password, account.credentials.proxy.username]
        )
    for secret in sorted(filter(None, sensitive), key=len, reverse=True):
        message = message.replace(secret, "[redacted]")
    return " ".join(message.split())[:240]


async def consume_response(
    response: httpx.Response,
    protocol: WireProtocol,
    state: StreamState,
    start: float,
) -> None:
    """Read bounded JSON or SSE data even when its media type is missing.

    Recognize SSE field prefixes before decoding JSON. This only selects the
    transport framing; the explicitly selected model protocol remains unchanged.
    Keep terminal validation with the caller so a truncated stream cannot pass.
    """
    media_type = (
        response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
    )
    streaming: bool | None = True if media_type == "text/event-stream" else None
    data: list[bytes] = []
    buffer = bytearray()
    size = 0
    first_line = True

    def apply_event() -> None:
        """Decode a complete data frame and retain the first text arrival time."""
        frame = b"\n".join(data)
        data.clear()
        if frame and frame != b"[DONE]":
            protocol.event(object_value(json.loads(frame)), state)
        if state.output.text and state.output.first_token_seconds is None:
            state.output.first_token_seconds = time.monotonic() - start

    def apply_line(line: bytes) -> None:
        """Interpret SSE data fields while ignoring metadata and heartbeat comments."""
        nonlocal first_line
        if first_line:
            line = line.removeprefix(codecs.BOM_UTF8)
            first_line = False
        if line.startswith(b"data:"):
            data.append(line[5:].removeprefix(b" "))
        elif line == b"data":
            data.append(b"")
        elif not line and data:
            apply_event()

    def consume_lines(final: bool = False) -> None:
        """Split only SSE line endings, retaining partial UTF-8 and CRLF chunks."""
        offset = 0
        for match in re.finditer(rb"\r\n|\r|\n", buffer):
            if not final and match.group() == b"\r" and match.end() == len(buffer):
                break
            apply_line(bytes(buffer[offset : match.start()]))
            offset = match.end()
        del buffer[:offset]
        if final and buffer:
            apply_line(bytes(buffer))
            buffer.clear()

    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > 8 * 1024 * 1024:
            raise DomainError(
                "output_limit", "The upstream response exceeded the size limit.", 502
            )
        buffer.extend(chunk)
        if streaming is None:
            if codecs.BOM_UTF8.startswith(buffer):
                continue
            prefix = bytes(buffer).removeprefix(codecs.BOM_UTF8).lstrip(b" \t\r\n")
            fields = (b":",) + tuple(
                field + ending
                for field in (b"data", b"event", b"id", b"retry")
                for ending in (b":", b"\r", b"\n")
            )
            if prefix.startswith(fields):
                streaming = True
            elif not prefix or any(field.startswith(prefix) for field in fields):
                continue
            else:
                streaming = False
        if streaming:
            consume_lines()
        if len(state.output.text) > 2_000_000:
            raise DomainError(
                "output_limit", "The upstream response exceeded the size limit.", 502
            )
    if streaming:
        consume_lines(final=True)
        if data:
            apply_event()
    else:
        protocol.response(object_value(json.loads(buffer)), state)
    if len(state.output.text) > 2_000_000:
        raise DomainError(
            "output_limit", "The upstream response exceeded the size limit.", 502
        )


class HttpModelGateway:
    """Own short-lived HTTP clients whose route cannot fall back to direct access."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        ca_bundle: str | None = None,
        codex_client_version: str = CODEX_CATALOGUE_VERSION,
    ) -> None:
        """Register wire adapters and optional test transport or operator CA."""
        self.protocols: dict[str, WireProtocol] = protocols()
        self.transport = transport
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", codex_client_version):
            raise ValueError(
                "Codex catalogue client version must be a semantic version."
            )
        self.codex_client_version = codex_client_version
        self.verify = (
            ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
        )

    def client(self, account: Account) -> httpx.AsyncClient:
        """Create a client bound to exactly one account route."""
        return httpx.AsyncClient(
            transport=self.transport,
            proxy=proxy_address(account.credentials.proxy),
            trust_env=False,
            follow_redirects=False,
            verify=self.verify,
            timeout=httpx.Timeout(60, connect=15, pool=15, write=30),
        )

    def _headers(self, account: Account) -> dict[str, str]:
        result = {
            "Accept": "text/event-stream, application/json",
            "Content-Type": "application/json",
            "User-Agent": "Intelligence-Degradation-Detection/0.1",
        }
        for name, value in account.credentials.headers.items():
            if (
                name.lower()
                in {"host", "cookie", "authorization", "x-api-key", "content-length"}
                or "\n" in value
                or "\r" in value
            ):
                raise DomainError(
                    "header_invalid",
                    "A custom header conflicts with transport authentication.",
                )
            result[name] = value
        result.update(self.protocols[account.config.protocol].headers(account))
        return result

    async def invoke(
        self,
        account: Account,
        model: str,
        effort: str,
        prompt: str,
        settings: Settings,
        progress: Callable[[Output], None],
    ) -> Output:
        """Execute once and retain partial output on timeout or cancellation."""
        validate_reasoning(account.config.protocol, model, effort)
        protocol = self.protocols[account.config.protocol]
        payload = protocol.payload(model, effort, prompt, settings)
        if account.account_type == "oauth":
            payload.pop("max_output_tokens", None)
            payload["instructions"] = ""
        state = StreamState()
        start = time.monotonic()
        try:
            async with (
                asyncio.timeout(settings.call_timeout),
                self.client(account) as client,
            ):
                async with client.stream(
                    "POST",
                    account.config.base_url + account.config.path,
                    headers=self._headers(account),
                    json=payload,
                ) as response:
                    if response.status_code >= 300:
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk[: 4096 - len(body)])
                            if len(body) >= 4096:
                                break
                        detail = body.decode("utf-8", errors="replace")
                        try:
                            error = json.loads(detail)
                            if isinstance(error, dict):
                                nested = error.get("error", error)
                                if isinstance(nested, dict):
                                    detail = str(
                                        nested.get("message", "Request rejected.")
                                    )
                        except ValueError:
                            detail = "The upstream rejected this request."
                        raise DomainError(
                            "upstream_http",
                            f"HTTP {response.status_code}: {sanitized(detail, account, prompt)}",
                            502,
                        )
                    await consume_response(response, protocol, state, start)
            if not state.complete:
                raise DomainError(
                    "stream_interrupted",
                    "The upstream stream ended without a terminal response.",
                    502,
                )
            if state.output.finish_reason not in {
                "completed",
                "stop",
                "end_turn",
                "stop_sequence",
            }:
                raise DomainError(
                    "output_incomplete",
                    f"The upstream finished with: {state.output.finish_reason}.",
                    502,
                )
            if not state.output.text.strip():
                raise DomainError(
                    "empty_output", "The upstream returned no text output.", 502
                )
            return state.output
        except (httpx.HTTPError, TimeoutError) as exc:
            raise DomainError(
                "upstream_network",
                sanitized(f"{type(exc).__name__}: {exc}", account, prompt),
                502,
            ) from exc
        except (ValueError, UnicodeError) as exc:
            raise DomainError(
                "upstream_schema", "The upstream returned malformed response data.", 502
            ) from exc
        except DomainError as exc:
            raise DomainError(
                exc.code, sanitized(str(exc), account, prompt), exc.status
            ) from exc
        finally:
            state.output.elapsed = time.monotonic() - start
            progress(state.output.model_copy(deep=True))

    async def models(self, account: Account) -> list[str]:
        """Read a bounded model catalogue without discarding a caller's cache."""
        url = httpx.URL(account.config.base_url + account.config.models_path)
        if account.account_type == "oauth":
            url = url.copy_set_param("client_version", self.codex_client_version)
        try:
            async with self.client(account) as client:
                async with client.stream(
                    "GET",
                    url,
                    headers=self._headers(account),
                ) as response:
                    body = bytearray()
                    limit = 4096 if response.status_code >= 300 else 4 * 1024 * 1024
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk[: limit + 1 - len(body)])
                        if len(body) > limit:
                            if response.status_code >= 300:
                                break
                            raise DomainError(
                                "models_size",
                                "Model catalogue exceeded its size limit.",
                                502,
                            )
                if response.status_code >= 300:
                    detail = "The upstream rejected the model catalogue request."
                    try:
                        error = json.loads(body)
                        nested = (
                            error.get("error", error)
                            if isinstance(error, dict)
                            else None
                        )
                        if isinstance(nested, dict) and isinstance(
                            nested.get("message"), str
                        ):
                            detail = nested["message"]
                        elif isinstance(nested, str):
                            detail = nested
                    except ValueError:
                        pass  # HTML error pages are not safe or useful UI diagnostics.
                    raise DomainError(
                        "models_http",
                        f"Model catalogue returned HTTP {response.status_code}: "
                        f"{sanitized(detail, account)}",
                        502,
                    )
                document = object_value(json.loads(body))
                entries = document.get("data", document.get("models"))
                if not isinstance(entries, list):
                    raise DomainError(
                        "models_schema", "The response contains no model list.", 502
                    )
                identifiers = [
                    entry.get("id", entry.get("slug"))
                    for entry in entries
                    if isinstance(entry, dict)
                ]
                if any(not isinstance(value, str) for value in identifiers) or len(
                    identifiers
                ) != len(entries):
                    raise DomainError(
                        "models_schema",
                        "The model list contains an invalid entry.",
                        502,
                    )
                visible = sorted(
                    {
                        value
                        for entry, value in zip(entries, identifiers, strict=True)
                        if isinstance(value, str)
                        and isinstance(entry, dict)
                        and (
                            account.account_type != "oauth"
                            or entry.get("visibility", "list") == "list"
                        )
                    }
                )
                if account.account_type == "oauth" and entries and not visible:
                    raise DomainError(
                        "models_unavailable",
                        "The OAuth catalogue contains no selectable models. "
                        "Check the Codex catalogue client version and account access.",
                        502,
                    )
                return visible
        except (httpx.HTTPError, ValueError) as exc:
            raise DomainError(
                "models_network",
                sanitized(
                    f"{type(exc).__name__}: model catalogue unavailable.", account
                ),
                502,
            ) from exc
