"""SQL persistence layer tests (implementation spec 03).

Validates DB-level CAS/fencing, transactional outbox atomicity and full run
lifecycle over SQLAlchemy (SQLite in-memory) — the same repository code runs
against PostgreSQL 16 in production.
"""

from __future__ import annotations

import pytest

from tests import support
from ueaf.infrastructure.db.database import memory_database
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


def _sql_coordinator():
    database = memory_database()
    coordinator = RunCoordinator.sql(
        database, support.admission_controller(), clock=Clock(support.now())
    )
    return database, coordinator


def _create_run(coordinator: RunCoordinator):
    return coordinator.create_run(
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


def _admit(coordinator: RunCoordinator):
    run = _create_run(coordinator)
    admitting = coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    return coordinator.apply_admission(admitting.run_id, result)


@pytest.mark.test_id("RUN-001")
def test_sql_coordinator_full_lifecycle() -> None:
    database, coordinator = _sql_coordinator()
    running = _admit(coordinator)
    assert running.phase == "running"

    terminal = coordinator.commit_terminal(
        running.run_id,
        disposition="completed",
        reason_codes=("done",),
        result_ref="result:1",
    )
    assert terminal.phase == "terminal"
    assert terminal.completion_disposition == "completed"

    # Authority state is durable: reload from the DB in a fresh session.
    repo = SqlRunRecordRepository(database)
    with database.session_context():
        reloaded = repo.require(terminal.run_id)
    assert reloaded.meta.object_id == terminal.run_id
    assert reloaded.meta.contract_name == "RunRecord"
    assert reloaded.phase == "terminal"


@pytest.mark.test_id("RUN-008")
def test_db_level_cas_rejects_stale_revision() -> None:
    database, coordinator = _sql_coordinator()
    run = _create_run(coordinator)
    # Advance authority state so the persisted revision moves past the snapshot.
    coordinator.begin_admission(run.run_id)
    repo = SqlRunRecordRepository(database)
    with database.session_context():
        current = repo.require(run.run_id)
    assert current.revision > run.revision

    # An update carrying an out-of-date expected_revision must be rejected by CAS.
    with pytest.raises(RevisionConflict):
        with database.session_context():
            repo.update(current, expected_revision=run.revision)


@pytest.mark.test_id("RUN-003")
def test_db_level_fencing_rejects_stale_token() -> None:
    database, coordinator = _sql_coordinator()
    running = _admit(coordinator)
    leased = coordinator.acquire_lease(running.run_id, holder_id="worker-a")
    assert leased.lease.fencing_token == 1

    # A stale fencing token (< current persisted token) must be rejected.
    with pytest.raises(ValueError, match="stale_fencing"):
        coordinator.heartbeat(
            leased.run_id,
            lease_id=leased.lease.lease_id,
            fencing_token=0,
        )

    # Direct repository-level fencing check too.
    repo = SqlRunRecordRepository(database)
    with database.session_context():
        current = repo.require(running.run_id)
        assert current.lease is not None
    with pytest.raises(StaleFencing):
        with database.session_context():
            repo.update(current, expected_revision=current.revision, fencing_token=0)


@pytest.mark.test_id("CON-013")
def test_outbox_and_state_are_atomic_in_one_transaction() -> None:
    database, coordinator = _sql_coordinator()
    run = _create_run(coordinator)
    repo = SqlRunRecordRepository(database)
    outbox = SqlOutboxStore(database)

    with database.session_context():
        pre = repo.require(run.run_id)
        # Capture an existing outbox event_id to force a duplicate on the next tx.
        existing = outbox.unpublished()[0].event_id

    with database.session_context() as session:
        from dataclasses import replace

        changed = replace(pre, phase="admitting", revision=pre.revision + 1)
        repo.update(changed, expected_revision=pre.revision)
        # A duplicate outbox insert fails the whole transaction...
        outbox.append(
            _duplicate_entry(existing, tenant=run.meta.tenant_id)
        )
        # ...and the session must roll back (never committed).
        try:
            session.commit()
        except Exception:
            session.rollback()

    with database.session_context():
        after = repo.require(run.run_id)
    # The phase change was NOT committed because outbox insert failed atomically.
    assert after.phase == "queued"
    assert after.revision == pre.revision


@pytest.mark.test_id("RUN-004")
def test_sql_idempotent_terminal_replay() -> None:
    database, coordinator = _sql_coordinator()
    running = _admit(coordinator)
    first = coordinator.commit_terminal(
        running.run_id, disposition="cancelled", reason_codes=("op_cancel",)
    )
    replay = coordinator.commit_terminal(
        running.run_id, disposition="cancelled", reason_codes=("op_cancel",)
    )
    assert replay.revision == first.revision
    with pytest.raises(StateMachineError, match="terminal_conflict"):
        coordinator.commit_terminal(
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
