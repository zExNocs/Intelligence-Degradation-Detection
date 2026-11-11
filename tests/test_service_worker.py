"""Exercise persistence, quotas, immutable snapshots, and observable task lifecycles."""

import asyncio

import pytest
from conftest import FakeGateway, drain

from intelligence_degradation_detection.application.service import EvaluationService
from intelligence_degradation_detection.application.worker import Worker
from intelligence_degradation_detection.domain.models import (
    Account,
    AccountInput,
    Call,
    DomainError,
    Group,
    GroupInput,
    Kind,
    Run,
    Status,
    Target,
    TargetInput,
    timestamp,
)


def create_account(
    service: EvaluationService, name: str = "Fixture", parallel: int = 1
) -> Account:
    """Create an account with a local-only fixture key."""
    return service.save_account(
        AccountInput(
            name=name,
            api_key="fixture-private-key",
            default_model="fixture-model",
            max_parallel=parallel,
        )
    )


async def create_group(
    service: EvaluationService,
    account: Account,
    kind: Kind = Kind.COMPARISON,
    parallel: bool = False,
) -> Group:
    """Create a real recipe using a predictable default answer."""
    return await service.save_group(
        GroupInput(
            name="Fixture group",
            kind=kind,
            prompt="A fixture prompt",
            expected_json=service.repo.settings().default_expected_json,
            parallel=parallel,
            targets=[TargetInput(account_id=account.id, model="fixture-model")],
        )
    )


async def test_batch_quota_rolls_back_every_record(service: EvaluationService) -> None:
    """A late batch quota violation must not leave partial groups or preference changes."""
    account = create_account(service)
    settings = service.repo.settings()
    settings.account_check_limit = 1
    service.repo.save_settings(settings)
    await create_group(service, account)
    second = create_account(service, "Second")
    with pytest.raises(DomainError, match="limit"):
        await service.save_group(
            GroupInput(
                name="Rejected",
                kind=Kind.OTHER,
                prompt="prompt",
                targets=[
                    TargetInput(account_id=second.id, model="new-model"),
                    TargetInput(account_id=account.id, model="overflow"),
                ],
            )
        )
    assert len(service.repo.all(Group)) == 1
    assert len(service.repo.all(Target)) == 1
    assert service.repo.get(Account, second.id).last_model is None


async def test_account_limits_and_global_fairness(service: EvaluationService) -> None:
    """Keep a busy account from blocking a ready call belonging to another account."""
    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    settings = service.repo.settings()
    settings.global_parallel = 2
    service.repo.save_settings(settings)
    first, second = create_account(service, "First"), create_account(service, "Second")
    groups = [
        await create_group(service, first),
        await create_group(service, first),
        await create_group(service, second),
    ]
    for group in groups:
        await service.run_group(group.id)
    worker = Worker(service)
    try:
        await worker.tick()
        await asyncio.wait_for(gateway.entered.wait(), 2)
        assert {identity for identity, _ in worker.tasks.values()} == {
            first.id,
            second.id,
        }
        assert len(service.repo.all(Call, status=Status.QUEUED)) == 1
        gateway.release.set()
        await asyncio.wait_for(
            asyncio.gather(*(task for _, task in list(worker.tasks.values()))), 5
        )
        await drain(worker)
        assert gateway.global_peak == 2
        assert gateway.peak[first.id] == gateway.peak[second.id] == 1
        assert all(run.status == Status.COMPLETED for run in service.repo.all(Run))
    finally:
        await worker.stop()


async def test_cancel_cleans_capacity_and_preserves_partial_usage(
    service: EvaluationService,
) -> None:
    """Cancellation must close the running invocation without converting it to success."""
    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    account = create_account(service)
    group = await create_group(service, account)
    target = service.repo.all(Target, group_id=group.id)[0]
    run = await service.run_target(target.id)
    worker = Worker(service)
    try:
        await worker.tick()
        await asyncio.wait_for(gateway.entered.wait(), 2)
        with pytest.raises(DomainError, match="already"):
            await service.run_target(target.id)
        cancelled = await worker.cancel(run.id)
        assert cancelled.status == Status.CANCELLED
        assert cancelled.output.usage.total_tokens == 30
        assert not worker.tasks and not sum(gateway.active.values())
        assert all(
            call.status == Status.CANCELLED
            for call in service.repo.all(Call, run_id=run.id)
        )
    finally:
        await worker.stop()


@pytest.mark.parametrize("parallel,expected", [(False, 1), (True, 3)])
async def test_fingerprint_parallelism_uses_real_slots(
    service: EvaluationService, parallel: bool, expected: int
) -> None:
    """Each selected fingerprint challenge consumes one account invocation slot."""
    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    gateway.text = " ".join(str(1 + index % 355) for index in range(340))
    account = create_account(service, parallel=3)
    group = await create_group(service, account, Kind.MODELTRACE, parallel)
    await service.run_group(group.id)
    worker = Worker(service)
    try:
        await worker.tick()
        await asyncio.wait_for(gateway.entered.wait(), 2)
        assert len(worker.tasks) == expected
        gateway.release.set()
        await drain(worker)
        assert len(gateway.calls) == 3
        result = service.repo.all(Run)[0]
        assert result.judgment.analysis["used_outputs"] == 3
        assert result.judgment.verdict == "reference"
    finally:
        await worker.stop()


async def test_snapshot_and_model_preferences_are_independent(
    service: EvaluationService,
) -> None:
    """Changing a recipe after enqueue must not rewrite stored prompts or selected models."""
    account = create_account(service)
    group = await create_group(service, account)
    await service.run_group(group.id)
    updated = group.recipe.model_copy(update={"prompt": "Changed prompt"})
    await service.save_group(updated, group.id)
    assert service.repo.all(Run)[0].snapshot.recipe.prompt == "A fixture prompt"
    assert service.repo.get(Account, account.id).last_model == "fixture-model"


async def test_due_overlap_is_skipped_without_moving_manual_schedule(
    service: EvaluationService,
) -> None:
    """An active check is not duplicated by either a manual or scheduled trigger."""
    account = create_account(service)
    group = await create_group(service, account)
    previous = group.next_run_at
    await service.run_group(group.id)
    assert service.repo.get(Group, group.id).next_run_at == previous
    group.next_run_at = timestamp() - 1
    service.repo.save(group)
    worker = Worker(service)
    try:
        await worker.tick()
        assert len(service.repo.all(Run)) == 1
        assert service.repo.get(Group, group.id).next_run_at > timestamp()
    finally:
        await worker.stop()


async def test_preview_catalogue_is_saved_without_an_extra_request(
    service: EvaluationService,
) -> None:
    """A successfully previewed unsaved account retains its catalogue after creation."""
    config = AccountInput(name="Preview", api_key="fixture-private-key")
    models = await service.preview_models(config)
    assert service.repo.all(Account) == []
    account = service.save_account(config)
    assert account.models == models
    assert account.config.api_key is None


async def test_retention_removes_owned_calls_but_not_active_work(
    service: EvaluationService,
) -> None:
    """Count retention cleans result bodies and child calls atomically."""
    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    gateway.release.set()
    account = create_account(service)
    group = await create_group(service, account)
    worker = Worker(service)
    try:
        for _ in range(3):
            await service.run_group(group.id)
            await drain(worker)
        settings = service.repo.settings()
        settings.retention_count = 1
        service.repo.save_settings(settings)
        await service.run_group(group.id)
        await worker.cleanup()
        assert len(service.repo.all(Run)) == 2
        assert len(service.repo.all(Call)) == 2
    finally:
        await worker.stop()


async def test_cancellation_before_first_task_step_releases_slot(
    service: EvaluationService,
) -> None:
    """A pre-start cancellation must not permanently consume dispatch capacity."""
    account = create_account(service)
    group = await create_group(service, account)
    runs = await service.run_group(group.id)
    worker = Worker(service)
    try:
        await worker.tick()
        await worker.cancel(runs["queued"][0])
        assert not worker.tasks
        assert service.repo.get(Run, runs["queued"][0]).status == Status.CANCELLED
        gateway = service.gateway
        assert isinstance(gateway, FakeGateway)
        gateway.release.set()
        await service.run_group(group.id)
        await drain(worker)
        assert len(gateway.calls) == 1
    finally:
        await worker.stop()


async def test_concurrent_group_creation_respects_account_limit(
    service: EvaluationService,
) -> None:
    """Competing requests cannot both reserve the last available account check."""
    account = create_account(service)
    settings = service.repo.settings()
    settings.account_check_limit = 1
    service.repo.save_settings(settings)
    results = await asyncio.gather(
        create_group(service, account),
        create_group(service, account),
        return_exceptions=True,
    )
    assert sum(isinstance(value, Group) for value in results) == 1
    assert sum(isinstance(value, DomainError) for value in results) == 1
    assert len(service.repo.all(Target)) == 1


async def test_evaluator_failure_finishes_run_and_releases_capacity(
    service: EvaluationService,
) -> None:
    """Unexpected evaluator errors must not leave an eternal running check."""

    class BrokenEvaluator:
        def evaluate(self, recipe, calls):
            raise ValueError("Fixture evaluator failure")

    gateway = service.gateway
    assert isinstance(gateway, FakeGateway)
    gateway.release.set()
    account = create_account(service)
    group = await create_group(service, account)
    worker = Worker(service)
    worker.evaluators[Kind.COMPARISON] = BrokenEvaluator()
    try:
        await service.run_group(group.id)
        await drain(worker)
        run = service.repo.all(Run)[0]
        assert run.status == Status.FAILED and run.finished_at is not None
        assert not worker.tasks
    finally:
        await worker.stop()
