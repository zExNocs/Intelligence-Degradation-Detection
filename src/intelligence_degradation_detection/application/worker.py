"""Dispatch persistent calls fairly and release capacity on every terminal path."""

import asyncio
import logging
from collections import Counter
from functools import partial

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..domain.models import (
    ACTIVE,
    Account,
    Call,
    DomainError,
    Group,
    Judgment,
    Kind,
    Output,
    Run,
    Status,
    Target,
    Usage,
    identifier,
    timestamp,
)
from .evaluators import evaluation_registry
from .schedules import next_occurrences
from .service import EvaluationService

logger = logging.getLogger(__name__)


class Worker:
    """Run one process-local dispatcher backed by durable SQLite call records."""

    def __init__(self, service: EvaluationService) -> None:
        """Bind an explicit service and initialize an empty active-task directory."""
        self.service = service
        self.repo = service.repo
        self.evaluators = evaluation_registry(service.fingerprint)
        self.tasks: dict[str, tuple[str, asyncio.Task[None]]] = {}
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.dispatch_lock = asyncio.Lock()
        self.last_account: str | None = None
        self.stopping = False

    async def start(self) -> None:
        """Recover queued work and mark uncertain in-flight requests interrupted."""
        with self.repo.transaction():
            for run in self.repo.all(Run, status=Status.RUNNING):
                run.status, run.finished_at, run.error = (
                    Status.INTERRUPTED,
                    timestamp(),
                    "The service restarted during this invocation; it was not retried.",
                )
                self.repo.save(run)
                for call in self.repo.all(Call, run_id=run.id):
                    if call.status in ACTIVE:
                        call.status = Status.INTERRUPTED
                        self.repo.save(call)
            for group in self.repo.all(Group):
                if group.recipe.enabled and (
                    group.next_run_at is None or group.next_run_at < timestamp()
                ):
                    group.next_run_at = next_occurrences(
                        group.recipe.cron, self.repo.settings().timezone
                    )[0]
                    self.repo.save(group)
        self.scheduler.add_job(
            self.tick,
            "interval",
            seconds=1,
            id="dispatch",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.service.sync_accounts,
            "interval",
            seconds=self.repo.settings().sync_seconds,
            id="source-sync",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self.cleanup,
            "interval",
            minutes=10,
            id="retention",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        await self.tick()

    def settings_changed(self) -> None:
        """Apply a new source-sync interval without restarting the scheduler."""
        if self.scheduler.running:
            self.scheduler.reschedule_job(
                "source-sync",
                trigger="interval",
                seconds=self.repo.settings().sync_seconds,
            )

    async def tick(self) -> None:
        """Enqueue due groups and select eligible calls without holding wait slots."""
        if self.stopping:
            return
        async with self.dispatch_lock:
            async with self.service.lock:
                now = timestamp()
                for group in self.repo.all(Group):
                    if (
                        not group.recipe.enabled
                        or group.next_run_at is None
                        or group.next_run_at > now
                    ):
                        continue
                    with self.repo.transaction():
                        batch = identifier()
                        for target in self.repo.all(Target, group_id=group.id):
                            try:
                                self.service.enqueue(target, batch)
                            except DomainError as exc:
                                if exc.code not in {"check_busy", "account_disabled"}:
                                    raise
                        group.next_run_at = next_occurrences(
                            group.recipe.cron, self.repo.settings().timezone, after=now
                        )[0]
                        self.repo.save(group)
            settings = self.repo.settings()
            occupied = Counter(
                account_id
                for account_id, task in self.tasks.values()
                if not task.done()
            )
            pending = self.repo.all(Call, status=Status.QUEUED)
            pending.sort(
                key=lambda call: (
                    call.account_id == self.last_account,
                    call.created_at,
                    call.order,
                )
            )
            for call in pending:
                if len(self.tasks) >= settings.global_parallel:
                    break
                account = self.repo.get(Account, call.account_id)
                if occupied[account.id] >= account.config.max_parallel:
                    continue
                run = self.repo.get(Run, call.run_id)
                if run.status not in ACTIVE:
                    call.status = Status.CANCELLED
                    self.repo.save(call)
                    continue
                if run.kind == Kind.MODELTRACE and not run.snapshot.recipe.parallel:
                    if any(
                        other.order < call.order and other.status in ACTIVE
                        for other in self.repo.all(Call, run_id=run.id)
                    ):
                        continue
                call.status = Status.RUNNING
                if run.status == Status.QUEUED:
                    run.status, run.started_at = Status.RUNNING, timestamp()
                with self.repo.transaction():
                    self.repo.save(call)
                    self.repo.save(run)
                task = asyncio.create_task(
                    self._execute(call.id), name=f"idd-call-{call.id}"
                )
                self.tasks[call.id] = (account.id, task)
                # A task cancelled before its first step never enters its finally block.
                task.add_done_callback(partial(self._forget, call.id))
                occupied[account.id] += 1
                self.last_account = account.id

    def _forget(self, identity: str, task: asyncio.Task[None]) -> None:
        self.tasks.pop(identity, None)

    async def _execute(self, identity: str) -> None:
        call = self.repo.get(Call, identity)
        run = self.repo.get(Run, call.run_id)

        def progress(output: Output) -> None:
            current = self.repo.get(Call, identity)
            current.output = output
            self.repo.save(current)

        try:
            account = await self.service.fresh_account(call.account_id)
            if account.config.protocol != run.snapshot.protocol:
                raise DomainError(
                    "route_changed",
                    "The account protocol changed after this check was queued.",
                )
            await self.service.gateway.invoke(
                account,
                run.snapshot.model,
                run.snapshot.effort,
                call.prompt,
                self.repo.settings().model_copy(
                    update={
                        "call_timeout": run.snapshot.call_timeout,
                        "max_output_tokens": run.snapshot.max_output_tokens,
                    }
                ),
                progress,
            )
            current = self.repo.get(Call, identity)
            if current.status == Status.RUNNING:
                current.status = Status.COMPLETED
                self.repo.save(current)
        except asyncio.CancelledError:
            current = self.repo.get(Call, identity)
            if current.status == Status.RUNNING:
                current.status = (
                    Status.INTERRUPTED if self.stopping else Status.CANCELLED
                )
                self.repo.save(current)
        except DomainError as exc:
            current = self.repo.get(Call, identity)
            if current.status == Status.RUNNING:
                current.status, current.error = Status.FAILED, str(exc)
                self.repo.save(current)
        except Exception:
            logger.exception("An evaluation failed unexpectedly")
            current = self.repo.get(Call, identity)
            if current.status == Status.RUNNING:
                current.status, current.error = (
                    Status.FAILED,
                    "An internal evaluation error occurred.",
                )
                self.repo.save(current)
        finally:
            try:
                await self._settle(call.run_id)
            except Exception:
                logger.exception("Result evaluation failed")
                current_run = self.repo.get(Run, call.run_id)
                if current_run.status in ACTIVE:
                    current_run.status = Status.FAILED
                    current_run.finished_at = timestamp()
                    current_run.error = (
                        "The output could not be evaluated due to an internal error."
                    )
                    self.repo.save(current_run)
            finally:
                self.tasks.pop(identity, None)

    async def _settle(self, identity: str) -> None:
        run = self.repo.get(Run, identity)
        calls = sorted(
            self.repo.all(Call, run_id=identity), key=lambda call: call.order
        )
        if any(call.status in ACTIVE for call in calls):
            return
        usage_fields = Usage.model_fields
        usage = {
            name: sum(values) if all(value is not None for value in values) else None
            for name in usage_fields
            for values in [[getattr(call.output.usage, name) for call in calls]]
        }
        run.output = Output(
            text="\n\n".join(call.output.text for call in calls),
            usage=Usage.model_validate(usage),
            elapsed=max(0, timestamp() - (run.started_at or timestamp())),
            finish_reason="completed"
            if all(call.status == Status.COMPLETED for call in calls)
            else "partial",
        )
        if run.status in {Status.CANCELLED, Status.INTERRUPTED}:
            self.repo.save(run)
            return
        if run.kind == Kind.MODELTRACE:
            judgment = await asyncio.to_thread(
                self.evaluators[Kind.MODELTRACE].evaluate, run.snapshot.recipe, calls
            )
            latest = self.repo.get(Run, identity)
            if latest.status == Status.CANCELLED:
                return
            run.judgment = judgment
            run.status = (
                Status.COMPLETED
                if all(call.status == Status.COMPLETED for call in calls)
                else Status.FAILED
            )
        elif all(call.status == Status.COMPLETED for call in calls):
            run.status = Status.COMPLETED
            run.judgment = (
                self.evaluators[Kind(run.kind)].evaluate(run.snapshot.recipe, calls)
                if run.kind != "probe"
                else Judgment(verdict="pass")
            )
        else:
            run.status = Status.INTERRUPTED if self.stopping else Status.FAILED
        run.finished_at = timestamp()
        run.error = next((call.error for call in calls if call.error), None)
        self.repo.save(run)

    async def cancel(self, identity: str) -> Run:
        """Cancel queued and active children before finalizing the parent record."""
        async with self.service.lock:
            run = self.repo.get(Run, identity)
            if run.status not in ACTIVE:
                raise DomainError(
                    "already_finished", "This check has already finished.", 409
                )
            waiting = []
            with self.repo.transaction():
                run.status, run.finished_at, run.error = (
                    Status.CANCELLED,
                    timestamp(),
                    "Cancelled manually.",
                )
                self.repo.save(run)
                for call in self.repo.all(Call, run_id=identity):
                    if call.status in ACTIVE:
                        call.status = Status.CANCELLED
                        self.repo.save(call)
                    if call.id in self.tasks:
                        task = self.tasks[call.id][1]
                        task.cancel()
                        waiting.append(task)
            if waiting:
                await asyncio.gather(*waiting, return_exceptions=True)
            await self._settle(identity)
            return self.repo.get(Run, identity)

    async def cleanup(self) -> None:
        """Apply age and count limits to terminal results and their owned calls."""
        settings = self.repo.settings()
        counts: Counter[str] = Counter()
        cutoff = timestamp() - settings.retention_days * 86400
        with self.repo.transaction():
            for run in self.repo.summaries():
                if run.status in ACTIVE:
                    continue
                key = run.target_id or f"probe:{run.account_id}"
                counts[key] += 1
                if run.created_at < cutoff or counts[key] > settings.retention_count:
                    self.repo.delete(Run, run.id)

    async def stop(self) -> None:
        """Stop scheduling and interrupt owned tasks before closing persistence."""
        self.stopping = True
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        waiting = [task for _, task in list(self.tasks.values())]
        for task in waiting:
            task.cancel()
        if waiting:
            await asyncio.gather(*waiting, return_exceptions=True)
        with self.repo.transaction():
            for run in self.repo.all(Run, status=Status.RUNNING):
                run.status, run.finished_at, run.error = (
                    Status.INTERRUPTED,
                    timestamp(),
                    "The service stopped during this invocation; it was not retried.",
                )
                self.repo.save(run)
                for call in self.repo.all(Call, run_id=run.id):
                    if call.status in ACTIVE:
                        call.status = Status.INTERRUPTED
                        self.repo.save(call)
