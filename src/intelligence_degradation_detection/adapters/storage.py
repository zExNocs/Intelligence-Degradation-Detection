"""Persist typed records in SQLite with transactional indexed projections."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    event,
    func,
    select,
)
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection

from ..application.ports import Entity
from ..domain.models import (
    Account,
    Call,
    DomainError,
    Group,
    Run,
    RunSummary,
    Settings,
    Target,
)

metadata = MetaData()
tables: dict[
    type[Account] | type[Group] | type[Target] | type[Run] | type[Call], Table
] = {}
for model, name, indexes in (
    (Account, "accounts", ["source"]),
    (Group, "groups", []),
    (Target, "targets", ["group_id", "account_id"]),
    (
        Run,
        "runs",
        ["group_id", "target_id", "account_id", "batch_id", "status", "kind"],
    ),
    (Call, "calls", ["run_id", "account_id", "status"]),
):
    columns = [
        Column("id", String, primary_key=True),
        Column("payload", JSON, nullable=False),
    ]
    for field in indexes:
        if model is Call and field == "run_id":
            columns.append(
                Column(
                    field, String, ForeignKey("runs.id", ondelete="CASCADE"), index=True
                )
            )
        else:
            columns.append(Column(field, String, index=True))
    columns.append(Column("created_at", Float, nullable=False, default=0))
    tables[model] = Table(name, metadata, *columns)

settings_table = Table(
    "settings",
    metadata,
    Column("id", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)
Index("ix_runs_group_time", tables[Run].c.group_id, tables[Run].c.created_at)
Index("ix_runs_target_time", tables[Run].c.target_id, tables[Run].c.created_at)
EntityT = TypeVar("EntityT", Account, Group, Target, Run, Call)


class SQLiteRepository:
    """Own a SQLite engine and synchronous transactional record access."""

    def __init__(self, path: Path) -> None:
        """Create the data directory and migrate the database before use."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 10},
        )
        event.listen(self.engine, "connect", self._configure)
        self._connection: Connection | None = None
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).with_name("migrations"))
        )
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with self.transaction():
            assert self._connection is not None
            if self._connection.execute(select(settings_table.c.id)).first() is None:
                self.save_settings(Settings())

    @staticmethod
    def _configure(connection: object, _record: object) -> None:
        """Enable WAL, foreign keys, and bounded writer contention."""
        import sqlite3

        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("Expected a SQLite connection.")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit grouped synchronous writes together; never await inside."""
        if self._connection is not None:
            yield
            return
        with self.engine.begin() as connection:
            self._connection = connection
            try:
                yield
            finally:
                self._connection = None

    def get(self, entity_type: type[EntityT], identity: str) -> EntityT:
        """Load a record by stable identity."""
        table = tables[entity_type]
        with self.transaction():
            assert self._connection is not None
            payload = self._connection.execute(
                select(table.c.payload).where(table.c.id == identity)
            ).scalar_one_or_none()
        if payload is None:
            raise DomainError("not_found", "The requested record does not exist.", 404)
        return entity_type.model_validate(payload)

    def all(self, entity_type: type[EntityT], **filters: str) -> list[EntityT]:
        """Read matching records in insertion-time order."""
        table = tables[entity_type]
        query = select(table.c.payload).order_by(table.c.created_at, table.c.id)
        for key, value in filters.items():
            query = query.where(table.c[key] == value)
        with self.transaction():
            assert self._connection is not None
            return [
                entity_type.model_validate(value)
                for value in self._connection.execute(query).scalars()
            ]

    def save(self, entity: Entity) -> None:
        """Upsert a typed payload and maintain its indexed projection."""
        table = tables[type(entity)]
        payload = entity.model_dump(mode="json")
        values = {
            column.name: payload.get(
                column.name, 0 if column.name == "created_at" else None
            )
            for column in table.columns
            if column.name != "payload"
        }
        values["payload"] = payload
        statement = insert(table).values(**values)
        with self.transaction():
            assert self._connection is not None
            self._connection.execute(
                statement.on_conflict_do_update(index_elements=["id"], set_=values)
            )

    def delete(self, entity_type: type[EntityT], identity: str) -> None:
        """Delete a record and let foreign keys clean owned calls."""
        table = tables[entity_type]
        with self.transaction():
            assert self._connection is not None
            self._connection.execute(delete(table).where(table.c.id == identity))

    def settings(self) -> Settings:
        """Load global settings with validation."""
        with self.transaction():
            assert self._connection is not None
            payload = self._connection.execute(
                select(settings_table.c.payload).where(settings_table.c.id == "global")
            ).scalar_one()
        return Settings.model_validate(payload)

    def save_settings(self, value: Settings) -> None:
        """Persist defaults while retaining their complete typed schema."""
        statement = insert(settings_table).values(
            id="global", payload=value.model_dump(mode="json")
        )
        with self.transaction():
            assert self._connection is not None
            self._connection.execute(
                statement.on_conflict_do_update(
                    index_elements=["id"],
                    set_={"payload": value.model_dump(mode="json")},
                )
            )

    def close(self) -> None:
        """Release the engine after the application has stopped all work."""
        self.engine.dispose()

    def summaries(
        self, group_id: str | None = None, since: float | None = None
    ) -> list[RunSummary]:
        """Project indexed metadata and short previews inside SQLite."""
        table = tables[Run]
        paths = {
            "id": "$.id",
            "batch_id": "$.batch_id",
            "group_id": "$.group_id",
            "target_id": "$.target_id",
            "account_id": "$.account_id",
            "kind": "$.kind",
            "status": "$.status",
            "created_at": "$.created_at",
            "started_at": "$.started_at",
            "finished_at": "$.finished_at",
            "account_name": "$.snapshot.account_name",
            "model": "$.snapshot.model",
            "effort": "$.snapshot.effort",
            "verdict": "$.judgment.verdict",
            "score": "$.judgment.score",
            "review": "$.review",
            "error": "$.error",
            "elapsed": "$.output.elapsed",
            "total_tokens": "$.output.usage.total_tokens",
        }
        query = select(
            *(
                func.json_extract(table.c.payload, path).label(name)
                for name, path in paths.items()
            ),
            func.substr(
                func.json_extract(table.c.payload, "$.output.text"), 1, 180
            ).label("preview"),
        ).order_by(table.c.created_at.desc(), table.c.id.desc())
        if group_id:
            query = query.where(table.c.group_id == group_id)
        if since is not None:
            query = query.where(table.c.created_at >= since)
        with self.transaction():
            assert self._connection is not None
            return [
                RunSummary.model_validate(dict(row))
                for row in self._connection.execute(query).mappings()
            ]
