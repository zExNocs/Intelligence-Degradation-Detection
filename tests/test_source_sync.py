"""Verify atomic source snapshots and fail-closed invocation-time routing."""

import pytest
from conftest import FakeGateway, drain

from intelligence_degradation_detection.application.service import EvaluationService
from intelligence_degradation_detection.application.worker import Worker
from intelligence_degradation_detection.domain.models import (
    Account,
    AccountInput,
    Credentials,
    DomainError,
    GroupInput,
    Kind,
    Proxy,
    Run,
    Status,
    TargetInput,
)


class ChangingSource:
    """Expose source-owned changes without requiring a running account service."""

    def __init__(self) -> None:
        """Initialize two complete source records with an authenticated proxy."""
        self.failed: set[int] = set()
        self.records = {
            index: Account(
                source="sub2api",
                external_id=index,
                config=AccountInput(name=f"Source {index}"),
                credentials=Credentials(
                    api_key="fixture-initial",
                    proxy=Proxy(
                        protocol="http",
                        host="proxy.invalid",
                        port=8080,
                        username="fixture",
                        password="fixture-password",
                    ),
                ),
            )
            for index in (1, 2)
        }

    async def resolve(self, external_id: int) -> Account:
        """Return a complete snapshot or an explicit transport failure."""
        if external_id in self.failed:
            raise DomainError("source_proxy", "Fixture source proxy is unavailable.")
        return self.records[external_id].model_copy(deep=True)

    async def discover(self) -> list[dict[str, object]]:
        """Leave discovery outside this snapshot-specific fixture."""
        return []


async def test_incomplete_sync_retains_bundle_then_updates_credentials_and_proxy(
    service: EvaluationService,
) -> None:
    """Do not publish partial routing; preserve local preferences on a complete sync."""
    source = ChangingSource()
    service.source = source
    imported = await service.import_accounts([1, 2])
    first = next(item for item in imported if item.external_id == 1)
    (
        first.config.default_model,
        first.config.default_effort,
        first.config.max_parallel,
    ) = "preferred", "high", 3
    first.models, first.models_at = ["old-catalogue"], 1
    service.repo.save(first)
    source.records[1].credentials.api_key = "fixture-rotated"
    source.records[1].credentials.proxy.port = 8081
    source.failed.add(2)
    result = await service.sync_accounts()
    assert result == {"updated": 0, "failed": 1}
    retained = service.repo.get(Account, first.id)
    assert retained.credentials.api_key == "fixture-initial"
    assert retained.credentials.proxy.port == 8080
    source.failed.clear()
    assert await service.sync_accounts() == {"updated": 2, "failed": 0}
    updated = service.repo.get(Account, first.id)
    assert updated.credentials.api_key == "fixture-rotated"
    assert updated.credentials.proxy.port == 8081
    assert (
        updated.config.default_model,
        updated.config.default_effort,
        updated.config.max_parallel,
    ) == ("preferred", "high", 3)
    assert updated.models == [] and updated.models_at is None


async def test_failed_precall_resolution_never_invokes_gateway(
    service: EvaluationService,
) -> None:
    """A cached credential cannot bypass failed authoritative route confirmation."""
    source = ChangingSource()
    service.source = source
    account = (await service.import_accounts([1]))[0]
    group = await service.save_group(
        GroupInput(
            name="Source check",
            kind=Kind.OTHER,
            prompt="Fixture",
            targets=[TargetInput(account_id=account.id, model="fixture")],
        )
    )
    source.failed.add(1)
    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    gateway.release.set()
    worker = Worker(service)
    try:
        await service.run_group(group.id)
        await drain(worker)
        assert service.repo.all(Run)[0].status == Status.FAILED
        assert gateway.calls == []
        with pytest.raises(DomainError, match="proxy"):
            await service.refresh_models(account.id)
    finally:
        await worker.stop()


async def test_imported_editor_refresh_persists_shared_cache(
    service: EvaluationService,
) -> None:
    """Populate the shared catalogue before saving unrelated editor preferences."""
    source = ChangingSource()
    service.source = source
    account = (await service.import_accounts([1]))[0]
    assert await service.preview_models(account.config, account.id) == [
        "fixture-model",
        "fixture-second",
    ]
    cached = service.repo.get(Account, account.id)
    assert cached.models_at is not None and cached.models == [
        "fixture-model",
        "fixture-second",
    ]
    source.failed.add(1)
    with pytest.raises(DomainError):
        await service.preview_models(account.config, account.id)
    retained = service.repo.get(Account, account.id)
    assert retained.models == cached.models and retained.models_at == cached.models_at
    assert retained.models_error is not None
