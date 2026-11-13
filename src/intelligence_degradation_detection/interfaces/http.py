"""Expose authenticated JSON operations and safe result projections."""

from fastapi import APIRouter, Query, Response

from ..application.schedules import next_occurrences
from ..application.service import EvaluationService
from ..application.worker import Worker
from ..domain.models import (
    ACTIVE,
    Account,
    AccountInput,
    Challenge,
    DomainError,
    Group,
    GroupInput,
    Kind,
    Run,
    Settings,
    Status,
    Target,
    timestamp,
)
from ..domain.reasoning import reasoning_options
from .schemas import (
    AccountView,
    CronInput,
    DashboardView,
    GroupView,
    HistoryPage,
    ImportInput,
    OrderInput,
    ReviewInput,
    RunDetail,
    SettingsInput,
    SettingsView,
)


def api_router(service: EvaluationService, worker: Worker) -> APIRouter:
    """Bind HTTP handlers to explicit use-case dependencies."""
    router = APIRouter(prefix="/api/v1")
    repo = service.repo

    @router.get("/models/reasoning-options", response_model=list[str])
    async def model_reasoning_options(
        protocol: str = Query(max_length=64), model: str = Query(max_length=250)
    ) -> list[str]:
        """Share the same model policy used to validate saved and executed checks."""
        return reasoning_options(protocol, model)

    @router.get("/accounts", response_model=list[AccountView])
    async def accounts() -> list[AccountView]:
        """List account metadata without credentials."""
        return [
            AccountView.from_account(account)
            for account in sorted(repo.all(Account), key=lambda item: item.sort_order)
        ]

    @router.put("/accounts/order", status_code=204)
    async def order_accounts(value: OrderInput) -> Response:
        """Save account card order independently of provider configuration."""
        await service.reorder_accounts(value.ids)
        return Response(status_code=204)

    @router.post("/accounts", response_model=AccountView, status_code=201)
    async def create_account(value: AccountInput) -> AccountView:
        """Create one direct account."""
        return AccountView.from_account(service.save_account(value))

    @router.post("/accounts/models/preview", response_model=list[str])
    async def preview_models(
        value: AccountInput, account_id: str | None = None
    ) -> list[str]:
        """Fetch models for an unsaved form without persisting its credentials."""
        return await service.preview_models(value, account_id)

    @router.put("/accounts/{identity}", response_model=AccountView)
    async def update_account(identity: str, value: AccountInput) -> AccountView:
        """Edit account preferences while preserving omitted secrets."""
        return AccountView.from_account(service.save_account(value, identity))

    @router.delete("/accounts/{identity}", status_code=204)
    async def delete_account(identity: str) -> Response:
        """Delete an idle local account and checks, preserving historical evidence."""
        await service.delete_account(identity)
        return Response(status_code=204)

    @router.post("/accounts/{identity}/models/refresh", response_model=AccountView)
    async def refresh_models(identity: str) -> AccountView:
        """Refresh a catalogue explicitly through its authoritative route."""
        return AccountView.from_account(await service.refresh_models(identity))

    @router.post("/accounts/{identity}/probe", response_model=Run, status_code=202)
    async def probe(identity: str) -> Run:
        """Queue a metered connectivity probe using the account defaults."""
        run = await service.probe_account(identity)
        await worker.tick()
        return run

    @router.post("/accounts/{identity}/route/verify", response_model=AccountView)
    async def verify_route(identity: str) -> AccountView:
        """Re-read source credentials and proxy association without calling a model."""
        return AccountView.from_account(await service.fresh_account(identity))

    @router.get("/accounts/{identity}/probes", response_model=list[Run])
    async def probe_history(identity: str) -> list[Run]:
        """Return a small history of connectivity checks for this account."""
        return repo.all(Run, account_id=identity, kind="probe")[-5:]

    @router.get("/sources/sub2api/accounts")
    async def source_accounts() -> list[dict[str, object]]:
        """Discover supported and unsupported accounts without importing them."""
        return await service.source.discover()

    @router.post("/sources/sub2api/import", response_model=list[AccountView])
    async def import_accounts(value: ImportInput) -> list[AccountView]:
        """Import only explicitly selected source accounts."""
        return [
            AccountView.from_account(account)
            for account in await service.import_accounts(value.ids)
        ]

    @router.post("/sources/sub2api/sync")
    async def sync_accounts() -> dict[str, int]:
        """Synchronize source-owned credentials and proxies immediately."""
        return await service.sync_accounts()

    @router.get("/groups", response_model=list[GroupView])
    async def groups() -> list[GroupView]:
        """List recipes and stable check identities."""
        return [
            GroupView(
                id=group.id,
                recipe=group.recipe,
                revision=group.revision,
                next_run_at=group.next_run_at,
                targets=repo.all(Target, group_id=group.id),
                active_runs={
                    run.target_id: run.id
                    for run in service.active_runs(group_id=group.id)
                    if run.target_id
                },
            )
            for group in sorted(repo.all(Group), key=lambda item: item.sort_order)
        ]

    @router.put("/groups/order/{kind}", status_code=204)
    async def order_groups(kind: Kind, value: OrderInput) -> Response:
        """Save card order for one detector without altering schedules or history."""
        await service.reorder_groups(kind, value.ids)
        return Response(status_code=204)

    @router.post("/groups", response_model=Group, status_code=201)
    async def create_group(value: GroupInput) -> Group:
        """Create a quota-checked batch of account evaluations."""
        return await service.save_group(value)

    @router.put("/groups/{identity}", response_model=Group)
    async def update_group(identity: str, value: GroupInput) -> Group:
        """Version a recipe without modifying historical run snapshots."""
        return await service.save_group(value, identity)

    @router.delete("/groups/{identity}", status_code=204)
    async def delete_group(identity: str) -> Response:
        """Remove an idle group and its checks while retaining historical records."""
        repo.get(Group, identity)
        if service.active_runs(group_id=identity):
            raise DomainError(
                "group_busy", "Cancel active checks before deleting the group.", 409
            )
        with repo.transaction():
            for target in repo.all(Target, group_id=identity):
                repo.delete(Target, target.id)
            repo.delete(Group, identity)
        return Response(status_code=204)

    @router.post("/groups/{identity}/run", status_code=202)
    async def run_group(identity: str) -> dict[str, list[str]]:
        """Create one aligned batch without changing the cron schedule."""
        repo.get(Group, identity)
        result = await service.run_group(identity)
        await worker.tick()
        return result

    @router.post("/targets/{identity}/run", response_model=Run, status_code=202)
    async def run_target(identity: str) -> Run:
        """Queue a single check unless it already has an active run."""
        result = await service.run_target(identity)
        await worker.tick()
        return result

    @router.get("/groups/{identity}/history", response_model=HistoryPage)
    async def history(
        identity: str, offset: int = Query(0, ge=0), limit: int = Query(5, ge=1, le=30)
    ) -> HistoryPage:
        """Page complete batch columns while keeping account rows aligned."""
        rows = repo.summaries(group_id=identity)
        batches = list(dict.fromkeys(run.batch_id for run in rows))
        selected = batches[offset : offset + limit]
        return HistoryPage(
            batches=selected,
            runs=[run for run in rows if run.batch_id in selected],
            has_more=offset + limit < len(batches),
            total_batches=len(batches),
        )

    @router.get("/runs/{identity}", response_model=RunDetail)
    async def run_detail(identity: str) -> RunDetail:
        """Read raw output only when a user opens result details."""
        from ..domain.models import Call

        run = repo.get(Run, identity)
        return RunDetail(
            **run.model_dump(),
            calls=sorted(repo.all(Call, run_id=identity), key=lambda call: call.order),
        )

    @router.post("/runs/{identity}/cancel", response_model=Run)
    async def cancel_run(identity: str) -> Run:
        """Stop work and exclude the cancelled result from dashboard metrics."""
        return await worker.cancel(identity)

    @router.put("/runs/{identity}/review", response_model=Run)
    async def review(identity: str, value: ReviewInput) -> Run:
        """Set or clear a human quality judgment."""
        return service.review_run(identity, value.verdict, value.note)

    @router.get("/fingerprint/challenges", response_model=list[Challenge])
    async def challenges() -> list[Challenge]:
        """Read the immutable named fingerprint prompts."""
        return service.fingerprint.challenges

    @router.get("/fingerprint/catalog")
    async def fingerprint_catalog() -> dict[str, object]:
        """Describe actual loaded candidates and their fixed bank version."""
        return {
            "version": service.fingerprint.version,
            "models": service.fingerprint.models,
            "method": "closed_set_numeric_fingerprint",
        }

    @router.post("/schedules/preview")
    async def schedule_preview(value: CronInput) -> dict[str, list[float]]:
        """Validate a five-field cron and preview its next five occurrences."""
        Settings.validate_timezone(value.timezone)
        return {"occurrences": next_occurrences(value.expression, value.timezone, 5)}

    @router.get("/clock")
    async def clock() -> dict[str, object]:
        """Provide a server time anchor for browser-independent countdowns."""
        return {"now": timestamp(), "timezone": repo.settings().timezone}

    @router.get("/settings", response_model=SettingsView)
    async def settings() -> SettingsView:
        """Return defaults without revealing the administrator key."""
        current = repo.settings()
        return SettingsView(
            **current.model_dump(exclude={"sub2api_key"}),
            has_sub2api_key=bool(current.sub2api_key),
        )

    @router.put("/settings", response_model=SettingsView)
    async def update_settings(value: SettingsInput) -> SettingsView:
        """Apply global defaults while preserving an omitted source key."""
        current = repo.settings()
        payload = value.model_dump()
        if "sub2api_key" not in value.model_fields_set:
            payload["sub2api_key"] = current.sub2api_key
        updated = Settings.model_validate(payload)
        if updated.sub2api_url != current.sub2api_url and repo.all(
            Account, source="sub2api"
        ):
            raise DomainError(
                "source_in_use",
                "The source URL cannot change while imported accounts exist.",
                409,
            )
        service.update_settings(updated)
        worker.settings_changed()
        await worker.cleanup()
        return SettingsView(
            **updated.model_dump(exclude={"sub2api_key"}),
            has_sub2api_key=bool(updated.sub2api_key),
        )

    @router.get("/dashboard", response_model=DashboardView)
    async def dashboard() -> DashboardView:
        """Aggregate non-cancelled results and classify current findings separately."""
        all_rows = [run for run in repo.summaries() if run.status != Status.CANCELLED]
        recent = [
            run
            for run in all_rows
            if run.created_at >= timestamp() - 86400 and run.status not in ACTIVE
        ]
        complete = [run for run in recent if run.status == Status.COMPLETED]
        alerts: dict[str, list] = {
            "quality": [],
            "identity": [],
            "manual": [],
            "operational": [],
        }
        seen: set[str] = set()
        for run in all_rows:
            key = run.target_id or f"probe:{run.account_id}"
            if key in seen or run.status in ACTIVE:
                continue
            seen.add(key)
            if run.status in {Status.FAILED, Status.INTERRUPTED}:
                alerts["operational"].append(run)
            elif run.review == "fail":
                alerts["manual"].append(run)
            elif run.verdict == "suspected_mismatch":
                alerts["identity"].append(run)
            elif run.verdict in {"fail", "format_error"}:
                alerts["quality"].append(run)
            elif run.verdict in {"incomplete", "evaluation_error"}:
                alerts["operational"].append(run)
        return DashboardView(
            account_count=len(repo.all(Account)),
            check_count=len(repo.all(Target)),
            runs_24h=len(recent),
            completed_24h=len(complete),
            total_tokens=sum(run.total_tokens or 0 for run in recent),
            unknown_usage_count=sum(run.total_tokens is None for run in recent),
            average_seconds=sum(run.elapsed for run in recent) / len(recent)
            if recent
            else None,
            success_rate=len(complete) / len(recent) if recent else None,
            alerts=alerts,
        )

    return router
