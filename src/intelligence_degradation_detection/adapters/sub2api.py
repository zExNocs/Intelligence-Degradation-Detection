"""Read source-owned accounts and proxies without changing upstream state."""

from collections.abc import Callable

import httpx
from pydantic import JsonValue, ValidationError

from ..domain.models import (
    Account,
    AccountInput,
    Credentials,
    DomainError,
    Proxy,
    Settings,
    timestamp,
)
from .protocols import object_value


class Sub2APISource:
    """Translate validated administrative snapshots into internal accounts."""

    def __init__(
        self,
        settings: Callable[[], Settings],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Read current configuration for every operation and allow test transport."""
        self.settings = settings
        self.transport = transport

    async def _read(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> JsonValue:
        settings = self.settings()
        if not settings.sub2api_url or not settings.sub2api_key:
            raise DomainError(
                "source_unconfigured",
                "Configure the account source URL and administrator key first.",
            )
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
                timeout=20,
            ) as client:
                response = await client.get(
                    settings.sub2api_url.rstrip("/") + "/api/v1/admin" + path,
                    params=params,
                    headers={"x-api-key": settings.sub2api_key},
                )
                if response.status_code >= 300:
                    raise DomainError(
                        "source_not_found"
                        if response.status_code == 404
                        else "source_http",
                        f"Account source returned HTTP {response.status_code}.",
                        502,
                    )
                if len(response.content) > 16 * 1024 * 1024:
                    raise DomainError(
                        "source_size", "Account source response is too large.", 502
                    )
                body = object_value(response.json())
                if body.get("code", 0) != 0:
                    raise DomainError(
                        "source_rejected",
                        "Account source rejected the read request.",
                        502,
                    )
                return body.get("data", body)
        except (httpx.HTTPError, ValueError) as exc:
            raise DomainError(
                "source_unavailable",
                f"{type(exc).__name__}: account source unavailable.",
                502,
            ) from exc

    async def discover(self) -> list[dict[str, object]]:
        """Read every page before publishing a complete candidate list."""
        rows: list[dict[str, object]] = []
        seen: set[int] = set()
        expected_total: int | None = None
        for page in range(1, 101):
            data = await self._read("/accounts", {"page": page, "page_size": 100})
            entries = (
                data
                if isinstance(data, list)
                else object_value(data).get("items", object_value(data).get("accounts"))
            )
            total = (
                len(entries)
                if isinstance(data, list) and isinstance(entries, list)
                else object_value(data).get("total")
            )
            if not isinstance(entries, list) or type(total) is not int or total < 0:
                raise DomainError(
                    "source_incomplete", "Account source pagination is incomplete.", 502
                )
            if expected_total is not None and total != expected_total:
                raise DomainError(
                    "source_changed",
                    "Account list changed during synchronization.",
                    502,
                )
            expected_total = total
            for raw in entries:
                entry = object_value(raw)
                identity = entry.get("id")
                if type(identity) is not int or identity in seen:
                    raise DomainError(
                        "source_incomplete",
                        "Account identities are missing or duplicated.",
                        502,
                    )
                seen.add(identity)
                platform, auth_type = (
                    str(entry.get("platform", "")),
                    str(entry.get("type", "")),
                )
                supported = (
                    platform in {"openai", "anthropic"} and auth_type == "apikey"
                ) or (platform == "openai" and auth_type == "oauth")
                rows.append(
                    {
                        "id": identity,
                        "name": str(entry.get("name", identity)),
                        "platform": platform,
                        "type": auth_type,
                        "supported": supported,
                        "active": entry.get("status") == "active",
                    }
                )
            if len(seen) == expected_total:
                return rows
            if not entries or len(seen) > expected_total:
                break
        raise DomainError(
            "source_incomplete", "Account source did not return a complete list.", 502
        )

    async def resolve(self, external_id: int) -> Account:
        """Fetch one current credential bundle and its uniquely matched proxy."""
        try:
            state = object_value(await self._read(f"/accounts/{external_id}"))
        except DomainError as exc:
            if exc.code == "source_not_found":
                raise DomainError(
                    "source_missing", "The source account no longer exists."
                ) from exc
            raise
        if state.get("id", external_id) != external_id:
            raise DomainError(
                "source_identity", "Account identity changed during retrieval.", 502
            )
        platform, auth_type = str(state.get("platform", "")), str(state.get("type", ""))
        if not (
            (platform in {"openai", "anthropic"} and auth_type == "apikey")
            or (platform == "openai" and auth_type == "oauth")
        ):
            raise DomainError(
                "source_unsupported", "This source account type is not supported."
            )
        if state.get("status") != "active" or state.get("schedulable") is False:
            raise DomainError(
                "source_inactive", "The source account is disabled or unavailable."
            )
        bundle = object_value(
            await self._read(
                "/accounts/data", {"ids": str(external_id), "include_proxies": "true"}
            )
        )
        entries = bundle.get("accounts")
        if not isinstance(entries, list) or len(entries) != 1:
            raise DomainError(
                "source_identity",
                "The credential bundle does not identify one account.",
                502,
            )
        entry = object_value(entries[0])
        if (
            entry.get("name") != state.get("name")
            or entry.get("platform") != platform
            or entry.get("id", external_id) != external_id
        ):
            raise DomainError(
                "source_identity",
                "The credential bundle does not match the selected account.",
                502,
            )
        credentials = object_value(entry.get("credentials"))
        proxy = None
        proxy_name = None
        proxy_key = entry.get("proxy_key")
        if state.get("proxy_id") and not proxy_key:
            raise DomainError(
                "source_proxy",
                "The assigned proxy is absent from the credential bundle.",
                502,
            )
        if proxy_key:
            proxies = bundle.get("proxies")
            matches = (
                [
                    item
                    for item in proxies
                    if isinstance(item, dict) and item.get("proxy_key") == proxy_key
                ]
                if isinstance(proxies, list)
                else []
            )
            if len(matches) != 1:
                raise DomainError(
                    "source_proxy",
                    "The account proxy could not be resolved uniquely.",
                    502,
                )
            try:
                proxy_name = str(matches[0].get("name", "")) or None
                proxy = Proxy.model_validate(
                    {
                        key: matches[0].get(
                            key, "" if key in {"username", "password"} else None
                        )
                        for key in ("protocol", "host", "port", "username", "password")
                    }
                )
            except ValidationError as exc:
                raise DomainError(
                    "source_proxy", "The assigned proxy configuration is invalid.", 502
                ) from exc
        extra = state.get("extra")
        extra = extra if isinstance(extra, dict) else {}
        config = AccountInput(name=str(state.get("name", external_id)))
        if platform == "anthropic":
            config.protocol, config.base_url, config.path = (
                "anthropic_messages",
                "https://api.anthropic.com",
                "/v1/messages",
            )
        elif extra.get("openai_responses_supported") is False and auth_type != "oauth":
            config.protocol, config.path = "openai_chat", "/v1/chat/completions"
        if auth_type == "oauth":
            config.base_url, config.path, config.models_path = (
                "https://chatgpt.com",
                "/backend-api/codex/responses",
                "/backend-api/codex/models",
            )
        elif credentials.get("base_url"):
            config.base_url = str(credentials["base_url"]).rstrip("/")
            if config.base_url.endswith("/v1"):
                config.path = config.path.removeprefix("/v1")
                config.models_path = "/models"
        secret = Credentials(
            api_key=str(credentials.get("api_key", "")),
            access_token=str(credentials.get("access_token", "")),
            chatgpt_account_id=str(credentials.get("chatgpt_account_id", "")),
            proxy=proxy,
        )
        if not (secret.access_token if auth_type == "oauth" else secret.api_key):
            raise DomainError(
                "source_credentials",
                "The source account has no usable credential.",
                502,
            )
        proxy_id = state.get("proxy_id")
        return Account(
            config=config,
            credentials=secret,
            source="sub2api",
            external_id=external_id,
            source_proxy_id=proxy_id if type(proxy_id) is int else None,
            source_proxy_name=proxy_name,
            account_type=auth_type,
            synced_at=timestamp(),
        )
