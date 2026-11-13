"""Verify local deletion, durable display ordering, and source-sync races."""

import asyncio
from pathlib import Path

import pytest
from conftest import FakeGateway, FakeSource, drain
from fastapi.testclient import TestClient
from test_auth_api import login
from test_service_worker import create_account, create_group
from test_source_sync import ChangingSource

from intelligence_degradation_detection.application.service import EvaluationService
from intelligence_degradation_detection.application.worker import Worker
from intelligence_degradation_detection.bootstrap import create_app
from intelligence_degradation_detection.domain.models import (
    Account,
    Call,
    DomainError,
    Group,
    GroupInput,
    Kind,
    Run,
    Target,
    TargetInput,
)


async def test_delete_account_retains_evidence_and_other_group_members(
    service: EvaluationService,
) -> None:
    """Remove owned configuration without altering another account or past snapshots."""
    first, second = create_account(service, "First"), create_account(service, "Second")
    solo = await create_group(service, first)
    shared = await service.save_group(
        GroupInput(
            name="Shared",
            kind=Kind.OTHER,
            prompt="Fixture",
            targets=[
                TargetInput(account_id=account.id, model="fixture-model")
                for account in (first, second)
            ],
        )
    )
    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    gateway.release.set()
    worker = Worker(service)
    try:
        await service.run_group(solo.id)
        await service.run_group(shared.id)
        await drain(worker)
        runs = service.repo.all(Run)
        calls = service.repo.all(Call)
        await service.delete_account(first.id)
        assert service.repo.all(Account) == [service.repo.get(Account, second.id)]
        assert service.repo.all(Target, account_id=first.id) == []
        remaining = service.repo.all(Group)
        assert len(remaining) == 1 and remaining[0].id == shared.id
        assert remaining[0].revision == shared.revision + 1
        assert [item.account_id for item in remaining[0].recipe.targets] == [second.id]
        assert service.repo.all(Run) == runs and service.repo.all(Call) == calls
        await service.run_group(shared.id)
        await drain(worker)
    finally:
        await worker.stop()


@pytest.mark.parametrize("running", [False, True])
@pytest.mark.parametrize("probe", [False, True])
async def test_delete_rejects_active_checks_and_probes_then_allows_cancelled_work(
    service: EvaluationService, running: bool, probe: bool
) -> None:
    """Do not orphan queued or active work; cancellation releases the delete guard."""
    account = create_account(service)
    group = await create_group(service, account)
    run = (
        await service.probe_account(account.id)
        if probe
        else await service.run_target(service.repo.all(Target, group_id=group.id)[0].id)
    )
    worker = Worker(service)
    try:
        if running:
            await worker.tick()
            assert isinstance(service.gateway, FakeGateway)
            await asyncio.wait_for(service.gateway.entered.wait(), timeout=2)
        with pytest.raises(DomainError, match="Cancel or wait"):
            await service.delete_account(account.id)
        assert service.repo.get(Account, account.id)
        assert service.repo.get(Group, group.id)
        await worker.cancel(run.id)
        await service.delete_account(account.id)
        assert not service.repo.all(Account)
        assert (
            service.repo.get(Run, run.id).snapshot.account_name == account.config.name
        )
    finally:
        await worker.stop()


@pytest.mark.parametrize("failed", [False, True])
async def test_sync_in_flight_does_not_restore_deleted_source_account(
    service: EvaluationService, monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    """Finish a pending source read safely after its local account was removed."""
    source = ChangingSource()
    service.source = source
    imported = await service.import_accounts([1, 2])
    account = next(item for item in imported if item.external_id == 1)
    remaining = next(item for item in imported if item.external_id == 2)
    await service.reorder_accounts([remaining.id, account.id])
    entered, release = asyncio.Event(), asyncio.Event()
    original = source.records[1].model_copy(deep=True)
    source.records[2].credentials.api_key = "fixture-updated"

    async def resolve(external_id: int) -> Account:
        if external_id == 2:
            return source.records[2].model_copy(deep=True)
        entered.set()
        await asyncio.wait_for(release.wait(), timeout=2)
        if failed:
            raise DomainError("source_failure", "Fixture source failed.")
        return original.model_copy(deep=True)

    monkeypatch.setattr(source, "resolve", resolve)
    sync = asyncio.create_task(service.sync_accounts())
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await service.delete_account(account.id)
        release.set()
        assert await asyncio.wait_for(sync, timeout=2) == {"updated": 1, "failed": 0}
        saved = service.repo.all(Account)
        assert len(saved) == 1 and saved[0].id == remaining.id
        assert saved[0].credentials.api_key == "fixture-updated"
        assert saved[0].sort_order == 0
        assert source.records[1] == original
    finally:
        release.set()
        await asyncio.gather(sync, return_exceptions=True)


def test_ordering_api_is_atomic_scoped_and_persists_across_restart(
    tmp_path: Path,
) -> None:
    """Reject stale lists and preserve durable order without rewriting recipes."""
    app = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    with TestClient(app) as client:
        for path in ("/accounts/order", "/groups/order/other"):
            assert client.put("/api/v1" + path, json={"ids": []}).status_code == 401
        assert client.delete("/api/v1/accounts/missing").status_code == 401
        login(client, tmp_path)
        accounts = [
            client.post(
                "/api/v1/accounts",
                json={"name": name, "api_key": "fixture-key"},
            ).json()["id"]
            for name in ("First", "Second", "Third")
        ]
        order = [accounts[2], accounts[0], accounts[1]]
        assert (
            client.put("/api/v1/accounts/order", json={"ids": order}).status_code == 204
        )
        for invalid in (order[:-1], [*order[:-1], order[0]], [*order, "missing"]):
            assert (
                client.put("/api/v1/accounts/order", json={"ids": invalid}).status_code
                == 409
            )
            assert [
                item["id"] for item in client.get("/api/v1/accounts").json()
            ] == order
        groups = {}
        for kind in Kind:
            ids = []
            for index in range(2):
                group = client.post(
                    "/api/v1/groups",
                    json={
                        "name": f"{kind}-{index}",
                        "kind": kind.value,
                        "prompt": "Fixture",
                        "targets": [
                            {"account_id": accounts[index], "model": "fixture"}
                        ],
                    },
                ).json()
                ids.append(group["id"])
            groups[kind] = ids
        before = {group["id"]: group for group in client.get("/api/v1/groups").json()}
        for kind, ids in groups.items():
            assert (
                client.put(
                    f"/api/v1/groups/order/{kind}", json={"ids": ids[::-1]}
                ).status_code
                == 204
            )
        assert (
            client.put(
                "/api/v1/groups/order/other", json={"ids": groups[Kind.COMPARISON]}
            ).status_code
            == 409
        )
        after = client.get("/api/v1/groups").json()
        assert {group["id"]: group for group in after} == before
        assert client.delete("/api/v1/accounts/missing").status_code == 404

    reopened = create_app(
        tmp_path, gateway=FakeGateway(), source=FakeSource(), start_worker=False
    )
    with TestClient(reopened) as client:
        login(client, tmp_path)
        assert [item["id"] for item in client.get("/api/v1/accounts").json()] == order
        for kind, ids in groups.items():
            assert [
                item["id"]
                for item in client.get("/api/v1/groups").json()
                if item["recipe"]["kind"] == kind
            ] == ids[::-1]
        added = client.post(
            "/api/v1/accounts", json={"name": "New", "api_key": "fixture-key"}
        ).json()
        assert client.get("/api/v1/accounts").json()[-1]["id"] == added["id"]
        assert client.delete(f"/api/v1/accounts/{accounts[0]}").status_code == 204
        assert all(
            target["account_id"] != accounts[0]
            for group in client.get("/api/v1/groups").json()
            for target in group["targets"]
        )
