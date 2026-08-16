"""基于 SQLAlchemy 的权威仓库，具备数据库级 CAS/fencing。

每个仓库都必须在 ``Database.session_context()`` 内使用，使状态变更与 outbox
插入共享同一事务。CAS 通过条件 ``UPDATE ... WHERE revision = expected`` 与
rowcount 检查来保证；过期的 fencing token 会与持久化的 lease fencing token
比对后被拒绝。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult

from ueaf.admission.controller import RunAdmissionResult
from ueaf.infrastructure.db.database import Database
from ueaf.infrastructure.db.orm import (
    ActionReceiptORM,
    ActionRecordORM,
    MemoryRecordORM,
    OutboxEntryORM,
    RunAdmissionResultORM,
    RunRecordORM,
    TaskStateORM,
    TurnRecordORM,
)
from ueaf.infrastructure.db.repositories import (
    RevisionConflict,
    StaleFencing,
)
from ueaf.infrastructure.db.serialization import decode_value, encode_value
from ueaf.memory.objects import MemoryRecord
from ueaf.runtime.objects import RunLease, RunRecord, TaskState
from ueaf.runtime.outbox import OutboxEntry
from ueaf.runtime.turn import TurnRecord
from ueaf.tool.action import ActionReceipt, ActionRecord


class SqlRunRecordRepository:
    """具备条件更新 CAS 的 RunRecord 权威存储。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, run_id: str) -> RunRecord | None:
        session = await self._db.session()
        row = await session.get(RunRecordORM, run_id)
        return _record_from_row(row) if row is not None else None

    async def require(self, run_id: str) -> RunRecord:
        record = await self.get(run_id)
        if record is None:
            raise KeyError(f"RunRecord {run_id} not found")
        return record

    async def create(self, record: RunRecord) -> RunRecord:
        session = await self._db.session()
        if await session.get(RunRecordORM, record.run_id) is not None:
            raise ValueError(f"RunRecord {record.run_id} already exists")
        session.add(_record_to_row(record))
        return record

    async def update(
        self,
        current: RunRecord,
        *,
        expected_revision: int | None = None,
        fencing_token: int | None = None,
    ) -> RunRecord:
        session = await self._db.session()
        conditions = [RunRecordORM.run_id == current.run_id]
        if expected_revision is not None:
            conditions.append(RunRecordORM.revision == expected_revision)
        if fencing_token is not None:
            conditions.append(
                or_(
                    RunRecordORM.lease_fencing_token.is_(None),
                    RunRecordORM.lease_fencing_token <= fencing_token,
                )
            )
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(RunRecordORM)
                .where(*conditions)
                .values(
                    task_id=current.task_id,
                    phase=current.phase,
                    completion_disposition=current.completion_disposition,
                    attempt=current.attempt,
                    revision=current.revision,
                    sequence=current.sequence,
                    lease_fencing_token=(
                        current.lease.fencing_token if current.lease is not None else None
                    ),
                    release_id=current.release_id,
                    runtime_adapter_ref=current.runtime_adapter_ref,
                    updated_at=_utcnow(),
                    payload=encode_value(current),
                )
            ),
        )
        if result.rowcount == 0:
            existing = await session.get(RunRecordORM, current.run_id)
            if existing is None:
                raise KeyError(f"RunRecord {current.run_id} not found")
            if (
                fencing_token is not None
                and existing.lease_fencing_token is not None
                and fencing_token < existing.lease_fencing_token
            ):
                raise StaleFencing(current.run_id, fencing_token, existing.lease_fencing_token)
            raise RevisionConflict(current.run_id, expected_revision or 0, existing.revision)
        return current


class SqlTaskStateRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, task_id: str) -> TaskState | None:
        session = await self._db.session()
        row = await session.get(TaskStateORM, task_id)
        return _task_state_from_row(row) if row is not None else None

    async def create(self, state: TaskState) -> TaskState:
        session = await self._db.session()
        if await session.get(TaskStateORM, state.task_id) is not None:
            raise ValueError(f"TaskState {state.task_id} already exists")
        session.add(
            TaskStateORM(
                task_id=state.task_id,
                tenant_id=state.meta.tenant_id,
                revision=state.revision,
                updated_at=_utcnow(),
                payload=encode_value(state),
            )
        )
        return state

    async def update(self, state: TaskState, *, expected_revision: int | None = None) -> TaskState:
        session = await self._db.session()
        conditions = [TaskStateORM.task_id == state.task_id]
        if expected_revision is not None:
            conditions.append(TaskStateORM.revision == expected_revision)
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(TaskStateORM)
                .where(*conditions)
                .values(
                    revision=state.revision,
                    updated_at=_utcnow(),
                    payload=encode_value(state),
                )
            ),
        )
        if result.rowcount == 0:
            existing = await session.get(TaskStateORM, state.task_id)
            if existing is None:
                raise KeyError(f"TaskState {state.task_id} not found")
            raise RevisionConflict(state.task_id, expected_revision or 0, existing.revision)
        return state


class SqlAdmissionResultRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, result_id: str) -> RunAdmissionResult | None:
        session = await self._db.session()
        row = await session.get(RunAdmissionResultORM, result_id)
        return _admission_from_row(row) if row is not None else None

    async def create(self, result: RunAdmissionResult) -> RunAdmissionResult:
        session = await self._db.session()
        if await session.get(RunAdmissionResultORM, result.run_admission_result_id) is not None:
            raise ValueError(f"RunAdmissionResult {result.run_admission_result_id} already exists")
        session.add(
            RunAdmissionResultORM(
                run_admission_result_id=result.run_admission_result_id,
                run_id=result.run_id,
                tenant_id=result.meta.tenant_id,
                outcome=result.outcome,
                created_at=result.created_at or _utcnow(),
                expires_at=result.expires_at,
                payload=encode_value(result),
            )
        )
        return result


class SqlOutboxStore:
    """共享当前事务的 outbox 存储（CON-013）。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def append(self, entry: OutboxEntry) -> None:
        session = await self._db.session()
        existing = (
            await session.execute(
                select(OutboxEntryORM.event_id).where(OutboxEntryORM.event_id == entry.event_id)
            )
        ).first()
        if existing is not None:
            raise ValueError(f"duplicate outbox event_id {entry.event_id}")
        session.add(
            OutboxEntryORM(
                outbox_id=entry.outbox_id,
                event_id=entry.event_id,
                event_name=entry.event_name,
                event_version=entry.event_version,
                tenant_id=entry.tenant_id,
                aggregate_type=entry.aggregate_type,
                aggregate_id=entry.aggregate_id,
                aggregate_version=entry.aggregate_version,
                sequence=entry.sequence,
                correlation_id=entry.correlation_id,
                trace_id=entry.trace_id,
                payload_schema_ref=entry.payload_schema_ref,
                created_at=entry.created_at,
                published_at=entry.published_at,
                attempt_count=entry.attempt_count,
                payload=encode_value(entry.payload),
            )
        )

    async def unpublished(self) -> list[OutboxEntry]:
        session = await self._db.session()
        rows = (
            (
                await session.execute(
                    select(OutboxEntryORM)
                    .where(OutboxEntryORM.published_at.is_(None))
                    .order_by(OutboxEntryORM.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [_entry_from_row(row) for row in rows]

    async def mark_published(self, event_id: str, at: datetime | None = None) -> None:
        session = await self._db.session()
        row = (
            await session.execute(select(OutboxEntryORM).where(OutboxEntryORM.event_id == event_id))
        ).scalar_one_or_none()
        if row is None:
            raise KeyError(f"no outbox entry for {event_id}")
        row.published_at = at or _utcnow()
        row.attempt_count = row.attempt_count + 1

    async def dedupe_event_id(self, event_id: str) -> bool:
        session = await self._db.session()
        row = (
            await session.execute(select(OutboxEntryORM).where(OutboxEntryORM.event_id == event_id))
        ).scalar_one_or_none()
        return row is not None and row.published_at is not None


class SqlActionRecordRepository:
    """具备条件更新 CAS/fencing 的 ActionRecord 权威存储。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, action_id: str) -> ActionRecord | None:
        session = await self._db.session()
        row = await session.get(ActionRecordORM, action_id)
        return _action_from_row(row) if row is not None else None

    async def require(self, action_id: str) -> ActionRecord:
        record = await self.get(action_id)
        if record is None:
            raise KeyError(f"ActionRecord {action_id} not found")
        return record

    async def create(self, record: ActionRecord) -> ActionRecord:
        session = await self._db.session()
        if await session.get(ActionRecordORM, record.action_id) is not None:
            raise ValueError(f"ActionRecord {record.action_id} already exists")
        session.add(_action_to_row(record))
        return record

    async def update(
        self,
        current: ActionRecord,
        *,
        expected_revision: int | None = None,
        fencing_token: int | None = None,
    ) -> ActionRecord:
        session = await self._db.session()
        conditions = [ActionRecordORM.action_id == current.action_id]
        if expected_revision is not None:
            conditions.append(ActionRecordORM.revision == expected_revision)
        if fencing_token is not None:
            conditions.append(
                or_(
                    ActionRecordORM.lease_fencing_token.is_(None),
                    ActionRecordORM.lease_fencing_token <= fencing_token,
                )
            )
        result = cast(
            "CursorResult[Any]",
            await session.execute(
                update(ActionRecordORM)
                .where(*conditions)
                .values(
                    phase=current.phase,
                    disposition=current.disposition,
                    attempt=current.attempt,
                    revision=current.revision,
                    sequence=current.sequence,
                    lease_fencing_token=current.lease_fencing_token,
                    updated_at=_utcnow(),
                    payload=encode_value(current),
                )
            ),
        )
        if result.rowcount == 0:
            existing = await session.get(ActionRecordORM, current.action_id)
            if existing is None:
                raise KeyError(f"ActionRecord {current.action_id} not found")
            if (
                fencing_token is not None
                and existing.lease_fencing_token is not None
                and fencing_token < existing.lease_fencing_token
            ):
                raise StaleFencing(current.action_id, fencing_token, existing.lease_fencing_token)
            raise RevisionConflict(current.action_id, expected_revision or 0, existing.revision)
        return current

    async def list_for_run(self, run_id: str) -> list[ActionRecord]:
        session = await self._db.session()
        rows = (
            (
                await session.execute(
                    select(ActionRecordORM)
                    .where(ActionRecordORM.run_id == run_id)
                    .order_by(ActionRecordORM.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [_action_from_row(row) for row in rows]


class SqlActionReceiptRepository:
    """只追加的 ActionReceipt 存储（副作用证据）。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, action_receipt_id: str) -> ActionReceipt | None:
        session = await self._db.session()
        row = await session.get(ActionReceiptORM, action_receipt_id)
        return _receipt_from_row(row) if row is not None else None

    async def create(self, receipt: ActionReceipt) -> ActionReceipt:
        session = await self._db.session()
        if await session.get(ActionReceiptORM, receipt.action_receipt_id) is not None:
            raise ValueError(f"ActionReceipt {receipt.action_receipt_id} already exists")
        session.add(_receipt_to_row(receipt))
        return receipt

    async def list_for_key(self, action_key: str) -> list[ActionReceipt]:
        session = await self._db.session()
        rows = (
            (
                await session.execute(
                    select(ActionReceiptORM)
                    .where(ActionReceiptORM.action_key == action_key)
                    .order_by(ActionReceiptORM.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [_receipt_from_row(row) for row in rows]


class SqlTurnRecordRepository:
    """只追加的 TurnRecord 存储（每次运行轮次的权威序列）。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, turn_id: str) -> TurnRecord | None:
        session = await self._db.session()
        row = await session.get(TurnRecordORM, turn_id)
        return _turn_from_row(row) if row is not None else None

    async def add(self, turn: TurnRecord) -> TurnRecord:
        session = await self._db.session()
        if await session.get(TurnRecordORM, turn.turn_id) is not None:
            raise ValueError(f"TurnRecord {turn.turn_id} already exists")
        session.add(_turn_to_row(turn))
        return turn

    async def list_for_run(self, run_id: str) -> list[TurnRecord]:
        session = await self._db.session()
        rows = (
            (
                await session.execute(
                    select(TurnRecordORM)
                    .where(TurnRecordORM.run_id == run_id)
                    .order_by(TurnRecordORM.turn_no)
                )
            )
            .scalars()
            .all()
        )
        return [_turn_from_row(row) for row in rows]


class SqlMemoryRecordRepository:
    """受治理的记忆存储；Memory Service 是唯一写入方。"""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def get(self, record_id: str) -> MemoryRecord | None:
        session = await self._db.session()
        row = await session.get(MemoryRecordORM, record_id)
        return _memory_from_row(row) if row is not None else None

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        session = await self._db.session()
        if await session.get(MemoryRecordORM, record.record_id) is not None:
            raise ValueError(f"MemoryRecord {record.record_id} already exists")
        session.add(_memory_to_row(record))
        return record

    async def list_for_subject(
        self, subject_ref: str, *, status: str | None = None
    ) -> list[MemoryRecord]:
        session = await self._db.session()
        stmt = select(MemoryRecordORM).where(MemoryRecordORM.subject_ref == subject_ref)
        if status is not None:
            stmt = stmt.where(MemoryRecordORM.status == status)
        rows = (await session.execute(stmt.order_by(MemoryRecordORM.created_at))).scalars().all()
        return [_memory_from_row(row) for row in rows]


# -- 行 <-> 对象映射 ----------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _record_to_row(record: RunRecord) -> RunRecordORM:
    return RunRecordORM(
        run_id=record.run_id,
        tenant_id=record.meta.tenant_id,
        task_id=record.task_id,
        phase=record.phase,
        completion_disposition=record.completion_disposition,
        attempt=record.attempt,
        revision=record.revision,
        sequence=record.sequence,
        lease_fencing_token=record.lease.fencing_token if record.lease is not None else None,
        release_id=record.release_id,
        runtime_adapter_ref=record.runtime_adapter_ref,
        created_at=record.created_at or _utcnow(),
        updated_at=record.updated_at or _utcnow(),
        payload=encode_value(record),
    )


def _record_from_row(row: RunRecordORM) -> RunRecord:
    record = decode_value(row.payload)
    if not isinstance(record, RunRecord):
        raise ValueError(f"corrupt run_records payload for {row.run_id}")
    return record


def _task_state_from_row(row: TaskStateORM) -> TaskState:
    state = decode_value(row.payload)
    if not isinstance(state, TaskState):
        raise ValueError(f"corrupt task_states payload for {row.task_id}")
    return state


def _admission_from_row(row: RunAdmissionResultORM) -> RunAdmissionResult:
    result = decode_value(row.payload)
    if not isinstance(result, RunAdmissionResult):
        raise ValueError(f"corrupt run_admission_results payload for {row.run_admission_result_id}")
    return result


def _entry_from_row(row: OutboxEntryORM) -> OutboxEntry:
    payload = decode_value(row.payload)
    if not isinstance(payload, dict):
        raise ValueError(f"corrupt outbox payload for {row.event_id}")
    return OutboxEntry(
        outbox_id=row.outbox_id,
        event_id=row.event_id,
        event_name=row.event_name,
        event_version=row.event_version,
        tenant_id=row.tenant_id,
        aggregate_type=row.aggregate_type,
        aggregate_id=row.aggregate_id,
        aggregate_version=row.aggregate_version,
        sequence=row.sequence,
        correlation_id=row.correlation_id,
        trace_id=row.trace_id,
        payload_schema_ref=row.payload_schema_ref,
        payload=payload,
        created_at=row.created_at,
        release_id=None,
        principal_ref=None,
        causation_id=None,
        published_at=row.published_at,
        attempt_count=row.attempt_count,
    )


def _action_to_row(record: ActionRecord) -> ActionRecordORM:
    return ActionRecordORM(
        action_id=record.action_id,
        tenant_id=record.meta.tenant_id,
        run_id=record.run_id,
        action_key=record.action_key,
        capability_ref=record.capability_ref,
        phase=record.phase,
        disposition=record.disposition,
        attempt=record.attempt,
        revision=record.revision,
        sequence=record.sequence,
        lease_fencing_token=record.lease_fencing_token,
        created_at=record.created_at or _utcnow(),
        updated_at=record.updated_at or _utcnow(),
        payload=encode_value(record),
    )


def _action_from_row(row: ActionRecordORM) -> ActionRecord:
    record = decode_value(row.payload)
    if not isinstance(record, ActionRecord):
        raise ValueError(f"corrupt action_records payload for {row.action_id}")
    return record


def _receipt_to_row(receipt: ActionReceipt) -> ActionReceiptORM:
    return ActionReceiptORM(
        action_receipt_id=receipt.action_receipt_id,
        action_key=receipt.action_key,
        action_fingerprint=receipt.action_fingerprint,
        capability_ref=receipt.capability_ref,
        executor_ref=receipt.executor_ref,
        status=receipt.status,
        attempt=receipt.attempt,
        started_at=receipt.started_at,
        finished_at=receipt.finished_at,
        created_at=receipt.finished_at or _utcnow(),
        payload=encode_value(receipt),
    )


def _receipt_from_row(row: ActionReceiptORM) -> ActionReceipt:
    receipt = decode_value(row.payload)
    if not isinstance(receipt, ActionReceipt):
        raise ValueError(f"corrupt action_receipts payload for {row.action_receipt_id}")
    return receipt


def _turn_to_row(turn: TurnRecord) -> TurnRecordORM:
    return TurnRecordORM(
        turn_id=turn.turn_id,
        run_id=turn.run_id,
        tenant_id=turn.meta.tenant_id,
        turn_no=turn.turn_no,
        outcome=turn.outcome,
        created_at=turn.created_at or _utcnow(),
        payload=encode_value(turn),
    )


def _turn_from_row(row: TurnRecordORM) -> TurnRecord:
    turn = decode_value(row.payload)
    if not isinstance(turn, TurnRecord):
        raise ValueError(f"corrupt turn_records payload for {row.turn_id}")
    return turn


def _memory_to_row(record: MemoryRecord) -> MemoryRecordORM:
    return MemoryRecordORM(
        record_id=record.record_id,
        subject_ref=record.subject_ref,
        tenant_id=record.meta.tenant_id,
        scope=record.scope,
        sensitivity=record.sensitivity,
        status=record.status,
        created_at=record.valid_from,
        payload=encode_value(record),
    )


def _memory_from_row(row: MemoryRecordORM) -> MemoryRecord:
    record = decode_value(row.payload)
    if not isinstance(record, MemoryRecord):
        raise ValueError(f"corrupt memory_records payload for {row.record_id}")
    return record


__all__ = [
    "RunLease",
    "SqlRunRecordRepository",
    "SqlTaskStateRepository",
    "SqlAdmissionResultRepository",
    "SqlOutboxStore",
    "SqlActionRecordRepository",
    "SqlActionReceiptRepository",
    "SqlTurnRecordRepository",
    "SqlMemoryRecordRepository",
]
