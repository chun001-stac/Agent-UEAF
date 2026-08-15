"""Create V1 authoritative persistence tables.

Revision ID: 20260816_0002
Revises: 20260815_0001
Create Date: 2026-08-16

Tables: ``run_records``, ``task_states``, ``run_admission_results``, ``outbox``.
Each row keeps a full ``payload`` JSON column to reconstruct the canonical
object (including ContractMeta); scalar columns enable DB-level CAS, fencing
and tenant-scoped queries (implementation spec 03 §5/§15).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0002"
down_revision: str | None = "20260815_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    _create_run_records()
    _create_task_states()
    _create_run_admission_results()
    _create_outbox()


def _create_run_records() -> None:
    op.create_table(
        "run_records",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("completion_disposition", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_fencing_token", sa.Integer(), nullable=True),
        sa.Column("release_id", sa.String(), nullable=True),
        sa.Column("runtime_adapter_ref", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_run_records_tenant_id", "run_records", ["tenant_id"])
    op.create_index("ix_run_records_phase", "run_records", ["phase"])
    op.create_index("ix_run_records_updated_at", "run_records", ["updated_at"])


def _create_task_states() -> None:
    op.create_table(
        "task_states",
        sa.Column("task_id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_task_states_tenant_id", "task_states", ["tenant_id"])
    op.create_index("ix_task_states_updated_at", "task_states", ["updated_at"])


def _create_run_admission_results() -> None:
    op.create_table(
        "run_admission_results",
        sa.Column("run_admission_result_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index(
        "ix_run_admission_results_run_id",
        "run_admission_results",
        ["run_id"],
    )
    op.create_index(
        "ix_run_admission_results_tenant_id",
        "run_admission_results",
        ["tenant_id"],
    )


def _create_outbox() -> None:
    op.create_table(
        "outbox",
        sa.Column("outbox_id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), nullable=False, unique=True),
        sa.Column("event_name", sa.String(), nullable=False),
        sa.Column("event_version", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("aggregate_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("payload_schema_ref", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_outbox_event_name", "outbox", ["event_name"])
    op.create_index("ix_outbox_tenant_id", "outbox", ["tenant_id"])
    op.create_index("ix_outbox_aggregate_id", "outbox", ["aggregate_id"])


def downgrade() -> None:
    op.drop_table("outbox")
    op.drop_table("run_admission_results")
    op.drop_table("task_states")
    op.drop_table("run_records")
