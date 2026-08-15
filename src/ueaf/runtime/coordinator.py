"""Run Coordinator — authoritative State Writer for ``RunRecord``/``TaskState``.

Drives the closed run state machine with CAS/revision, fencing-token checks
and transactional outbox events (CON-013). Edge pre-validation rejections must
never reach this class (RUN-005).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from ueaf.admission.controller import AdmissionController, RunAdmissionResult
from ueaf.admission.objects import TaskEnvelope
from ueaf.common.identifiers import new_object_id
from ueaf.common.meta import ContractMeta
from ueaf.infrastructure.db.repositories import (
    InMemoryAdmissionResultRepository,
    InMemoryRunRecordRepository,
    InMemoryTaskStateRepository,
)
from ueaf.runtime.objects import (
    CompletionDisposition,
    RunLease,
    RunPhase,
    RunRecord,
    TaskState,
    WaitReason,
)
from ueaf.runtime.outbox import OutboxEntry, OutboxStore
from ueaf.runtime.state_machine import (
    StateMachineError,
    validate_transition,
)

EVENT_VERSION = "1.0.0"
PRODUCER = "ueaf-runtime-coordinator"
PRODUCER_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class RunCreateInput:
    task_envelope: TaskEnvelope
    agent_ref: str
    runtime_adapter_ref: str
    release_id: str
    budget_snapshot_ref: str
    trace_id: str | None = None
    parent_run_id: str | None = None
    deadline_at: datetime | None = None
    correlation_id: str | None = None
    actor_ref: str | None = None


class RunCoordinator:
    """Root lifecycle owner: create, admit, wait, resume, retry, pause, cancel, terminal."""

    def __init__(
        self,
        runs: InMemoryRunRecordRepository,
        tasks: InMemoryTaskStateRepository,
        admissions: InMemoryAdmissionResultRepository,
        admission_controller: AdmissionController,
        outbox: OutboxStore,
        clock: object | None = None,
    ) -> None:
        self._runs = runs
        self._tasks = tasks
        self._admissions = admissions
        self._admission = admission_controller
        self._outbox = outbox
        self._now = clock if callable(clock) else _default_now

    # -- creation ----------------------------------------------------------

    def create_run(self, input_: RunCreateInput) -> RunRecord:
        """Create TaskState + RunRecord(queued) with frozen bindings (RUN-007)."""
        moment = self._now()
        task = input_.task_envelope
        run_id = new_object_id("run")
        trace_id = input_.trace_id or new_object_id("trace")

        task_state = TaskState(
            meta=ContractMeta(
                contract_name="TaskState",
                contract_version="1.0.0",
                object_id=task.task_id,
                tenant_id=task.meta.tenant_id,
                created_at=moment,
                producer=PRODUCER,
                producer_version=PRODUCER_VERSION,
                task_id=task.task_id,
                trace_id=trace_id,
            ),
            task_id=task.task_id,
        )
        self._tasks.create(task_state)

        record = RunRecord(
            meta=ContractMeta(
                contract_name="RunRecord",
                contract_version="1.0.0",
                object_id=run_id,
                tenant_id=task.meta.tenant_id,
                created_at=moment,
                producer=PRODUCER,
                producer_version=PRODUCER_VERSION,
                task_id=task.task_id,
                run_id=run_id,
                trace_id=trace_id,
                release_id=input_.release_id,
                request_id=task.request_refs[0] if task.request_refs else None,
            ),
            run_id=run_id,
            task_id=task.task_id,
            agent_ref=input_.agent_ref,
            runtime_adapter_ref=input_.runtime_adapter_ref,
            release_id=input_.release_id,
            phase="queued",
            attempt=1,
            budget_snapshot_ref=input_.budget_snapshot_ref,
            deadline_at=input_.deadline_at,
            parent_run_id=input_.parent_run_id,
            created_at=moment,
            updated_at=moment,
        )
        self._runs.create(record)
        self._outbox.append(self._entry(
            record,
            event_name="ueaf.run.created",
            correlation_id=input_.correlation_id,
            actor_ref=input_.actor_ref,
            payload={
                "run_id": run_id,
                "task_id": task.task_id,
                "release_id": input_.release_id,
                "runtime_adapter_ref": input_.runtime_adapter_ref,
            },
        ))
        return record

    # -- admission ---------------------------------------------------------

    def begin_admission(self, run_id: str, *, actor_ref: str | None = None) -> RunRecord:
        """queued -> admitting (admission lease acquired)."""
        return self._transition(
            run_id,
            to_phase="admitting",
            expected_revision=None,
            event_extra={
                "from_phase": "queued",
                "to_phase": "admitting",
                "reason_codes": ("admission_started",),
            },
            actor_ref=actor_ref,
        )

    def apply_admission(
        self,
        run_id: str,
        result: RunAdmissionResult,
        *,
        actor_ref: str | None = None,
    ) -> RunRecord:
        """Apply a validated admission result: running / waiting / terminal."""
        run = self._runs.require(run_id)
        if run.phase != "admitting":
            raise StateMachineError(run.phase, "running")
        if not result.is_valid_at(self._now()):
            from ueaf.common.error import ERROR_CODES

            raise ValueError(f"{ERROR_CODES['EXPIRED_RESULT']}: admission result expired")

        self._admissions.create(result)
        self._outbox.append(self._entry(
            run,
            event_name=(
                "ueaf.run.admitted"
                if result.outcome == "admitted"
                else "ueaf.run.phase_changed"
            ),
            correlation_id=None,
            actor_ref=actor_ref,
            payload=(
                {"admission_result_ref": result.run_admission_result_id,
                 "budget_snapshot_ref": result.budget_snapshot_ref}
                if result.outcome == "admitted"
                else {
                    "from_phase": "admitting",
                    "to_phase": "terminal",
                    "reason_codes": result.reason_codes,
                }
            ),
        ))

        if result.outcome == "admitted":
            return self._transition(
                run_id,
                to_phase="running",
                expected_revision=run.revision,
                event_extra={
                    "from_phase": "admitting",
                    "to_phase": "running",
                    "reason_codes": result.reason_codes,
                },
                actor_ref=actor_ref,
            )
        if result.outcome == "deferred":
            return self._register_wait(
                run_id,
                wait_reason="dependency",
                condition_refs=result.validation_refs or ("admission_deferred",),
                expires_at=result.retry_after,
                wait_origin="admission_deferred",
                actor_ref=actor_ref,
            )
        return self._commit_terminal(
            run_id,
            disposition="rejected",
            reason_codes=result.reason_codes,
            actor_ref=actor_ref,
        )

    # -- lifecycle commands ------------------------------------------------

    def acquire_lease(
        self, run_id: str, *, holder_id: str, actor_ref: str | None = None
    ) -> RunRecord:
        """Acquire (or renew) the execution lease with a monotonic fencing token.

        A new execution attempt increments ``attempt`` and always issues a
        strictly greater fencing token than any previously issued lease
        (RUN-003, RUN-008).
        """
        run = self._runs.require(run_id)
        if run.phase not in ("admitting", "running", "retrying"):
            raise StateMachineError(run.phase, "running", "lease requires an executing phase")
        moment = self._now()
        previous_token = run.lease.fencing_token if run.lease else 0
        lease = RunLease(
            lease_id=new_object_id("lease"),
            holder_id=holder_id,
            fencing_token=previous_token + 1,
            acquired_at=moment,
            heartbeat_at=moment,
            expires_at=moment + timedelta(seconds=120),
        )
        attempt = run.attempt if run.lease is not None else run.attempt
        if run.lease is None and run.phase == "retrying":
            attempt = run.attempt + 1
        updated = replace(
            run,
            lease=lease,
            attempt=attempt,
            revision=run.revision + 1,
            updated_at=moment,
        )
        self._runs.update(updated, expected_revision=run.revision)
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.phase_changed",
            correlation_id=None,
            actor_ref=actor_ref,
            payload={
                "from_phase": run.phase,
                "to_phase": run.phase,
                "reason_codes": ("lease_acquired",),
            },
        ))
        return updated

    def heartbeat(
        self,
        run_id: str,
        *,
        lease_id: str,
        fencing_token: int,
        actor_ref: str | None = None,
    ) -> RunRecord:
        """Extend a held lease; rejects stale holders (RUN-003)."""
        run = self._runs.require(run_id)
        self._ensure_lease(run, lease_id, fencing_token)
        assert run.lease is not None  # _ensure_lease guarantees an active lease
        moment = self._now()
        if not run.lease.is_held_at(moment):
            from ueaf.common.error import ERROR_CODES

            raise ValueError(
                f"{ERROR_CODES['STALE_FENCING']}: lease expired at {run.lease.expires_at}"
            )
        lease = replace(
            run.lease,
            heartbeat_at=moment,
            expires_at=moment + timedelta(seconds=120),
        )
        updated = replace(run, lease=lease, revision=run.revision + 1, updated_at=moment)
        self._runs.update(updated, expected_revision=run.revision)
        return updated

    def register_wait(
        self,
        run_id: str,
        *,
        wait_reason: WaitReason,
        condition_refs: tuple[str, ...],
        expires_at: datetime | None = None,
        wait_origin: Literal["admission_deferred", "admitted_execution"] | None = None,
        actor_ref: str | None = None,
    ) -> RunRecord:
        return self._register_wait(
            run_id,
            wait_reason=wait_reason,
            condition_refs=condition_refs,
            expires_at=expires_at,
            wait_origin=wait_origin,
            actor_ref=actor_ref,
        )

    def resume(
        self,
        run_id: str,
        *,
        to_phase: Literal["running", "admitting"],
        resume_signal_ref: str,
        validation_refs: tuple[str, ...] = (),
        actor_ref: str | None = None,
    ) -> RunRecord:
        run = self._runs.require(run_id)
        validate_transition(run.phase, to_phase)
        updated = self._apply(
            run,
            to_phase=to_phase,
            clear_wait=True,
            expected_revision=run.revision,
            actor_ref=actor_ref,
        )
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.resumed",
            correlation_id=None,
            actor_ref=actor_ref,
            payload={
                "from_phase": run.phase,
                "resume_signal_ref": resume_signal_ref,
                "validation_refs": validation_refs,
            },
        ))
        return updated

    def schedule_retry(
        self,
        run_id: str,
        *,
        failure_ref: str,
        policy_ref: str,
        not_before: datetime | None = None,
        actor_ref: str | None = None,
    ) -> RunRecord:
        run = self._runs.require(run_id)
        validate_transition(run.phase, "retrying")
        updated = self._apply(
            run,
            to_phase="retrying",
            expected_revision=run.revision,
            actor_ref=actor_ref,
        )
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.retry_scheduled",
            correlation_id=None,
            actor_ref=actor_ref,
            payload={
                "attempt": updated.attempt,
                "not_before": not_before.isoformat() if not_before else None,
                "failure_ref": failure_ref,
                "policy_ref": policy_ref,
            },
        ))
        return updated

    def pause(
        self,
        run_id: str,
        *,
        reason_codes: tuple[str, ...],
        checkpoint_ref: str | None = None,
        actor_ref: str | None = None,
    ) -> RunRecord:
        run = self._runs.require(run_id)
        validate_transition(run.phase, "paused")
        updated = self._apply(
            run,
            to_phase="paused",
            expected_revision=run.revision,
            actor_ref=actor_ref,
        )
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.paused",
            correlation_id=None,
            actor_ref=actor_ref,
            payload={
                "actor_ref": actor_ref or updated.meta.producer,
                "reason_codes": reason_codes,
                "checkpoint_ref": checkpoint_ref,
            },
        ))
        return updated

    def cancel(self, run_id: str, *, actor_ref: str | None = None) -> RunRecord:
        """Legal cancel accepted; no new actions started."""
        run = self._runs.require(run_id)
        if run.phase == "terminal":
            return run
        if run.phase == "running" and run.pending_action_refs:
            raise StateMachineError(run.phase, "terminal", "in-flight actions pending")
        return self._commit_terminal(
            run_id,
            disposition="cancelled",
            reason_codes=("cancelled_by_actor",),
            actor_ref=actor_ref,
        )

    def commit_terminal(
        self,
        run_id: str,
        *,
        disposition: CompletionDisposition,
        reason_codes: tuple[str, ...],
        result_ref: str | None = None,
        error_ref: str | None = None,
        actor_ref: str | None = None,
    ) -> RunRecord:
        return self._commit_terminal(
            run_id,
            disposition=disposition,
            reason_codes=reason_codes,
            result_ref=result_ref,
            error_ref=error_ref,
            actor_ref=actor_ref,
        )

    # -- internals ---------------------------------------------------------

    def _register_wait(
        self,
        run_id: str,
        *,
        wait_reason: WaitReason,
        condition_refs: tuple[str, ...],
        expires_at: datetime | None,
        wait_origin: Literal["admission_deferred", "admitted_execution"] | None,
        actor_ref: str | None,
    ) -> RunRecord:
        run = self._runs.require(run_id)
        if run.phase not in ("admitting", "running", "retrying"):
            raise StateMachineError(run.phase, "waiting")
        updated = replace(
            run,
            phase="waiting",
            wait_reason=wait_reason,
            wait_condition_refs=condition_refs,
            wait_origin=wait_origin,
            revision=run.revision + 1,
            updated_at=self._now(),
            lease=None,
        )
        self._runs.update(updated, expected_revision=run.revision)
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.wait_registered",
            correlation_id=None,
            actor_ref=actor_ref,
            payload={
                "wait_reason": wait_reason,
                "condition_refs": condition_refs,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        ))
        return updated

    def _transition(
        self,
        run_id: str,
        *,
        to_phase: RunPhase,
        expected_revision: int | None,
        event_extra: dict[str, object],
        actor_ref: str | None,
    ) -> RunRecord:
        run = self._runs.require(run_id)
        validate_transition(run.phase, to_phase)
        updated = self._apply(
            run,
            to_phase=to_phase,
            expected_revision=expected_revision,
            actor_ref=actor_ref,
        )
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.phase_changed",
            correlation_id=None,
            actor_ref=actor_ref,
            payload=event_extra,
        ))
        return updated

    def _ensure_lease(self, run: RunRecord, lease_id: str, fencing_token: int) -> None:
        """Reject writes that are not the current lease holder (RUN-003)."""
        if run.lease is None:
            from ueaf.common.error import ERROR_CODES

            raise ValueError(f"{ERROR_CODES['STALE_FENCING']}: no active lease")
        if run.lease.lease_id != lease_id:
            raise StateMachineError(run.phase, run.phase, "lease_id does not match holder")
        if fencing_token < run.lease.fencing_token:
            raise ValueError(f"stale_fencing_token: {fencing_token} < {run.lease.fencing_token}")

    def _commit_terminal(
        self,
        run_id: str,
        *,
        disposition: CompletionDisposition,
        reason_codes: tuple[str, ...],
        result_ref: str | None = None,
        error_ref: str | None = None,
        actor_ref: str | None = None,
    ) -> RunRecord:
        run = self._runs.require(run_id)
        if run.phase == "terminal":
            if run.completion_disposition == disposition:
                return run  # idempotent replay (spec 02 §5.2)
            raise StateMachineError(run.phase, "terminal", "terminal_conflict")
        if disposition == "completed" and run.pending_action_refs:
            raise StateMachineError(
                run.phase, "terminal", "completed must not leave unresolved actions"
            )
        updated = replace(
            run,
            phase="terminal",
            completion_disposition=disposition,
            terminal_reason_codes=reason_codes,
            result_ref=result_ref,
            error_ref=error_ref,
            revision=run.revision + 1,
            updated_at=self._now(),
            lease=None,
        )
        self._runs.update(updated, expected_revision=run.revision)
        self._outbox.append(self._entry(
            updated,
            event_name="ueaf.run.terminal_committed",
            correlation_id=None,
            actor_ref=actor_ref,
            payload={
                "disposition": disposition,
                "reason_codes": reason_codes,
                "result_ref": result_ref,
                "error_ref": error_ref,
            },
        ))
        return updated

    def _apply(
        self,
        run: RunRecord,
        *,
        to_phase: RunPhase,
        expected_revision: int | None,
        actor_ref: str | None,
        clear_wait: bool = False,
    ) -> RunRecord:
        del actor_ref
        updated = replace(
            run,
            phase=to_phase,
            revision=run.revision + 1,
            updated_at=self._now(),
            completion_disposition=(
                None if to_phase != "terminal" else run.completion_disposition
            ),
            wait_reason=None if (clear_wait or to_phase != "waiting") else run.wait_reason,
            wait_condition_refs=(
                () if (clear_wait or to_phase != "waiting") else run.wait_condition_refs
            ),
            wait_origin=None if (clear_wait or to_phase != "waiting") else run.wait_origin,
            lease=None if to_phase in ("queued", "waiting", "paused", "terminal") else run.lease,
        )
        self._runs.update(updated, expected_revision=expected_revision)
        return updated

    def _entry(
        self,
        record: RunRecord,
        *,
        event_name: str,
        correlation_id: str | None,
        actor_ref: str | None,
        payload: dict[str, object],
    ) -> OutboxEntry:
        moment = self._now()
        return OutboxEntry(
            outbox_id=new_object_id("outbox"),
            event_id=new_object_id("evt"),
            event_name=event_name,
            event_version=EVENT_VERSION,
            tenant_id=record.meta.tenant_id,
            aggregate_type="RunRecord",
            aggregate_id=record.run_id,
            aggregate_version=record.revision,
            sequence=record.sequence + 1,
            correlation_id=correlation_id or record.meta.request_id or record.run_id,
            trace_id=record.meta.trace_id or record.run_id,
            payload_schema_ref=self._schema_ref(event_name),
            payload=payload,
            created_at=moment,
            release_id=record.release_id,
            principal_ref=actor_ref,
            classification=record.meta.classification,
            purpose=record.meta.purpose,
        )

    @staticmethod
    def _schema_ref(event_name: str) -> str:
        mapping = {
            "ueaf.run.created": "schema://run-created/1.0.0",
            "ueaf.run.phase_changed": "schema://run-phase-changed/1.0.0",
        }
        return mapping.get(event_name, f"schema://{event_name.split('.')[-1]}/1.0.0")


def _default_now() -> datetime:
    from ueaf.common.identifiers import utcnow

    return utcnow()
