"""Pydantic v2 wire models for the V1 control-plane API.

Wire field names are ``snake_case`` (core spec 01 §2.2). Domain dataclasses
are mapped to/from these transport models at the API boundary; ORM rows are
never exposed directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RequestChannel = Literal["http", "websocket", "queue"]


class ProblemDetailOut(BaseModel):
    """Cross-process error body (ProblemDetail wire shape)."""

    model_config = ConfigDict(extra="forbid")

    code: str
    category: str
    message_safe: str
    retryability: Literal["never", "safe", "conditional", "after_reconciliation"]
    source: str
    object_ref: str | None = None
    field_paths: list[str] = Field(default_factory=list)
    correlation_refs: dict[str, str] = Field(default_factory=dict)
    cause_ref: str | None = None
    observed_at: datetime
    details_ref: str | None = None


class RequestIn(BaseModel):
    """External ingress submitted for edge pre-validation (RUN-005)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    channel: RequestChannel
    protocol: str
    client_correlation_id: str
    received_at: datetime
    deadline_at: datetime
    tenant_id: str
    principal_ref: str
    input_ref: str | None = None
    validation_status: Literal["pending", "accepted", "rejected"] = "pending"


class RunCreateIn(BaseModel):
    """Payload to create an immutable task envelope + queued Run."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    goal: str = Field(min_length=1)
    completion_criteria: list[str] = Field(min_length=1)
    risk_class: Literal[
        "compute_only", "read_only", "reversible_write", "high_risk_write"
    ]
    agent_ref: str
    runtime_adapter_ref: str
    release_id: str
    budget_snapshot_ref: str
    owner_ref: str
    request_refs: list[str] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    deadline_at: datetime | None = None


class AdmissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_ref: str | None = None
    principal_id: str = "principal-user-1"
    data_regions: list[str] = Field(default_factory=lambda: ["cn-east"])


class RunOut(BaseModel):
    """Public RunRecord projection (never exposes ORM internals)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    tenant_id: str
    phase: str
    completion_disposition: str | None = None
    wait_reason: str | None = None
    attempt: int
    revision: int
    release_id: str | None = None
    runtime_adapter_ref: str | None = None
    result_ref: str | None = None
    error_ref: str | None = None
    updated_at: datetime | None = None


class AdmissionResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_admission_result_id: str
    run_id: str
    outcome: Literal["admitted", "rejected", "deferred"]
    reason_codes: list[str]
    policy_decision_refs: list[str] = Field(default_factory=list)
    budget_snapshot_ref: str | None = None
    release_manifest_ref: str | None = None
    expires_at: datetime | None = None


class CommandIn(BaseModel):
    """CommandEnvelope wire shape; idempotency enforced by the state writer."""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    command_name: str
    command_version: str = "1.0.0"
    tenant_id: str
    actor_ref: str
    target_type: str = "RunRecord"
    target_id: str
    expected_revision: int | None = None
    idempotency_key: str
    correlation_id: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
