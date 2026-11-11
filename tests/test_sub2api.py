"""Exercise administrative reads and source proxy consistency without a live server."""

import httpx
import pytest

from intelligence_degradation_detection.adapters.sub2api import Sub2APISource
from intelligence_degradation_detection.domain.models import DomainError, Settings


def source(handler) -> Sub2APISource:
    """Bind an isolated mock administrative endpoint."""
    return Sub2APISource(
        lambda: Settings(
            sub2api_url="https://source.invalid", sub2api_key="fixture-admin-key"
        ),
        httpx.MockTransport(handler),
    )


def bundle(proxy_key: str | None = "proxy-a", proxies: list | None = None) -> dict:
    """Return a source-owned credential bundle with an explicit proxy association."""
    return {
        "accounts": [
            {
                "id": 7,
                "name": "Source account",
                "platform": "openai",
                "credentials": {
                    "api_key": "upstream-fixture-key",
                    "base_url": "https://upstream.invalid/v1",
                },
                "proxy_key": proxy_key,
            }
        ],
        "proxies": proxies
        if proxies is not None
        else [
            {
                "proxy_key": "proxy-a",
                "protocol": "socks5",
                "host": "proxy.invalid",
                "port": 1080,
                "username": "user",
                "password": "private",
            }
        ],
    }


async def test_proxy_bundle_is_resolved_without_writes() -> None:
    """Preserve source routing and never send a mutation to the account server."""
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["x-api-key"] == "fixture-admin-key"
        paths.append(request.url.path)
        data = (
            bundle()
            if request.url.path.endswith("/data")
            else {
                "id": 7,
                "name": "Source account",
                "platform": "openai",
                "type": "apikey",
                "status": "active",
            }
        )
        return httpx.Response(200, json={"code": 0, "data": data})

    account = await source(handler).resolve(7)
    assert account.credentials.proxy.protocol == "socks5"
    assert account.credentials.proxy.password == "private"
    assert account.config.base_url == "https://upstream.invalid/v1"
    assert account.config.path == "/responses"
    assert paths == ["/api/v1/admin/accounts/7", "/api/v1/admin/accounts/data"]


@pytest.mark.parametrize("proxies", [[], [{"proxy_key": "wrong"}]])
async def test_missing_proxy_never_becomes_direct(proxies: list) -> None:
    """Fail closed when a selected proxy cannot be found in the snapshot."""

    def handler(request: httpx.Request) -> httpx.Response:
        data = (
            bundle(proxies=proxies)
            if request.url.path.endswith("/data")
            else {
                "id": 7,
                "name": "Source account",
                "platform": "openai",
                "type": "apikey",
                "status": "active",
            }
        )
        return httpx.Response(200, json={"data": data})

    with pytest.raises(DomainError, match="proxy"):
        await source(handler).resolve(7)


async def test_incomplete_pagination_is_rejected() -> None:
    """An incomplete source list must not appear to be a valid empty replacement."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        return httpx.Response(
            200,
            json={
                "data": {
                    "items": [
                        {
                            "id": 7,
                            "name": "Fixture",
                            "platform": "openai",
                            "type": "apikey",
                        }
                    ]
                    if page == "1"
                    else [],
                    "total": 2,
                }
            },
        )

    with pytest.raises(DomainError, match="complete"):
        await source(handler).discover()


async def test_deleted_account_is_distinguished_from_transient_outage() -> None:
    """Account deletion pauses future checks instead of repeatedly calling a missing route."""
    with pytest.raises(DomainError) as caught:
        await source(lambda request: httpx.Response(404)).resolve(7)
    assert caught.value.code == "source_missing"


async def test_missing_proxy_association_never_falls_back_to_direct() -> None:
    """An assigned proxy requires a matching bundle reference, not just a valid credential."""

    def handler(request: httpx.Request) -> httpx.Response:
        data = (
            bundle(proxy_key=None)
            if request.url.path.endswith("/data")
            else {
                "id": 7,
                "name": "Source account",
                "platform": "openai",
                "type": "apikey",
                "status": "active",
                "proxy_id": 9,
            }
        )
        return httpx.Response(200, json={"data": data})

    with pytest.raises(DomainError, match="proxy"):
        await source(handler).resolve(7)
