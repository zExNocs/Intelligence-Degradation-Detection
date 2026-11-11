"""Provide isolated storage and observable network-free model fixtures."""

import asyncio
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from intelligence_degradation_detection.adapters.modeltrace import ModelTraceEvaluator
from intelligence_degradation_detection.adapters.storage import SQLiteRepository
from intelligence_degradation_detection.application.service import EvaluationService
from intelligence_degradation_detection.application.worker import Worker
from intelligence_degradation_detection.domain.models import (
    Account,
    DomainError,
    Output,
    Settings,
    Usage,
)


class FakeGateway:
    """Expose observable invocation gates for deterministic concurrency tests."""

    def __init__(self) -> None:
        """Initialize independent counters and a closed completion gate."""
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[tuple[str, str, str]] = []
        self.active: Counter[str] = Counter()
        self.peak: Counter[str] = Counter()
        self.global_peak = 0
        self.text = '{"evens":[2,4,6,8,10],"sum_of_squares":220,"count":5}'

    async def invoke(
        self,
        account: Account,
        model: str,
        effort: str,
        prompt: str,
        settings: Settings,
        progress: Callable[[Output], None],
    ) -> Output:
        """Wait for an explicit release while recording actual overlap."""
        self.calls.append((account.id, model, prompt))
        self.active[account.id] += 1
        self.peak[account.id] = max(self.peak[account.id], self.active[account.id])
        self.global_peak = max(self.global_peak, sum(self.active.values()))
        self.entered.set()
        output = Output(
            text=self.text,
            usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
            elapsed=0.1,
            finish_reason="completed",
        )
        try:
            await asyncio.wait_for(self.release.wait(), timeout=5)
            return output
        finally:
            self.active[account.id] -= 1
            progress(output)

    async def models(self, account: Account) -> list[str]:
        """Return a deterministic catalogue without generating text."""
        return ["fixture-model", "fixture-second"]


class FakeSource:
    """Fail closed when an unexpected source call occurs in an ordinary test."""

    async def discover(self) -> list[dict[str, object]]:
        """Return an empty configured source list."""
        return []

    async def resolve(self, external_id: int) -> Account:
        """Reject accidental source access instead of returning direct credentials."""
        raise DomainError("source_unavailable", "Fixture source is unavailable.")


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[SQLiteRepository]:
    """Close the per-test engine after every success and failure path."""
    repo = SQLiteRepository(tmp_path / "data.sqlite3")
    try:
        yield repo
    finally:
        repo.close()


@pytest.fixture
def fingerprint() -> ModelTraceEvaluator:
    """Load the actual pinned inference bank without external services."""
    return ModelTraceEvaluator()


@pytest.fixture
def service(
    repository: SQLiteRepository, fingerprint: ModelTraceEvaluator
) -> EvaluationService:
    """Compose real application logic with explicit network substitutes."""
    return EvaluationService(repository, FakeGateway(), FakeSource(), fingerprint)


async def drain(worker: Worker, rounds: int = 10) -> None:
    """Await observable task completions under a bounded number of dispatch rounds."""
    for _ in range(rounds):
        await worker.tick()
        tasks = [task for _, task in worker.tasks.values()]
        if not tasks:
            return
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
    raise AssertionError("The fixture worker did not become idle.")
