"""Create the first version of the evaluation record store."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.schema import SchemaItem

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables and indexes without depending on future model metadata."""
    definitions = {
        "accounts": ["source"],
        "groups": [],
        "targets": ["group_id", "account_id"],
        "runs": ["group_id", "target_id", "account_id", "batch_id", "status", "kind"],
        "calls": ["run_id", "account_id", "status"],
    }
    for name, fields in definitions.items():
        columns: list[SchemaItem] = [
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.Float(), nullable=False),
        ]
        for field in fields:
            if name == "calls" and field == "run_id":
                columns.append(
                    sa.Column(
                        field, sa.String(), sa.ForeignKey("runs.id", ondelete="CASCADE")
                    )
                )
            else:
                columns.append(sa.Column(field, sa.String()))
        op.create_table(name, *columns)
        for field in fields:
            op.create_index(f"ix_{name}_{field}", name, [field])
    op.create_index("ix_runs_group_time", "runs", ["group_id", "created_at"])
    op.create_index("ix_runs_target_time", "runs", ["target_id", "created_at"])
    op.create_table(
        "settings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    """Remove the initial schema only when explicitly requested by an operator."""
    for name in ("calls", "runs", "targets", "groups", "accounts", "settings"):
        op.drop_table(name)
