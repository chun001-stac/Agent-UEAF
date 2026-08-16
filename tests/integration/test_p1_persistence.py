"""P1 持久化测试：action/turn/memory SQL 仓库（实施规范 03）。

针对异步 SQLite 或真实 PostgreSQL（``UEAF_DATABASE_URL``）验证 P1 权威对象
（``ActionRecord``、``ActionReceipt``、``TurnRecord``、``MemoryRecord``）
的数据库级 CAS/fencing 以及规范对象往返。
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from tests import support
from ueaf.infrastructure.db.database import Database, memory_database
from ueaf.infrastructure.db.repositories import (
    RevisionConflict,
    StaleFencing,
)
from ueaf.infrastructure.db.repositories_sql import (
    SqlActionReceiptRepository,
    SqlActionRecordRepository,
    SqlMemoryRecordRepository,
    SqlTurnRecordRepository,
)
from ueaf.memory.objects import MemoryRecord
from ueaf.runtime.turn import TurnRecord
from ueaf.tool.action import ActionCoordinator, ActionReceipt
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


def _fingerprint() -> ActionFingerprint:
    return ActionFingerprint(
        tenant_id=support.TENANT,
        principal_id="principal-user-1",
        capability_ref="cap:create_order",
        capability_version="1.0.0",
        resource="orders/123",
        arguments={"amount": "10.00", "symbol": "IF"},
        trace_id="trace:1",
    )


def _action(fingerprint: ActionFingerprint | None = None):
    fp = fingerprint or _fingerprint()
    coordinator = ActionCoordinator()
    action = coordinator.create_action(
        tool_intent_ref=f"tool-intent:{fp.action_fingerprint[:12]}",
        run_id="run:1",
        turn_id="turn:1",
        capability_ref=fp.capability_ref,
        fingerprint=fp,
    )
    return coordinator.validate(action, valid=True)


@requires_database
@pytest.mark.test_id("ACT-007")
async def test_action_record_persistence_enforces_cas_and_fencing() -> None:
    database = await _make_database()
    repo = SqlActionRecordRepository(database)

    action = _action()
    async with database.async_session_context():
        await repo.create(action)
    async with database.async_session_context():
        reloaded = await repo.require(action.action_id)
    assert reloaded.meta.object_id == action.action_id
    assert reloaded.meta.contract_name == "ActionRecord"
    assert reloaded.phase == "validating"

    # 推进权威状态（设置 fencing token、递增 revision）。
    advanced = replace(
        reloaded,
        phase="authorizing",
        revision=reloaded.revision + 1,
        lease_fencing_token=1,
    )
    async with database.async_session_context():
        await repo.update(advanced, expected_revision=reloaded.revision, fencing_token=1)

    # 过期 revision 的更新必须被数据库级 CAS 拒绝。
    with pytest.raises(RevisionConflict):
        async with database.async_session_context():
            await repo.update(advanced, expected_revision=1, fencing_token=1)

    # 过期的 fencing token 必须被拒绝。
    with pytest.raises(StaleFencing):
        async with database.async_session_context():
            await repo.update(
                replace(advanced, phase="reserved", revision=advanced.revision + 1),
                expected_revision=advanced.revision,
                fencing_token=0,
            )

    # 按 run 范围查询可返回已持久化的 action。
    async with database.async_session_context():
        actions = await repo.list_for_run("run:1")
    assert [a.action_id for a in actions] == [action.action_id]
    await database.dispose()


@requires_database
@pytest.mark.test_id("ACT-002")
async def test_action_receipt_persistence_is_append_only_and_roundtrips() -> None:
    database = await _make_database()
    repo = SqlActionReceiptRepository(database)

    receipt = ActionReceipt(
        action_receipt_id="receipt:1",
        action_key="action-key-1",
        action_fingerprint="fp-1",
        tool_intent_ref="tool-intent:1",
        capability_ref="cap:create_order",
        executor_ref="executor:1",
        status="succeeded",
        attempt=1,
        started_at=support.now(),
        finished_at=support.now(),
        external_reference="ref:ext-1",
        result_digest="digest-1",
    )
    async with database.async_session_context():
        await repo.create(receipt)

    # 重复的 receipt_id 会被拒绝（仅追加）。
    with pytest.raises(ValueError, match="already exists"):
        async with database.async_session_context():
            await repo.create(receipt)

    # 规范对象往返时保留全部字段。
    async with database.async_session_context():
        reloaded = await repo.get("receipt:1")
    assert reloaded is not None
    assert reloaded.status == "succeeded"
    assert reloaded.external_reference == "ref:ext-1"
    assert reloaded.result_digest == "digest-1"

    async with database.async_session_context():
        keyed = await repo.list_for_key("action-key-1")
    assert [r.action_receipt_id for r in keyed] == ["receipt:1"]
    await database.dispose()


@requires_database
@pytest.mark.test_id("RUN-008")
async def test_turn_record_persistence_preserves_run_sequence() -> None:
    database = await _make_database()
    repo = SqlTurnRecordRepository(database)

    turns = [
        TurnRecord(
            meta=support_meta("TurnRecord", f"turn:{i}", "run:9"),
            turn_id=f"turn:{i}",
            run_id="run:9",
            turn_no=i,
            context_manifest_ref=f"context:{i}",
            prompt_contract_ref="prompt:1",
            output_schema_ref="schema://structured-decision/1.0.0",
            model_route_ref="route:1",
            model_invocation_ref=f"mi:{i}",
            outcome="tool_intents" if i < 3 else "final_response",
            stop_reason="stop",
            usage_tokens=10 * i,
            created_at=support.now(),
        )
        for i in (1, 2, 3)
    ]
    for turn in turns:
        async with database.async_session_context():
            await repo.add(turn)

    # 重新加载时保持每个 run 的权威序号（RUN-008）。
    async with database.async_session_context():
        reloaded = await repo.list_for_run("run:9")
    assert [t.turn_no for t in reloaded] == [1, 2, 3]
    assert [t.outcome for t in reloaded] == ["tool_intents", "tool_intents", "final_response"]
    assert reloaded[0].meta.object_id == "turn:1"

    # 重复的 turn_id 会被拒绝（仅追加）。
    with pytest.raises(ValueError, match="already exists"):
        async with database.async_session_context():
            await repo.add(turns[0])
    await database.dispose()


@requires_database
@pytest.mark.test_id("CTX-001")
async def test_memory_record_persistence_serves_governed_recall() -> None:
    database = await _make_database()
    repo = SqlMemoryRecordRepository(database)

    record = MemoryRecord(
        meta=support_meta("MemoryRecord", "memory:1", "principal:1"),
        record_id="memory:1",
        subject_ref="principal:1",
        scope="user",
        source_refs=("evidence:2",),
        statement="workflow preference",
        confidence=0.8,
        consent_ref=None,
        sensitivity="internal",
        valid_from=support.now(),
    )
    async with database.async_session_context():
        await repo.create(record)

    async with database.async_session_context():
        reloaded = await repo.get("memory:1")
    assert reloaded is not None
    assert reloaded.statement == "workflow preference"
    assert reloaded.sensitivity == "internal"
    assert reloaded.status == "active"

    # 按主体进行受治理的召回，可选按状态过滤。
    async with database.async_session_context():
        all_records = await repo.list_for_subject("principal:1")
        active = await repo.list_for_subject("principal:1", status="active")
        deleted = await repo.list_for_subject("principal:1", status="deleted")
    assert [r.record_id for r in all_records] == ["memory:1"]
    assert [r.record_id for r in active] == ["memory:1"]
    assert deleted == []
    await database.dispose()


def support_meta(contract_name: str, object_id: str, run_or_subject: str):
    from ueaf.common.meta import ContractMeta

    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=support.TENANT,
        created_at=support.now(),
        producer="ueaf-test",
        producer_version="0.1.0",
        run_id=run_or_subject,
        trace_id="trace:1",
    )
