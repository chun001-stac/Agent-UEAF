"""具备 CAS/版本号语义的内存权威仓库。

面向本地/CI 的端口优先默认实现：仓库是权威状态的唯一写入路径。后续可无缝替换
为 PostgreSQL 后端实现，而无需改动协调器逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, TypeVar

from ueaf.admission.controller import RunAdmissionResult
from ueaf.common.error import ERROR_CODES
from ueaf.runtime.objects import RunRecord, TaskState

T = TypeVar("T")

# 重新导出仓库冲突所用的稳定错误码。
REVISION_CONFLICT = ERROR_CODES["REVISION_CONFLICT"]
STALE_FENCING = ERROR_CODES["STALE_FENCING"]
IDEMPOTENCY_CONFLICT = ERROR_CODES["IDEMPOTENCY_CONFLICT"]


class RevisionConflict(RuntimeError):
    """当乐观 CAS 更新失败时抛出。"""

    code = REVISION_CONFLICT

    def __init__(self, aggregate: str, expected: int, actual: int) -> None:
        self.aggregate = aggregate
        self.expected = expected
        self.actual = actual
        super().__init__(f"revision_conflict {aggregate}: expected {expected}, got {actual}")


class StaleFencing(RuntimeError):
    """当写入携带的 fencing token 低于当前值时抛出。"""

    code = STALE_FENCING

    def __init__(self, aggregate: str, expected: int, current: int) -> None:
        self.aggregate = aggregate
        self.expected = expected
        self.current = current
        super().__init__(f"stale_fencing_token {aggregate}: {expected} < {current}")


class Versioned(Protocol):
    revision: int


class Repository[T]:
    """最小化的 CAS 仓库契约。"""


class RunRecordRepository(Protocol):
    """内存与 SQL RunRecord 存储的公共契约。"""

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def require(self, run_id: str) -> RunRecord: ...

    async def create(self, record: RunRecord) -> RunRecord: ...

    async def update(
        self,
        current: RunRecord,
        *,
        expected_revision: int | None = None,
        fencing_token: int | None = None,
    ) -> RunRecord: ...


class TaskStateRepository(Protocol):
    async def get(self, task_id: str) -> TaskState | None: ...

    async def create(self, state: TaskState) -> TaskState: ...

    async def update(
        self, state: TaskState, *, expected_revision: int | None = None
    ) -> TaskState: ...


class AdmissionResultRepository(Protocol):
    async def get(self, result_id: str) -> RunAdmissionResult | None: ...

    async def create(self, result: RunAdmissionResult) -> RunAdmissionResult: ...


@dataclass(slots=True)
class InMemoryRunRecordRepository:
    """带版本 CAS 的 RunRecord 权威存储。"""

    _records: dict[str, RunRecord] = field(default_factory=dict)

    async def get(self, run_id: str) -> RunRecord | None:
        return self._records.get(run_id)

    async def require(self, run_id: str) -> RunRecord:
        record = self._records.get(run_id)
        if record is None:
            raise KeyError(f"RunRecord {run_id} not found")
        return record

    async def create(self, record: RunRecord) -> RunRecord:
        if record.run_id in self._records:
            raise ValueError(f"RunRecord {record.run_id} already exists")
        self._records[record.run_id] = record
        return record

    async def update(
        self,
        current: RunRecord,
        *,
        expected_revision: int | None = None,
        fencing_token: int | None = None,
    ) -> RunRecord:
        existing = self._records.get(current.run_id)
        if existing is None:
            raise KeyError(f"RunRecord {current.run_id} not found")
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

    async def get(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    async def create(self, state: TaskState) -> TaskState:
        if state.task_id in self._states:
            raise ValueError(f"TaskState {state.task_id} already exists")
        self._states[state.task_id] = state
        return state

    async def update(
        self, state: TaskState, *, expected_revision: int | None = None
    ) -> TaskState:
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

    async def get(self, result_id: str) -> RunAdmissionResult | None:
        return self._results.get(result_id)

    async def create(self, result: RunAdmissionResult) -> RunAdmissionResult:
        if result.run_admission_result_id in self._results:
            raise ValueError(
                f"RunAdmissionResult {result.run_admission_result_id} already exists"
            )
        self._results[result.run_admission_result_id] = result
        return result


@dataclass(slots=True)
class Clock:
    """注入的时间源；测试可确定性地推进它。"""

    now: datetime | None = None

    def __call__(self) -> datetime:
        from ueaf.common.identifiers import utcnow

        return self.now if self.now is not None else utcnow()
