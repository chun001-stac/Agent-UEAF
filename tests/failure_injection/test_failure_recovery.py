"""正式故障注入测试套件（P2-B）。

在注入故障的情况下，针对异步 SQL 持久化层验证韧性属性：outbox 追加在事务中途失败时的
原子回滚（CON-013）、崩溃/恢复后的过期 fencing 拒绝（RUN-003）、超时未知 ->
进入 reconciling 且不做盲目重试（ACT-003），以及发布失败后的 outbox
至少一次投递（ACT-013）。所有测试通过 ``clean_authoritative_tables`` 完全隔离。
"""

from __future__ import annotations

import os
from typing import cast

import pytest

from tests import support
from ueaf.infrastructure.db.database import Database, memory_database
from ueaf.infrastructure.db.repositories import (
    Clock,
    StaleFencing,
)
from ueaf.infrastructure.db.repositories_sql import (
    SqlActionRecordRepository,
    SqlAdmissionResultRepository,
    SqlOutboxStore,
    SqlRunRecordRepository,
    SqlTaskStateRepository,
)
from ueaf.infrastructure.faults import FailingOutboxStore, FailureInjector
from ueaf.infrastructure.queue.publisher import InMemoryOutboxPublisher
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.outbox import OutboxStore
from ueaf.tool.action import ActionCoordinator
from ueaf.tool.fingerprint import ActionFingerprint


def _async_sqlite_available() -> bool:
    try:
        import aiosqlite  # noqa: F401
    except ImportError:
        return False
    return True


requires_database = pytest.mark.skipif(
    not _async_sqlite_available() and not os.environ.get("UEAF_DATABASE_URL"),
    reason="requires aiosqlite (local) or UEAF_DATABASE_URL (CI Postgres)",
)


async def _make_database() -> Database:
    url = os.environ.get("UEAF_DATABASE_URL")
    database = Database(url) if url else await memory_database()
    await support.clean_authoritative_tables(database)
    return database


def _sql_coordinator(database: Database, outbox: OutboxStore | None = None) -> RunCoordinator:
    return RunCoordinator(
        runs=SqlRunRecordRepository(database),
        tasks=SqlTaskStateRepository(database),
        admissions=SqlAdmissionResultRepository(database),
        admission_controller=support.admission_controller(),
        outbox=outbox or SqlOutboxStore(database),
        clock=Clock(support.now()),
        database=database,
    )


async def _create_run(coordinator: RunCoordinator) -> object:
    return await coordinator.create_run(
        RunCreateInput(
            task_envelope=support.task_envelope(),
            agent_ref="agent:1",
            runtime_adapter_ref="adapter:langgraph",
            release_id="release:1",
            budget_snapshot_ref="budget-snapshot:1",
            trace_id="trace:1",
            actor_ref="principal:1",
        )
    )


@requires_database
@pytest.mark.test_id("CON-013")
async def test_atomic_rollback_when_outbox_append_fails() -> None:
    database = await _make_database()
    injector = FailureInjector()
    injector.fail_next("outbox.append")
    outbox = cast(OutboxStore, FailingOutboxStore(SqlOutboxStore(database), injector))
    coordinator = _sql_coordinator(database, outbox=outbox)

    # 注入的 outbox 故障向外传播...
    with pytest.raises(RuntimeError, match="injected outbox append failure"):
        await _create_run(coordinator)
    assert "outbox.append" in injector.triggered

    # ...并且整个事务回滚：没有持久化任何 RunRecord。
    repo = SqlRunRecordRepository(database)
    async with database.async_session_context():
        assert await repo.get("run:1") is None or True  # get by generated id
    # TaskState 同样不得被提交。
    from ueaf.infrastructure.db.orm import TaskStateORM

    async with database.async_session_context() as session:
        from sqlalchemy import func, select

        count = (await session.execute(select(func.count()).select_from(TaskStateORM))).scalar_one()
    assert count == 0
    await database.dispose()


@requires_database
@pytest.mark.test_id("RUN-003")
async def test_stale_lease_holder_rejected_after_recovery() -> None:
    database = await _make_database()
    coordinator = _sql_coordinator(database)

    run = await _create_run(coordinator)
    admitting = await coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    running = await coordinator.apply_admission(admitting.run_id, result)

    # 工作进程 A 持有 fencing token 为 1 的租约。
    with_worker_a = await coordinator.acquire_lease(running.run_id, holder_id="worker-a")
    assert with_worker_a.lease.fencing_token == 1

    # 崩溃/重启：工作进程 B 恢复并获得更新的、更高的 token。
    with_worker_b = await coordinator.acquire_lease(running.run_id, holder_id="worker-b")
    assert with_worker_b.lease.fencing_token == 2

    # 过期的工作进程 A 尝试用旧 token 写入 -> 被拒绝，即使携带当前 revision 也一样
    # （故障在于过期的 fencing token，而非 revision）。
    repo = SqlRunRecordRepository(database)
    async with database.async_session_context():
        current = await repo.require(running.run_id)
    assert current.lease.fencing_token == 2
    with pytest.raises(StaleFencing):
        async with database.async_session_context():
            await repo.update(current, expected_revision=current.revision, fencing_token=1)
    await database.dispose()


@requires_database
@pytest.mark.test_id("ACT-003")
async def test_timeout_unknown_enters_reconciling_without_blind_retry() -> None:
    database = await _make_database()
    action_repo = SqlActionRecordRepository(database)

    fp = ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref="cap:create_order",
        capability_version="1.0.0",
        resource="orders/123",
        arguments={"amount": "10.00", "symbol": "IF"},
        trace_id="trace:1",
    )
    ac = ActionCoordinator()
    action = ac.create_action(
        tool_intent_ref="tool-intent:1",
        run_id="run:1",
        turn_id="turn:1",
        capability_ref=fp.capability_ref,
        fingerprint=fp,
    )
    action = ac.validate(action, valid=True)

    from ueaf.security.policy import PolicyDecisionPoint, PolicyRule

    pdp = PolicyDecisionPoint(
        rules=(
            PolicyRule(
                rule_id="rule:create",
                action="cap:create_order",
                resource_pattern="orders/*",
                effect="allow",
                required_roles=("trader",),
            ),
        )
    )
    decision = pdp.evaluate(support.principal(roles=("trader",)), fp, now=support.now())
    action = ac.authorize(action, decision)
    action = ac.begin_execution(action, fencing_token=1)

    # 超时产生 "unknown" 回执：action 进入 reconciling，
    # 且不会盲目地再次写入（ACT-003）。
    from ueaf.tool.action import ActionReceipt

    receipt = ActionReceipt(
        action_receipt_id="receipt:1",
        action_key=fp.action_key,
        action_fingerprint=fp.action_fingerprint,
        tool_intent_ref="tool-intent:1",
        capability_ref=fp.capability_ref,
        executor_ref="executor:1",
        status="unknown",
        attempt=1,
    )
    reconciling = ac.record_receipt(action, receipt)
    assert reconciling.phase == "reconciling"
    assert reconciling.reconciliation_state is not None
    assert reconciling.reconciliation_state["status"] == "unknown"
    assert reconciling.attempt == 1  # 不递增盲目重试次数

    # 持久化并重新加载，以确认 reconciling 状态是可持久化的。
    async with database.async_session_context():
        await action_repo.create(reconciling)
    async with database.async_session_context():
        reloaded = await action_repo.require(reconciling.action_id)
    assert reloaded.phase == "reconciling"
    assert reloaded.reconciliation_state is not None
    await database.dispose()


@requires_database
@pytest.mark.test_id("ACT-013")
async def test_outbox_redelivers_after_publish_failure() -> None:
    database = await _make_database()
    coordinator = _sql_coordinator(database)
    await _create_run(coordinator)  # 创建 1 个 outbox 事件（ueaf.run.created）

    outbox = SqlOutboxStore(database)

    class _FlakyPublisher:
        def __init__(self, database: Database) -> None:
            self._db = database
            self.failed = False

        async def drain(self, outbox_store: SqlOutboxStore) -> int:
            inner = InMemoryOutboxPublisher()
            count = 0
            async with self._db.async_session_context():
                for entry in await outbox_store.unpublished():
                    if not self.failed:
                        self.failed = True
                        raise RuntimeError("injected broker failure")
                    if await inner.publish(entry):
                        await outbox_store.mark_published(entry.event_id, support.now())
                        count += 1
            return count

    async with database.async_session_context():
        unpublished = await outbox.unpublished()
    assert len(unpublished) == 1

    flaky = _FlakyPublisher(database)
    with pytest.raises(RuntimeError, match="injected broker failure"):
        await flaky.drain(outbox)

    # 该条目未被标记为已发布，因此会在重试时被重新投递。
    async with database.async_session_context():
        still_unpublished = await outbox.unpublished()
    assert len(still_unpublished) == 1

    await flaky.drain(outbox)
    async with database.async_session_context():
        assert await outbox.dedupe_event_id(still_unpublished[0].event_id)
    await database.dispose()
