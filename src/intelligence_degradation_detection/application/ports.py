"""Describe infrastructure capabilities consumed by evaluation use cases."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol, TypeVar

from ..domain.models import (
    Account,
    Call,
    Challenge,
    Group,
    GroupInput,
    Judgment,
    Output,
    Run,
    RunSummary,
    Settings,
    Target,
)

Entity = Account | Group | Target | Run | Call
EntityT = TypeVar("EntityT", Account, Group, Target, Run, Call)


class Repository(Protocol):
    """Persist the application's finite set of entities atomically."""

    def transaction(self) -> AbstractContextManager[None]:
        """Group synchronous writes into one transaction."""
        ...

    def get(self, entity_type: type[EntityT], identity: str) -> EntityT:
        """Load a typed entity or report that it does not exist."""
        ...

    def all(self, entity_type: type[EntityT], **filters: str) -> list[EntityT]:
        """Read typed records matching indexed equality filters."""
        ...

    def save(self, entity: Entity) -> None:
        """Insert or update an entity without changing its identity."""
        ...

    def delete(self, entity_type: type[EntityT], identity: str) -> None:
        """Delete a record and its owned child calls where applicable."""
        ...

    def settings(self) -> Settings:
        """Read the persisted application defaults."""
        ...

    def save_settings(self, value: Settings) -> None:
        """Replace defaults in the current transaction."""
        ...

    def summaries(
        self, group_id: str | None = None, since: float | None = None
    ) -> list[RunSummary]:
        """Read lightweight result projections without full text bodies."""
        ...


class ModelGateway(Protocol):
    """Execute one invocation through the account's explicit route."""

    async def invoke(
        self,
        account: Account,
        model: str,
        effort: str,
        prompt: str,
        settings: Settings,
        progress: Callable[[Output], None],
    ) -> Output:
        """Return normalized output, reporting partial progress before failure."""
        ...

    async def models(self, account: Account) -> list[str]:
        """Download the advertised model identifiers through the same proxy."""
        ...


class AccountSource(Protocol):
    """Resolve live credentials and routing without mutating the source."""

    async def discover(self) -> list[dict[str, object]]:
        """List available source account descriptors."""
        ...

    async def resolve(self, external_id: int) -> Account:
        """Return an authoritative account and proxy configuration."""
        ...


class FingerprintEngine(Protocol):
    """Expose pinned challenges and local inference without third-party types."""

    version: str
    models: list[dict[str, str]]
    challenges: list[Challenge]

    def selected(self, identities: list[str]) -> list[Challenge]:
        """Resolve the fixed challenge selection."""
        ...

    def evaluate(self, recipe: GroupInput, calls: list[Call]) -> Judgment:
        """Attribute available outputs against the fixed candidate bank."""
        ...
