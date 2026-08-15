"""Admission-boundary objects (core spec 01 §7, §7.3).

Only the trusted admission boundary may construct ``PrincipalContext`` and
immutable ``TaskEnvelope`` / ``RequestEnvelope``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta

RiskClass = Literal["compute_only", "read_only", "reversible_write", "high_risk_write"]
PrincipalType = Literal[
    "end_user", "calling_service", "agent", "workload", "human_approver"
]

# Deprecated legacy alias mapping (RUN-006): never accepted for new writes.
_LEGACY_RISK_ALIASES: Mapping[str, RiskClass] = {
    "R0": "compute_only",
    "R1": "read_only",
    "R2": "reversible_write",
    "R3": "high_risk_write",
}


@dataclass(frozen=True, slots=True)
class DelegationRef:
    delegator_ref: str
    delegated_at: datetime
    scope_note: str | None = None


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """Trusted combination security context; immutable once constructed."""

    meta: ContractMeta
    principal_id: str
    principal_type: PrincipalType
    tenant_id: str
    roles: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()
    delegation_chain: tuple[DelegationRef, ...] = ()
    authentication_strength: str = "password"
    credential_ref: str | None = None
    data_regions: tuple[str, ...] = ()
    consent_refs: tuple[str, ...] = ()
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    revocation_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.principal_id:
            raise ValueError("PrincipalContext.principal_id must not be empty")
        if self.tenant_id != self.meta.tenant_id:
            raise ValueError(
                "PrincipalContext.tenant_id MUST equal meta.tenant_id "
                "(CON-008)"
            )
        if self.principal_id != self.meta.object_id:
            raise ValueError("PrincipalContext.meta.object_id must equal principal_id")
        if self.credential_ref and ":" not in self.credential_ref:
            raise ValueError("credential_ref must be an opaque reference, never a secret")

    def is_valid_at(self, moment: datetime) -> bool:
        if self.issued_at is not None and moment < self.issued_at:
            return False
        if self.expires_at is not None and moment >= self.expires_at:
            return False
        return True


@dataclass(frozen=True, slots=True)
class RequestEnvelope:
    """Immutable external ingress record produced by edge pre-validation."""

    meta: ContractMeta
    request_id: str
    channel: str
    protocol: str
    client_correlation_id: str
    received_at: datetime
    deadline_at: datetime
    principal_context_ref: str
    validation_status: Literal["pending", "accepted", "rejected"]
    input_ref: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.request_id != self.meta.object_id:
            raise ValueError("RequestEnvelope.meta.object_id must equal request_id")
        if self.deadline_at is not None and self.deadline_at <= self.received_at:
            raise ValueError("RequestEnvelope.deadline_at must be later than received_at")


@dataclass(frozen=True, slots=True)
class TaskEnvelope:
    """Immutable task input created by the admission boundary."""

    meta: ContractMeta
    task_id: str
    request_refs: tuple[str, ...]
    goal: str
    completion_criteria: tuple[str, ...]
    constraints: Mapping[str, object]
    risk_class: RiskClass
    owner_ref: str
    budget_ref: str
    revision: int = 1

    def __post_init__(self) -> None:
        if self.task_id != self.meta.object_id:
            raise ValueError("TaskEnvelope.meta.object_id must equal task_id")
        if not self.goal:
            raise ValueError("TaskEnvelope.goal must not be empty")
        if not self.completion_criteria:
            raise ValueError("TaskEnvelope.completion_criteria must not be empty")
        if self.risk_class not in (
            "compute_only", "read_only", "reversible_write", "high_risk_write"
        ):
            raise ValueError(f"invalid risk_class {self.risk_class!r} (RUN-006)")
        if self.revision < 1:
            raise ValueError("TaskEnvelope.revision must be >= 1")

    def with_legacy_risk_alias(self, legacy: str) -> TaskEnvelope:
        """Migration-only mapping; never used for new writes (RUN-006)."""
        risk = _LEGACY_RISK_ALIASES.get(legacy)
        if risk is None:
            raise ValueError(f"unknown legacy risk alias {legacy!r}")
        return TaskEnvelope(
            meta=self.meta,
            task_id=self.task_id,
            request_refs=self.request_refs,
            goal=self.goal,
            completion_criteria=self.completion_criteria,
            constraints=self.constraints,
            risk_class=risk,
            owner_ref=self.owner_ref,
            budget_ref=self.budget_ref,
            revision=self.revision,
        )


@dataclass(frozen=True, slots=True)
class BudgetEnvelope:
    """Explicit budget dimensions; missing dimension == explicit contract default."""

    meta: ContractMeta
    budget_id: str
    absolute_deadline_at: datetime | None = None
    max_steps: int | None = None
    max_model_calls: int | None = None
    max_token_budget: int | None = None
    max_cost_millis: int | None = None
    max_tool_calls: int | None = None
    max_parallelism: int | None = None
    reserved_finalize_millis: int | None = None
    unbounded: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.budget_id != self.meta.object_id:
            raise ValueError("BudgetEnvelope.meta.object_id must equal budget_id")
        for field_name in (
            "max_steps",
            "max_model_calls",
            "max_token_budget",
            "max_cost_millis",
            "max_tool_calls",
            "max_parallelism",
            "reserved_finalize_millis",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"BudgetEnvelope.{field_name} must be >= 0")

    def within(self, used: Mapping[str, int]) -> bool:
        """Return True when every bounded dimension used <= budget."""

        def ok(key: str, limit: int | None) -> bool:
            return limit is None or used.get(key, 0) <= limit

        return (
            ok("steps", self.max_steps)
            and ok("model_calls", self.max_model_calls)
            and ok("tokens", self.max_token_budget)
            and ok("cost_millis", self.max_cost_millis)
            and ok("tool_calls", self.max_tool_calls)
        )
