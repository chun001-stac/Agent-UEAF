"""SQLAlchemy ORM models for authoritative V1 objects (implementation spec 03).

The ORM rows are NOT the public contract: every row carries a ``payload`` JSON
column that fully reconstructs the canonical object (including ``ContractMeta``).
A few scalar columns (``tenant_id``, ``revision``, ``phase``, ``sequence``,
``lease_fencing_token``) are split out for DB-level CAS, fencing and querying.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ueaf.infrastructure.db.metadata import metadata


class Base(DeclarativeBase):
    metadata = metadata


JSON_COLUMN = JSON().with_variant(JSONB(), "postgresql")


class RunRecordORM(Base):
    __tablename__ = "run_records"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False, index=True)
    completion_disposition: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_fencing_token: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_id: Mapped[str | None] = mapped_column(String, nullable=True)
    runtime_adapter_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class TaskStateORM(Base):
    __tablename__ = "task_states"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class RunAdmissionResultORM(Base):
    __tablename__ = "run_admission_results"

    run_admission_result_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class OutboxEntryORM(Base):
    __tablename__ = "outbox"

    outbox_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    event_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    event_version: Mapped[str] = mapped_column(String, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    payload_schema_ref: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class ActionRecordORM(Base):
    __tablename__ = "action_records"

    action_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_key: Mapped[str] = mapped_column(String, nullable=False)
    capability_ref: Mapped[str] = mapped_column(String, nullable=False)
    phase: Mapped[str] = mapped_column(String, nullable=False, index=True)
    disposition: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_fencing_token: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class ActionReceiptORM(Base):
    __tablename__ = "action_receipts"

    action_receipt_id: Mapped[str] = mapped_column(String, primary_key=True)
    action_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    action_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    capability_ref: Mapped[str] = mapped_column(String, nullable=False)
    executor_ref: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class ApprovalRequestORM(Base):
    __tablename__ = "approval_requests"

    approval_request_id: Mapped[str] = mapped_column(String, primary_key=True)
    action_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class TurnRecordORM(Base):
    __tablename__ = "turn_records"

    turn_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)


class MemoryRecordORM(Base):
    __tablename__ = "memory_records"

    record_id: Mapped[str] = mapped_column(String, primary_key=True)
    subject_ref: Mapped[str] = mapped_column(String, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String, nullable=False)
    sensitivity: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_COLUMN, nullable=False)
