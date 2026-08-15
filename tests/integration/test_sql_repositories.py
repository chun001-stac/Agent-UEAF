"""SQL persistence layer tests (implementation spec 03).

Validates DB-level CAS/fencing, transactional outbox atomicity and full run
lifecycle over the async SQLAlchemy repositories. Runs against async SQLite
(local, aiosqlite) or a real PostgreSQL when ``UEAF_DATABASE_URL`` is set (CI).
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from tests import support
from ueaf.infrastructure.db.database import Database, memory_database
from ueaf.infrastructure.db.repositories import (
    Clock,
    RevisionConflict,
    StaleFencing,
)
from ueaf.infrastructure.db.repositories_sql import (
    SqlOutboxStore,
    SqlRunRecordRepository,
)
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.state_machine import StateMachineError


def _async_sqlite_available() -> bool:
    try:
        import aiosqlite  # noqa: F401
    except ImportError:
        return False
    return True


async def _make_database() -> Database:
    url = os.environ.get("UEAF_DATABASE_URL")
    if url:
        return Database(url)
    return await memory_database()  # sqlite+aiosqlite


requires_database = pytest.mark.skipif(
    not _async_sqlite_available() and not os.environ.get("UEAF_DATABASE_URL"),
    reason="requires aiosqlite (local) or UEAF_DATABASE_URL (CI Postgres)",
)


@requires_database
async def _sql_coordinator():
    database = await _make_database()
    await support.clean_authoritative_tables(database)
    coordinator = RunCoordinator.sql(
        database, support.admission_controller(), clock=Clock(support.now())
    )
    return database, coordinator


async def _create_run(coordinator: RunCoordinator):
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


async def _admit(coordinator: RunCoordinator):
    run = await _create_run(coordinator)
    admitting = await coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    return await coordinator.apply_admission(admitting.run_id, result)


@pytest.mark.test_id("RUN-001")
async def test_sql_coordinator_full_lifecycle() -> None:
    database, coordinator = await _sql_coordinator()
    running = await _admit(coordinator)
    assert running.phase == "running"

    terminal = await coordinator.commit_terminal(
        running.run_id,
        disposition="completed",
        reason_codes=("done",),
        result_ref="result:1",
    )
    assert terminal.phase == "terminal"
    assert terminal.completion_disposition == "completed"

    # Authority state is durable: reload from the DB in a fresh session.
    repo = SqlRunRecordRepository(database)
    async with database.async_session_context():
        reloaded = await repo.require(terminal.run_id)
    assert reloaded.meta.object_id == terminal.run_id
    assert reloaded.meta.contract_name == "RunRecord"
    assert reloaded.phase == "terminal"


@pytest.mark.test_id("RUN-008")
async def test_db_level_cas_rejects_stale_revision() -> None:
    database, coordinator = await _sql_coordinator()
    run = await _create_run(coordinator)
    # Advance authority state so the persisted revision moves past the snapshot.
    await coordinator.begin_admission(run.run_id)
    repo = SqlRunRecordRepository(database)
    async with database.async_session_context():
        current = await repo.require(run.run_id)
    assert current.revision > run.revision

    # An update carrying an out-of-date expected_revision must be rejected by CAS.
    with pytest.raises(RevisionConflict):
        async with database.async_session_context():
            await repo.update(current, expected_revision=run.revision)


@pytest.mark.test_id("RUN-003")
async def test_db_level_fencing_rejects_stale_token() -> None:
    database, coordinator = await _sql_coordinator()
    running = await _admit(coordinator)
    leased = await coordinator.acquire_lease(running.run_id, holder_id="worker-a")
    assert leased.lease.fencing_token == 1

    # A stale fencing token (< current persisted token) must be rejected.
    with pytest.raises(ValueError, match="stale_fencing"):
        await coordinator.heartbeat(
            leased.run_id,
            lease_id=leased.lease.lease_id,
            fencing_token=0,
        )

    # Direct repository-level fencing check too.
    repo = SqlRunRecordRepository(database)
    async with database.async_session_context():
        current = await repo.require(running.run_id)
        assert current.lease is not None
    with pytest.raises(StaleFencing):
        async with database.async_session_context():
            await repo.update(
                current, expected_revision=current.revision, fencing_token=0
            )


@pytest.mark.test_id("CON-013")
async def test_outbox_and_state_are_atomic_in_one_transaction() -> None:
    database, coordinator = await _sql_coordinator()
    run = await _create_run(coordinator)
    repo = SqlRunRecordRepository(database)
    outbox = SqlOutboxStore(database)

    async with database.async_session_context():
        pre = await repo.require(run.run_id)
        # Capture an existing outbox event_id to force a duplicate on the next tx.
        existing = (await outbox.unpublished())[0].event_id

    # A duplicate outbox insert fails the whole transaction; the async session
    # context rolls back the run phase change atomically (CON-013).
    with pytest.raises(ValueError, match="duplicate outbox"):
        async with database.async_session_context():
            changed = replace(pre, phase="admitting", revision=pre.revision + 1)
            await repo.update(changed, expected_revision=pre.revision)
            await outbox.append(_duplicate_entry(existing, tenant=run.meta.tenant_id))

    async with database.async_session_context():
        after = await repo.require(run.run_id)
    # The phase change was NOT committed because outbox insert failed atomically.
    assert after.phase == "queued"
    assert after.revision == pre.revision


@pytest.mark.test_id("RUN-004")
async def test_sql_idempotent_terminal_replay() -> None:
    database, coordinator = await _sql_coordinator()
    running = await _admit(coordinator)
    first = await coordinator.commit_terminal(
        running.run_id, disposition="cancelled", reason_codes=("op_cancel",)
    )
    replay = await coordinator.commit_terminal(
        running.run_id, disposition="cancelled", reason_codes=("op_cancel",)
    )
    assert replay.revision == first.revision
    with pytest.raises(StateMachineError, match="terminal_conflict"):
        await coordinator.commit_terminal(
            running.run_id, disposition="failed", reason_codes=("other",)
        )


def _duplicate_entry(event_id: str, *, tenant: str):
    from datetime import UTC, datetime

    from ueaf.common.identifiers import new_object_id
    from ueaf.runtime.outbox import OutboxEntry

    return OutboxEntry(
        outbox_id=new_object_id("outbox"),
        event_id=event_id,
        event_name="ueaf.run.created",
        event_version="1.0.0",
        tenant_id=tenant,
        aggregate_type="RunRecord",
        aggregate_id="run:dup",
        aggregate_version=1,
        sequence=1,
        correlation_id="req:1",
        trace_id="trace:1",
        payload_schema_ref="schema://run-created/1.0.0",
        payload={"run_id": "run:dup"},
        created_at=datetime.now(UTC),
    )
