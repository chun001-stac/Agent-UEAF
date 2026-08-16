"""创建 P1 action/turn/memory 持久化表。

Revision ID: 20260816_0003
Revises: 20260816_0002
Create Date: 2026-08-16

表：``action_records``、``action_receipts``、``approval_requests``、
``turn_records``、``memory_records``。

沿用 0002 模式：每行保留完整的 ``payload`` JSON 列，用于重建规范对象
（包括 ``ContractMeta``）；标量列支持数据库级别的 CAS、fencing 及
按租户/run 范围查询（实现规范 03 §5/§15）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0003"
down_revision: str | None = "20260816_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_COLUMN = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    _create_action_records()
    _create_action_receipts()
    _create_approval_requests()
    _create_turn_records()
    _create_memory_records()


def _create_action_records() -> None:
    op.create_table(
        "action_records",
        sa.Column("action_id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("action_key", sa.String(), nullable=False),
        sa.Column("capability_ref", sa.String(), nullable=False),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("disposition", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_fencing_token", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_action_records_tenant_id", "action_records", ["tenant_id"])
    op.create_index("ix_action_records_run_id", "action_records", ["run_id"])
    op.create_index("ix_action_records_phase", "action_records", ["phase"])
    op.create_index("ix_action_records_updated_at", "action_records", ["updated_at"])


def _create_action_receipts() -> None:
    op.create_table(
        "action_receipts",
        sa.Column("action_receipt_id", sa.String(), primary_key=True),
        sa.Column("action_key", sa.String(), nullable=False),
        sa.Column("action_fingerprint", sa.String(), nullable=False),
        sa.Column("capability_ref", sa.String(), nullable=False),
        sa.Column("executor_ref", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_action_receipts_action_key", "action_receipts", ["action_key"])
    op.create_index("ix_action_receipts_status", "action_receipts", ["status"])


def _create_approval_requests() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("approval_request_id", sa.String(), primary_key=True),
        sa.Column("action_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_approval_requests_action_id", "approval_requests", ["action_id"])
    op.create_index("ix_approval_requests_run_id", "approval_requests", ["run_id"])
    op.create_index("ix_approval_requests_tenant_id", "approval_requests", ["tenant_id"])


def _create_turn_records() -> None:
    op.create_table(
        "turn_records",
        sa.Column("turn_id", sa.String(), primary_key=True),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("turn_no", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_turn_records_run_id", "turn_records", ["run_id"])
    op.create_index("ix_turn_records_tenant_id", "turn_records", ["tenant_id"])
    op.create_index("ix_turn_records_created_at", "turn_records", ["created_at"])


def _create_memory_records() -> None:
    op.create_table(
        "memory_records",
        sa.Column("record_id", sa.String(), primary_key=True),
        sa.Column("subject_ref", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("sensitivity", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSON_COLUMN, nullable=False),
    )
    op.create_index("ix_memory_records_subject_ref", "memory_records", ["subject_ref"])
    op.create_index("ix_memory_records_tenant_id", "memory_records", ["tenant_id"])
    op.create_index("ix_memory_records_status", "memory_records", ["status"])


def downgrade() -> None:
    op.drop_table("memory_records")
    op.drop_table("turn_records")
    op.drop_table("approval_requests")
    op.drop_table("action_receipts")
    op.drop_table("action_records")
