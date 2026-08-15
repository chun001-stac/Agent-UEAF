"""Run admission (core spec 02 §4, functional module 01).

``RunAdmissionResult`` is the only Run-level admission aggregate result and is
produced only after a ``RunRecord(phase=queued)`` exists. Edge pre-validation
rejections must not create any run/admission object (RUN-005).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from ueaf.admission.objects import BudgetEnvelope, PrincipalContext, TaskEnvelope
from ueaf.common.identifiers import utcnow
from ueaf.common.meta import ContractMeta
from ueaf.runtime.objects import RunRecord

AdmissionOutcome = Literal["admitted", "rejected", "deferred"]


@dataclass(frozen=True, slots=True)
class RunAdmissionResult:
    meta: ContractMeta
    run_admission_result_id: str
    run_id: str
    outcome: AdmissionOutcome
    validation_refs: tuple[str, ...] = ()
    policy_decision_refs: tuple[str, ...] = ()
    budget_snapshot_ref: str | None = None
    release_manifest_ref: str | None = None
    reason_codes: tuple[str, ...] = ()
    retry_after: datetime | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.run_admission_result_id != self.meta.object_id:
            raise ValueError("RunAdmissionResult.meta.object_id must equal id")
        if self.outcome not in ("admitted", "rejected", "deferred"):
            raise ValueError(f"invalid outcome {self.outcome!r}")
        if not self.reason_codes:
            raise ValueError("RunAdmissionResult.reason_codes MUST be non-empty")
        if self.expires_at is None:
            raise ValueError("RunAdmissionResult.expires_at MUST be set (never infinite)")
        if self.created_at is not None and self.expires_at <= self.created_at:
            raise ValueError("RunAdmissionResult.expires_at must be later than created_at")
        if self.outcome == "deferred" and self.retry_after is None:
            raise ValueError("deferred outcome SHOULD provide retry_after")

    def is_valid_at(self, moment: datetime) -> bool:
        return self.expires_at is not None and moment < self.expires_at


class ReleaseManifestGate(Protocol):
    """Fail-closed check on the release bound to a run."""

    def lifecycle_is_usable(self, release_manifest_ref: str) -> bool: ...

    def is_compatible(self, release_manifest_ref: str, task: TaskEnvelope) -> bool: ...


class PolicyDecisionRefs(Protocol):
    """Deny-by-default policy source for admission (SEC-004, ACT-015)."""

    def resolved_policy_decision_refs(self, run_id: str) -> tuple[str, ...]: ...

    def any_deny(self, run_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class AdmissionCheckResult:
    passed: bool
    reason_codes: tuple[str, ...]
    validation_refs: tuple[str, ...] = ()


class AdmissionController:
    """Deterministic run admission; no second governance decision."""

    def __init__(
        self,
        release_gate: ReleaseManifestGate,
        policy_source: PolicyDecisionRefs,
        *,
        region_allowlist: tuple[str, ...] = ("cn-east", "cn-north"),
        default_budget_overhead_steps: int = 0,
    ) -> None:
        self._release_gate = release_gate
        self._policy_source = policy_source
        self._region_allowlist = region_allowlist
        self._budget_overhead = default_budget_overhead_steps

    def evaluate(
        self,
        run: RunRecord,
        task: TaskEnvelope,
        budget: BudgetEnvelope,
        principal: PrincipalContext,
        *,
        now: datetime | None = None,
    ) -> RunAdmissionResult:
        """Evaluate admission for an existing queued run (deny-by-default)."""
        moment = now or utcnow()
        result_id = f"run-admission:{run.run_id}:{run.revision}"
        base_meta = ContractMeta(
            contract_name="RunAdmissionResult",
            contract_version="1.0.0",
            object_id=result_id,
            tenant_id=run.meta.tenant_id,
            created_at=moment,
            producer="ueaf-admission",
            producer_version="0.1.0",
            task_id=run.task_id,
            run_id=run.run_id,
            trace_id=run.meta.trace_id,
            release_id=run.release_id,
        )

        checks: list[AdmissionCheckResult] = [
            self._check_release(run, task),
            self._check_policy(run),
            self._check_budget(run, budget),
            self._check_region(principal),
            self._check_binding(run),
        ]
        failures = [
            reason
            for check in checks
            for reason in check.reason_codes
            if not check.passed
        ]
        validation_refs = tuple(
            ref for check in checks for ref in check.validation_refs
        )
        policy_refs = self._policy_source.resolved_policy_decision_refs(run.run_id)

        if failures:
            return RunAdmissionResult(
                meta=base_meta,
                run_admission_result_id=result_id,
                run_id=run.run_id,
                outcome="rejected",
                validation_refs=validation_refs,
                policy_decision_refs=policy_refs,
                budget_snapshot_ref=run.budget_snapshot_ref,
                release_manifest_ref=run.release_id,
                reason_codes=tuple(sorted(set(failures))),
                created_at=moment,
                expires_at=self._expiry(moment, 300),
            )

        if run.phase == "queued" and not self._capacity_available():
            return RunAdmissionResult(
                meta=base_meta,
                run_admission_result_id=result_id,
                run_id=run.run_id,
                outcome="deferred",
                validation_refs=validation_refs,
                policy_decision_refs=policy_refs,
                budget_snapshot_ref=run.budget_snapshot_ref,
                release_manifest_ref=run.release_id,
                reason_codes=("capacity_unavailable",),
                retry_after=self._expiry(moment, 60),
                created_at=moment,
                expires_at=self._expiry(moment, 300),
            )

        return RunAdmissionResult(
            meta=base_meta,
            run_admission_result_id=result_id,
            run_id=run.run_id,
            outcome="admitted",
            validation_refs=validation_refs,
            policy_decision_refs=policy_refs,
            budget_snapshot_ref=run.budget_snapshot_ref,
            release_manifest_ref=run.release_id,
            reason_codes=("admitted",),
            created_at=moment,
            expires_at=self._expiry(moment, 300),
        )

    # -- checks ------------------------------------------------------------

    def _check_release(self, run: RunRecord, task: TaskEnvelope) -> AdmissionCheckResult:
        if not run.release_id:
            return AdmissionCheckResult(False, ("release_missing",))
        if not self._release_gate.lifecycle_is_usable(run.release_id):
            return AdmissionCheckResult(False, ("release_not_usable",))
        if not self._release_gate.is_compatible(run.release_id, task):
            return AdmissionCheckResult(False, ("release_incompatible_with_task",))
        return AdmissionCheckResult(True, (), ("release-lifecycle", "release-task-compat"))

    def _check_policy(self, run: RunRecord) -> AdmissionCheckResult:
        refs = self._policy_source.resolved_policy_decision_refs(run.run_id)
        if self._policy_source.any_deny(run.run_id):
            return AdmissionCheckResult(False, ("policy_denied",))
        if not refs:
            return AdmissionCheckResult(False, ("missing_policy_decision",))
        return AdmissionCheckResult(True, (), ("policy-decisions",))

    def _check_budget(self, run: RunRecord, budget: BudgetEnvelope) -> AdmissionCheckResult:
        if not run.budget_snapshot_ref:
            return AdmissionCheckResult(False, ("budget_snapshot_missing",))
        if not budget.within({"steps": self._budget_overhead, "model_calls": 0, "tokens": 0}):
            return AdmissionCheckResult(False, ("budget_exhausted",))
        return AdmissionCheckResult(True, (), ("budget-snapshot",))

    def _check_region(self, principal: PrincipalContext) -> AdmissionCheckResult:
        for region in principal.data_regions:
            if region not in self._region_allowlist:
                return AdmissionCheckResult(False, (f"region_not_allowed:{region}",))
        return AdmissionCheckResult(True, (), ("region",))

    def _check_binding(self, run: RunRecord) -> AdmissionCheckResult:
        if not run.runtime_adapter_ref:
            return AdmissionCheckResult(False, ("runtime_adapter_missing",))
        if not run.agent_ref:
            return AdmissionCheckResult(False, ("agent_definition_missing",))
        return AdmissionCheckResult(True, (), ("adapter-binding-frozen",))

    def _capacity_available(self) -> bool:
        # Deterministic single-process default: capacity is available unless a
        # controller-level flag is set. Subclasses/profiles may override.
        return getattr(self, "_capacity_ok", True)

    @staticmethod
    def _expiry(moment: datetime, seconds: int) -> datetime:
        from datetime import timedelta

        return moment + timedelta(seconds=seconds)
