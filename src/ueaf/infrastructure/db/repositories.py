"""In-memory authoritative repositories with CAS/revision semantics.

Port-first default for local/CI: repositories are the only write path for
authoritative state. A PostgreSQL-backed implementation can swap in later
without changing the coordinator logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar

from ueaf.admission.controller import RunAdmissionResult
from ueaf.common.error import ERROR_CODES
from ueaf.runtime.objects import RunRecord, TaskState

T = TypeVar("T")

# Re-export stable error codes used by repository conflicts.
REVISION_CONFLICT = ERROR_CODES["REVISION_CONFLICT"]
STALE_FENCING = ERROR_CODES["STALE_FENCING"]
IDEMPOTENCY_CONFLICT = ERROR_CODES["IDEMPOTENCY_CONFLICT"]


class RevisionConflict(RuntimeError):
    """Raised when an optimistic CAS update fails."""

    code = REVISION_CONFLICT

    def __init__(self, aggregate: str, expected: int, actual: int) -> None:
        self.aggregate = aggregate
        self.expected = expected
        self.actual = actual
        super().__init__(f"revision_conflict {aggregate}: expected {expected}, got {actual}")


class StaleFencing(RuntimeError):
    """Raised when a write carries a fencing token below the current one."""

    code = STALE_FENCING

    def __init__(self, aggregate: str, expected: int, current: int) -> None:
        self.aggregate = aggregate
        self.expected = expected
        self.current = current
        super().__init__(f"stale_fencing_token {aggregate}: {expected} < {current}")


class Versioned(Protocol):
    revision: int


class Repository[T]:
    """Minimal CAS repository contract."""


@dataclass(slots=True)
class InMemoryRunRecordRepository:
    """Authoritative store for RunRecord with revision CAS."""

    _records: dict[str, RunRecord] = field(default_factory=dict)

    def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    def require(self, run_id: str) -> RunRecord:
        record = self._records.get(run_id)
        if record is None:
            raise KeyError(f"RunRecord {run_id} not found")
        return record

    def create(self, record: RunRecord) -> RunRecord:
        if record.run_id in self._records:
            raise ValueError(f"RunRecord {record.run_id} already exists")
        self._records[record.run_id] = record
        return record

    def update(
        self,
        current: RunRecord,
        *,
        expected_revision: int | None = None,
        fencing_token: int | None = None,
    ) -> RunRecord:
        existing = self.require(current.run_id)
        if expected_revision is not None and existing.revision != expected_revision:
            raise RevisionConflict(current.run_id, expected_revision, existing.revision)
        if fencing_token is not None:
            current_fencing = existing.lease.fencing_token if existing.lease else 0
            if fencing_token < current_fencing:
                raise StaleFencing(current.run_id, fencing_token, current_fencing)
        self._records[current.run_id] = current
        return current


@dataclass(slots=True)
class InMemoryTaskStateRepository:
    _states: dict[str, TaskState] = field(default_factory=dict)

    def get(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    def create(self, state: TaskState) -> TaskState:
        if state.task_id in self._states:
            raise ValueError(f"TaskState {state.task_id} already exists")
        self._states[state.task_id] = state
        return state

    def update(self, state: TaskState, *, expected_revision: int | None = None) -> TaskState:
        existing = self._states.get(state.task_id)
        if existing is None:
            raise KeyError(f"TaskState {state.task_id} not found")
        if expected_revision is not None and existing.revision != expected_revision:
            raise RevisionConflict(state.task_id, expected_revision, existing.revision)
        self._states[state.task_id] = state
        return state


@dataclass(slots=True)
class InMemoryAdmissionResultRepository:
    _results: dict[str, RunAdmissionResult] = field(default_factory=dict)

    def get(self, result_id: str) -> RunAdmissionResult | None:
        return self._results.get(result_id)

    def create(self, result: RunAdmissionResult) -> RunAdmissionResult:
        if result.run_admission_result_id in self._results:
            raise ValueError(
                f"RunAdmissionResult {result.run_admission_result_id} already exists"
            )
        self._results[result.run_admission_result_id] = result
        return result


@dataclass(slots=True)
class Clock:
    """Injected time source; tests may advance it deterministically."""

    now: datetime | None = None

    def __call__(self) -> datetime:
        from ueaf.common.identifiers import utcnow

        return self.now if self.now is not None else utcnow()
