"""Verify authenticated HTTP boundaries, redaction, and cancellation reporting."""

from pathlib import Path

import pytest
import yaml
from conftest import FakeGateway, FakeSource
from fastapi.testclient import TestClient
from test_source_sync import ChangingSource

from intelligence_degradation_detection.adapters.auth import TokenAuth
from intelligence_degradation_detection.bootstrap import create_app
from intelligence_degradation_detection.domain.models import DomainError, Run, Status


def login(client: TestClient, directory: Path) -> None:
    """Read only the isolated fixture token to establish a test session."""
    token = yaml.safe_load((directory / "yaml/auth.yaml").read_text())["access_token"]
    assert client.post("/api/v1/auth/session", json={"token": token}).status_code == 200


def test_source_route_verification_is_authenticated_redacted_and_unmetered(
    tmp_path: Path,
) -> None:
    """Show current source proxy metadata while preventing secret exposure or model calls."""
    source, gateway = ChangingSource(), FakeGateway()
    source.records[1].source_proxy_id = 9
    source.records[1].source_proxy_name = "Fixture route"
    app = create_app(tmp_path, gateway=gateway, source=source, start_worker=False)
    with TestClient(app) as client:
        assert client.post("/api/v1/accounts/unknown/route/verify").status_code == 401
        login(client, tmp_path)
        account = client.post(
            "/api/v1/sources/sub2api/import", json={"ids": [1]}
        ).json()[0]
        source.records[1].credentials.proxy.port = 8081
        response = client.post(f"/api/v1/accounts/{account['id']}/route/verify")
        assert response.status_code == 200
        assert response.json()["proxy"] == {
            "source_id": 9,
            "name": "Fixture route",
            "protocol": "http",
            "host": "proxy.invalid",
            "port": 8081,
            "authenticated": True,
        }
        assert (
            "fixture-password" not in response.text
            and "fixture-initial" not in response.text
        )
        assert "username" not in response.text and "password" not in response.text
        source.failed.add(1)
        assert (
            client.post(f"/api/v1/accounts/{account['id']}/route/verify").status_code
            >= 400
        )
        assert client.get("/api/v1/accounts").json()[0]["source_error"]
        assert not gateway.calls


def test_reasoning_policy_rejects_invalid_defaults_and_targets(tmp_path: Path) -> None:
    """Serve one policy to the UI and reject unsupported account and group settings."""
    app = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    route = (
        "/api/v1/models/reasoning-options?protocol=openai_responses&model=gpt-6.1-sol"
    )
    with TestClient(app) as client:
        assert client.get(route).status_code == 401
        login(client, tmp_path)
        assert client.get(route).json() == ["low", "medium", "high", "xhigh", "max"]
        config = {
            "name": "Reasoning",
            "api_key": "fixture-key",
            "default_model": "gpt-6.1-sol",
            "default_effort": "minimal",
        }
        assert client.post("/api/v1/accounts", json=config).status_code == 400
        config["default_effort"] = "low"
        account = client.post("/api/v1/accounts", json=config).json()
        recipe = {
            "name": "Reasoning check",
            "kind": "other",
            "prompt": "Fixture",
            "targets": [
                {
                    "account_id": account["id"],
                    "model": "gpt-6.1-sol",
                    "effort": "minimal",
                }
            ],
        }
        assert client.post("/api/v1/groups", json=recipe).status_code == 400
        recipe["targets"][0]["effort"] = "max"
        assert client.post("/api/v1/groups", json=recipe).status_code == 201


def test_token_creation_rotation_and_corruption(tmp_path: Path) -> None:
    """Preserve first-start tokens and revoke previous sessions after rotation."""
    path = tmp_path / "auth.yaml"
    auth = TokenAuth(path)
    original = auth.document.access_token
    assert TokenAuth(path).document.access_token == original
    session = auth.login(original)
    assert auth.verify(session)
    auth.rotate("a-completely-new-test-token-with-entropy")
    assert not auth.verify(session)
    with pytest.raises(DomainError):
        auth.login(original)
    path.write_text("broken: [", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Invalid authentication"):
        TokenAuth(path)
    assert path.read_text() == "broken: ["


def test_api_authentication_and_secret_allowlists(tmp_path: Path) -> None:
    """Reject unauthenticated access and never echo API keys in views or validation."""
    app = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    with TestClient(app) as client:
        for path in (
            "/api/v1/accounts",
            "/api/v1/settings",
            "/api/v1/dashboard",
            "/api/v1/openapi.json",
        ):
            assert client.get(path).status_code == 401
        login(client, tmp_path)
        response = client.post(
            "/api/v1/accounts",
            json={
                "name": "Fixture",
                "api_key": "fixture-private-value",
                "headers": {"x-fixture": "private-header-value"},
            },
        )
        assert response.status_code == 201
        assert "fixture-private-value" not in response.text
        assert "private-header-value" not in response.text
        invalid = client.post(
            "/api/v1/accounts", json={"name": "", "api_key": "fixture-private-value"}
        )
        assert (
            invalid.status_code == 422 and "fixture-private-value" not in invalid.text
        )
        assert (
            "HttpOnly"
            in client.post(
                "/api/v1/auth/session",
                json={"token": app.state.auth.document.access_token},
            ).headers["set-cookie"]
        )
        cross_origin = client.put(
            "/api/v1/auth/token",
            headers={"Origin": "https://untrusted.invalid"},
            json={"token": "some-other-fixture-token-value"},
        )
        assert cross_origin.status_code == 403
        assert (
            client.put(
                "/api/v1/auth/token",
                json={"token": "a-new-fixture-token-at-least-24-characters"},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/accounts").status_code == 401


def test_dashboard_excludes_cancelled_but_retains_history(tmp_path: Path) -> None:
    """A manually cancelled queued check must not alter dashboard metrics."""
    app = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    with TestClient(app) as client:
        login(client, tmp_path)
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Fixture", "api_key": "test-key", "default_model": "fixture"},
        ).json()
        group = client.post(
            "/api/v1/groups",
            json={
                "name": "Test",
                "kind": "other",
                "prompt": "hello",
                "targets": [{"account_id": account["id"], "model": "fixture"}],
            },
        ).json()
        result = client.post(f"/api/v1/groups/{group['id']}/run").json()
        identity = result["queued"][0]
        assert client.post(f"/api/v1/runs/{identity}/cancel").status_code == 200
        dashboard = client.get("/api/v1/dashboard").json()
        assert dashboard["runs_24h"] == 0 and dashboard["total_tokens"] == 0
        assert all(not items for items in dashboard["alerts"].values())
        detail = client.get(f"/api/v1/runs/{identity}").json()
        assert detail["status"] == "cancelled"
        assert detail["snapshot"]["recipe"]["prompt"] == "hello"
        history = client.get(f"/api/v1/groups/{group['id']}/history").json()
        assert history["runs"][0]["status"] == "cancelled"
        assert "snapshot" not in history["runs"][0]


def test_restart_marks_uncertain_calls_interrupted(tmp_path: Path) -> None:
    """A persisted in-flight request must not be automatically sent a second time."""
    first = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    with TestClient(first) as client:
        login(client, tmp_path)
        account = client.post(
            "/api/v1/accounts",
            json={"name": "Fixture", "api_key": "test-key", "default_model": "fixture"},
        ).json()
        result = client.post(f"/api/v1/accounts/{account['id']}/probe").json()
        identity = result["id"]
    gateway = FakeGateway()
    second = create_app(tmp_path, gateway=gateway, source=FakeSource())
    with TestClient(second):
        result = second.state.service.repo.get(Run, identity)
        assert result.status == Status.INTERRUPTED
        assert not gateway.calls


def test_prefixed_deployment_scopes_cookie_and_protects_both_path_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A proxy prefix must neither expose private endpoints nor leak session cookies to sibling apps."""
    monkeypatch.setenv("IDD_ROOT_PATH", "/evaluation")
    app = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    with TestClient(app, base_url="https://testserver") as client:
        for path in ("/api/v1/settings", "/evaluation/api/v1/settings"):
            assert client.get(path).status_code == 401
        token = app.state.auth.document.access_token
        response = client.post("/evaluation/api/v1/auth/session", json={"token": token})
        assert response.status_code == 200
        assert "Path=/evaluation/" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert client.get("/evaluation/api/v1/settings").status_code == 200
        assert client.delete("/evaluation/api/v1/auth/session").status_code == 204
        assert client.get("/evaluation/api/v1/settings").status_code == 401
