"""Coordinate transactional account, recipe, and evaluation operations."""

import asyncio
import hashlib
import json
from collections import Counter
from typing import Literal

from ..domain.models import (
    ACTIVE,
    Account,
    AccountInput,
    Call,
    DomainError,
    Group,
    GroupInput,
    Kind,
    Run,
    Settings,
    Snapshot,
    Status,
    Target,
    TargetInput,
    identifier,
    timestamp,
)
from ..domain.reasoning import validate_reasoning
from ..domain.scoring import parse_json, validate_regex
from .ports import AccountSource, FingerprintEngine, ModelGateway, Repository
from .schedules import next_occurrences


class EvaluationService:
    """Own user operations while depending only on replaceable capabilities."""

    def __init__(
        self,
        repository: Repository,
        gateway: ModelGateway,
        source: AccountSource,
        fingerprint: FingerprintEngine,
    ) -> None:
        """Receive every infrastructure dependency explicitly."""
        self.repo = repository
        self.gateway = gateway
        self.source = source
        self.fingerprint = fingerprint
        self.lock = asyncio.Lock()
        self.model_previews: dict[str, tuple[list[str], float]] = {}

    def save_account(
        self, config: AccountInput, identity: str | None = None
    ) -> Account:
        """Create or edit preferences without leaking credentials into public config."""
        with self.repo.transaction():
            account = (
                self.repo.get(Account, identity)
                if identity
                else Account(config=config.model_copy(deep=True))
            )
            if identity is None:
                account.sort_order = 1 + max(
                    (item.sort_order for item in self.repo.all(Account)), default=0
                )
            if account.source == "sub2api":
                config = config.model_copy(
                    update={
                        "protocol": account.config.protocol,
                        "base_url": account.config.base_url,
                        "path": account.config.path,
                        "models_path": account.config.models_path,
                        "api_key": None,
                        "headers": None,
                    }
                )
            else:
                if config.api_key is not None:
                    account.credentials.api_key = config.api_key
                if config.headers is not None:
                    if any(
                        name.lower()
                        in {
                            "authorization",
                            "x-api-key",
                            "host",
                            "cookie",
                            "content-length",
                        }
                        or "\n" in name
                        or "\r" in name
                        or "\n" in value
                        or "\r" in value
                        for name, value in config.headers.items()
                    ):
                        raise DomainError(
                            "header_invalid",
                            "Custom headers may not override authentication or transport headers.",
                        )
                    account.credentials.headers = config.headers
                if not account.credentials.api_key:
                    raise DomainError("credential_required", "An API key is required.")
            if (
                account.config.base_url,
                account.config.models_path,
                account.config.protocol,
            ) != (config.base_url, config.models_path, config.protocol):
                account.models, account.models_at = [], None
            account.config = config.model_copy(
                update={"api_key": None, "headers": None}
            )
            if config.enabled and config.default_model:
                validate_reasoning(
                    config.protocol, config.default_model, config.default_effort
                )
            preview = self.model_previews.get(self._catalog_key(account))
            if preview and preview[1] > timestamp() - 900:
                account.models, account.models_at, account.models_error = (
                    preview[0],
                    preview[1],
                    None,
                )
            self.repo.save(account)
            return account

    async def delete_account(self, identity: str) -> None:
        """Remove local routing and dependent checks while retaining run evidence.

        Reject deletion while the account has pending or active work. Shared
        groups retain other accounts; groups without remaining checks are removed.
        Source accounts and proxies are never modified.
        """
        async with self.lock:
            with self.repo.transaction():
                self.repo.get(Account, identity)
                if self.active_runs(account_id=identity):
                    raise DomainError(
                        "account_busy",
                        "Cancel or wait for active checks and probes before deleting "
                        "the account.",
                        409,
                    )
                targets = self.repo.all(Target, account_id=identity)
                for group_id in {target.group_id for target in targets}:
                    group = self.repo.get(Group, group_id)
                    remaining = [
                        target
                        for target in group.recipe.targets
                        if target.account_id != identity
                    ]
                    if remaining:
                        group.recipe = group.recipe.model_copy(
                            update={"targets": remaining}
                        )
                        group.revision += 1
                        self.repo.save(group)
                    else:
                        self.repo.delete(Group, group_id)
                for target in targets:
                    self.repo.delete(Target, target.id)
                self.repo.delete(Account, identity)

    def _save_order(
        self, records: list[Account] | list[Group], identities: list[str]
    ) -> None:
        indexed = {record.id: record for record in records}
        if len(identities) != len(set(identities)) or set(identities) != set(indexed):
            raise DomainError(
                "order_conflict",
                "The list changed. Refresh it and try reordering again.",
                409,
            )
        for position, identity in enumerate(identities):
            record = indexed[identity]
            record.sort_order = position
            self.repo.save(record)

    async def reorder_accounts(self, identities: list[str]) -> None:
        """Persist a complete account order atomically, rejecting stale lists."""
        async with self.lock:
            with self.repo.transaction():
                self._save_order(self.repo.all(Account), identities)

    async def reorder_groups(self, kind: Kind, identities: list[str]) -> None:
        """Persist one detector's card order without changing any recipe."""
        async with self.lock:
            with self.repo.transaction():
                self._save_order(
                    [
                        group
                        for group in self.repo.all(Group)
                        if group.recipe.kind == kind
                    ],
                    identities,
                )

    def _catalog_key(self, account: Account) -> str:
        return hashlib.sha256(
            json.dumps(
                [
                    account.config.base_url,
                    account.config.models_path,
                    account.config.protocol,
                    account.credentials.model_dump(),
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()

    async def preview_models(
        self, config: AccountInput, identity: str | None = None
    ) -> list[str]:
        """Fetch an unsaved form's catalogue and reuse it on successful save."""
        account = (
            self.repo.get(Account, identity).model_copy(deep=True)
            if identity
            else Account(config=config)
        )
        if account.source == "sub2api":
            return (await self.refresh_models(account.id)).models
        else:
            account.config = config.model_copy(
                update={"api_key": None, "headers": None}
            )
            if config.api_key is not None:
                account.credentials.api_key = config.api_key
            if config.headers is not None:
                account.credentials.headers = config.headers
            if not account.credentials.api_key:
                raise DomainError("credential_required", "An API key is required.")
        models = await self.gateway.models(account)
        self.model_previews = {
            key: value
            for key, value in self.model_previews.items()
            if value[1] > timestamp() - 900
        }
        if len(self.model_previews) >= 100:
            del self.model_previews[next(iter(self.model_previews))]
        self.model_previews[self._catalog_key(account)] = (models, timestamp())
        return models

    async def import_accounts(self, identities: list[int]) -> list[Account]:
        """Import selected fully resolved source accounts atomically."""
        if (
            not identities
            or len(identities) != len(set(identities))
            or len(identities) > 100
        ):
            raise DomainError(
                "selection_invalid", "Select one to one hundred unique accounts."
            )
        resolved = [await self.source.resolve(identity) for identity in identities]
        async with self.lock:
            with self.repo.transaction():
                existing = {
                    account.external_id: account
                    for account in self.repo.all(Account, source="sub2api")
                }
                next_order = 1 + max(
                    (account.sort_order for account in self.repo.all(Account)),
                    default=0,
                )
                for fresh in resolved:
                    if fresh.external_id in existing:
                        fresh = self._merge_source(existing[fresh.external_id], fresh)
                    else:
                        fresh.sort_order = next_order
                        next_order += 1
                    self.repo.save(fresh)
        return self.repo.all(Account, source="sub2api")

    def _merge_source(self, current: Account, fresh: Account) -> Account:
        if (
            current.config.base_url,
            current.config.models_path,
            current.config.protocol,
            current.credentials.proxy,
        ) != (
            fresh.config.base_url,
            fresh.config.models_path,
            fresh.config.protocol,
            fresh.credentials.proxy,
        ):
            current.models, current.models_at, current.models_error = [], None, None
        current.credentials = fresh.credentials
        current.source_proxy_id = fresh.source_proxy_id
        current.source_proxy_name = fresh.source_proxy_name
        current.account_type = fresh.account_type
        current.source_active, current.source_error = True, None
        current.synced_at = fresh.synced_at
        current.config = current.config.model_copy(
            update={
                "protocol": fresh.config.protocol,
                "base_url": fresh.config.base_url,
                "path": fresh.config.path,
                "models_path": fresh.config.models_path,
            }
        )
        return current

    async def fresh_account(self, identity: str) -> Account:
        """Resolve live source routing immediately before an outbound operation."""
        current = self.repo.get(Account, identity)
        if not current.config.enabled:
            raise DomainError("account_disabled", "The account is disabled.")
        if current.source == "sub2api":
            assert current.external_id is not None
            try:
                fresh = await self.source.resolve(current.external_id)
            except DomainError as exc:
                current = self.repo.get(Account, identity)
                current.source_error = str(exc)
                if exc.code in {
                    "source_inactive",
                    "source_unsupported",
                    "source_missing",
                }:
                    current.source_active = False
                self.repo.save(current)
                raise
            current = self._merge_source(self.repo.get(Account, identity), fresh)
            self.repo.save(current)
        if not current.source_active:
            raise DomainError(
                "account_unavailable", "The source account is unavailable."
            )
        return current

    async def sync_accounts(self) -> dict[str, int]:
        """Resolve an entire imported set before publishing new source snapshots."""
        accounts = self.repo.all(Account, source="sub2api")
        resolved: list[tuple[str, Account]] = []
        failures: list[tuple[str, DomainError]] = []
        for account in accounts:
            assert account.external_id is not None
            try:
                resolved.append(
                    (account.id, await self.source.resolve(account.external_id))
                )
            except DomainError as exc:
                failures.append((account.id, exc))
        with self.repo.transaction():
            current_accounts = {
                account.id: account
                for account in self.repo.all(Account, source="sub2api")
            }
            resolved = [
                (identity, fresh)
                for identity, fresh in resolved
                if identity in current_accounts
            ]
            failures = [
                (identity, failure)
                for identity, failure in failures
                if identity in current_accounts
            ]
            if not failures:
                for identity, fresh in resolved:
                    self.repo.save(
                        self._merge_source(current_accounts[identity], fresh)
                    )
            for identity, failure in failures:
                current = current_accounts[identity]
                current.source_error = str(failure)
                if failure.code in {
                    "source_inactive",
                    "source_unsupported",
                    "source_missing",
                }:
                    current.source_active = False
                self.repo.save(current)
        return {
            "updated": len(resolved) if not failures else 0,
            "failed": len(failures),
        }

    async def refresh_models(self, identity: str) -> Account:
        """Refresh the shared catalogue while retaining the last good cache on error."""
        try:
            fresh = await self.fresh_account(identity)
            models = await self.gateway.models(fresh)
        except DomainError as exc:
            current = self.repo.get(Account, identity)
            current.models_error = str(exc)
            self.repo.save(current)
            raise
        current = self.repo.get(Account, identity)
        current.models, current.models_at, current.models_error = (
            models,
            timestamp(),
            None,
        )
        self.repo.save(current)
        return current

    def validate_recipe(self, recipe: GroupInput) -> None:
        """Validate evaluation-specific configuration before creating any records."""
        next_occurrences(recipe.cron, self.repo.settings().timezone)
        if recipe.kind == Kind.MODELTRACE:
            self.fingerprint.selected(recipe.challenge_ids)
            valid = {model["id"] for model in self.fingerprint.models} | {
                model["family"] for model in self.fingerprint.models
            }
            if recipe.expected_identity and recipe.expected_identity not in valid:
                raise DomainError(
                    "identity_invalid",
                    "Choose an expected identity from the loaded fingerprint bank.",
                )
        elif not recipe.prompt.strip():
            raise DomainError("prompt_required", "A prompt is required.")
        if recipe.kind == Kind.COMPARISON:
            if recipe.comparison_mode == "regex":
                validate_regex(recipe.regex_pattern)
            else:
                try:
                    parse_json(recipe.expected_json)
                except (ValueError, RecursionError) as exc:
                    raise DomainError(
                        "answer_invalid", "The expected answer must be valid JSON."
                    ) from exc

    async def save_group(
        self, recipe: GroupInput, identity: str | None = None
    ) -> Group:
        """Commit a batch of checks together while enforcing account-wide quotas."""
        self.validate_recipe(recipe)
        selections = [
            (target.account_id, target.model, target.effort)
            for target in recipe.targets
        ]
        if len(set(selections)) != len(selections):
            raise DomainError(
                "target_duplicate",
                "A group cannot contain the same account/model/effort twice.",
            )
        async with self.lock:
            with self.repo.transaction():
                group = (
                    self.repo.get(Group, identity) if identity else Group(recipe=recipe)
                )
                if identity is None:
                    group.sort_order = 1 + max(
                        (
                            item.sort_order
                            for item in self.repo.all(Group)
                            if item.recipe.kind == recipe.kind
                        ),
                        default=0,
                    )
                existing = self.repo.all(Target, group_id=group.id)
                requested = Counter(target.account_id for target in recipe.targets)
                settings = self.repo.settings()
                for account_id, count in requested.items():
                    account = self.repo.get(Account, account_id)
                    if not account.config.enabled:
                        raise DomainError(
                            "account_disabled", "A selected account is disabled."
                        )
                    if recipe.enabled:
                        for selected in recipe.targets:
                            if selected.account_id == account_id:
                                validate_reasoning(
                                    account.config.protocol,
                                    selected.model,
                                    selected.effort,
                                )
                    current = sum(
                        target.group_id != group.id
                        for target in self.repo.all(Target, account_id=account_id)
                    )
                    if current + count > settings.account_check_limit:
                        raise DomainError(
                            "check_limit",
                            f"{account.config.name}: account check limit exceeded.",
                            409,
                        )
                previous = {
                    (target.account_id, target.model, target.effort): target
                    for target in existing
                }
                if identity:
                    group.revision += 1
                group.recipe = recipe.model_copy(deep=True)
                group.next_run_at = (
                    next_occurrences(recipe.cron, settings.timezone)[0]
                    if recipe.enabled
                    else None
                )
                self.repo.save(group)
                keep: set[str] = set()
                for selected in recipe.targets:
                    target = previous.get(
                        (selected.account_id, selected.model, selected.effort)
                    ) or Target(group_id=group.id, **selected.model_dump())
                    keep.add(target.id)
                    self.repo.save(target)
                    account = self.repo.get(Account, target.account_id)
                    account.last_model, account.last_effort = (
                        target.model,
                        target.effort,
                    )
                    self.repo.save(account)
                for target in existing:
                    if target.id not in keep:
                        if self.active_runs(target_id=target.id):
                            raise DomainError(
                                "target_busy",
                                "Cancel active checks before removing their configuration.",
                                409,
                            )
                        self.repo.delete(Target, target.id)
                return group

    def enqueue(self, target: Target, batch_id: str) -> Run:
        """Persist a complete immutable run and all of its invocation records."""
        with self.repo.transaction():
            if self.active_runs(target_id=target.id):
                raise DomainError(
                    "check_busy", "This check is already queued or running.", 409
                )
            group = self.repo.get(Group, target.group_id)
            account = self.repo.get(Account, target.account_id)
            if not account.config.enabled or not account.source_active:
                raise DomainError(
                    "account_disabled", "This account is disabled or unavailable.", 409
                )
            recipe = group.recipe.model_copy(deep=True)
            snapshot = Snapshot(
                account_name=account.config.name,
                model=target.model,
                effort=target.effort,
                protocol=account.config.protocol,
                group_revision=group.revision,
                recipe=recipe,
                timezone=self.repo.settings().timezone,
                call_timeout=self.repo.settings().call_timeout,
                max_output_tokens=self.repo.settings().max_output_tokens,
                fingerprint_version=self.fingerprint.version
                if recipe.kind == Kind.MODELTRACE
                else None,
            )
            run = Run(
                batch_id=batch_id,
                group_id=group.id,
                target_id=target.id,
                account_id=account.id,
                kind=recipe.kind,
                snapshot=snapshot,
            )
            self.repo.save(run)
            if recipe.kind == Kind.MODELTRACE:
                for index, challenge in enumerate(
                    self.fingerprint.selected(recipe.challenge_ids)
                ):
                    self.repo.save(
                        Call(
                            run_id=run.id,
                            account_id=account.id,
                            order=index,
                            challenge_id=challenge.id,
                            prompt=challenge.prompt,
                            expected_count=challenge.expected_count,
                        )
                    )
            else:
                self.repo.save(
                    Call(run_id=run.id, account_id=account.id, prompt=recipe.prompt)
                )
            return run

    async def run_target(self, identity: str) -> Run:
        """Queue one manual check without changing its scheduled occurrence."""
        async with self.lock:
            return self.enqueue(self.repo.get(Target, identity), identifier())

    async def run_group(self, identity: str) -> dict[str, list[str]]:
        """Queue available checks into one aligned batch and report skipped checks."""
        async with self.lock:
            batch = identifier()
            queued, skipped = [], []
            for target in self.repo.all(Target, group_id=identity):
                try:
                    queued.append(self.enqueue(target, batch).id)
                except DomainError as exc:
                    if exc.code not in {"check_busy", "account_disabled"}:
                        raise
                    skipped.append(target.id)
            return {"queued": queued, "skipped": skipped}

    async def probe_account(self, identity: str) -> Run:
        """Queue a small real connectivity probe through the normal limiter."""
        async with self.lock:
            account = self.repo.get(Account, identity)
            if not account.config.enabled:
                raise DomainError("account_disabled", "The account is disabled.")
            if not account.config.default_model:
                raise DomainError(
                    "model_required", "Configure the account's default model first."
                )
            validate_reasoning(
                account.config.protocol,
                account.config.default_model,
                account.config.default_effort,
            )
            if self.active_runs(account_id=identity, kind="probe"):
                raise DomainError(
                    "check_busy", "A connectivity probe is already pending.", 409
                )
            target = TargetInput(
                account_id=identity,
                model=account.config.default_model,
                effort=account.config.default_effort,
            )
            recipe = GroupInput(
                name="Connectivity",
                kind=Kind.OTHER,
                prompt="Reply with exactly OK.",
                targets=[target],
            )
            run = Run(
                account_id=identity,
                kind="probe",
                snapshot=Snapshot(
                    account_name=account.config.name,
                    model=target.model,
                    effort=target.effort,
                    protocol=account.config.protocol,
                    group_revision=1,
                    recipe=recipe,
                    timezone=self.repo.settings().timezone,
                    call_timeout=self.repo.settings().call_timeout,
                    max_output_tokens=self.repo.settings().max_output_tokens,
                ),
            )
            with self.repo.transaction():
                self.repo.save(run)
                self.repo.save(
                    Call(run_id=run.id, account_id=identity, prompt=recipe.prompt)
                )
            return run

    def update_settings(self, settings: Settings) -> None:
        """Save defaults and recompute plans only when the scheduling zone changes."""
        next_occurrences(settings.default_cron, settings.timezone)
        if settings.sub2api_url:
            AccountInput.validate_url(settings.sub2api_url)
        current = self.repo.settings()
        with self.repo.transaction():
            self.repo.save_settings(settings)
            if current.timezone != settings.timezone:
                for group in self.repo.all(Group):
                    group.next_run_at = (
                        next_occurrences(group.recipe.cron, settings.timezone)[0]
                        if group.recipe.enabled
                        else None
                    )
                    self.repo.save(group)

    def review_run(
        self, identity: str, verdict: Literal["pass", "fail"] | None, note: str
    ) -> Run:
        """Attach human assessment only to completed subjective evaluations."""
        run = self.repo.get(Run, identity)
        if run.status != Status.COMPLETED or run.kind not in {Kind.PELICAN, Kind.OTHER}:
            raise DomainError(
                "review_unavailable",
                "Only completed visual or free-form checks accept human review.",
            )
        if verdict not in {None, "pass", "fail"}:
            raise DomainError("review_invalid", "Use pass, fail, or clear the review.")
        run.review = verdict
        run.review_note = note[:2000]
        self.repo.save(run)
        return run

    def active_runs(self, **filters: str) -> list[Run]:
        """Read only active records through status-indexed queries."""
        return [
            run
            for status in ACTIVE
            for run in self.repo.all(Run, status=status, **filters)
        ]
