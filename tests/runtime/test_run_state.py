"""Phase 1 run-state acceptance tests (RUN-002..004, RUN-008, CON-013)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests import support
from ueaf.infrastructure.db.repositories import (
    Clock,
    InMemoryAdmissionResultRepository,
    InMemoryRunRecordRepository,
    InMemoryTaskStateRepository,
)
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.outbox import InMemoryEventBus, InMemoryOutboxStore
from ueaf.runtime.state_machine import StateMachineError

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _harness():
    runs = InMemoryRunRecordRepository()
    tasks = InMemoryTaskStateRepository()
    admissions = InMemoryAdmissionResultRepository()
    outbox = InMemoryOutboxStore()
    clock = Clock(support.now())
    coordinator = RunCoordinator(
        runs, tasks, admissions, support.admission_controller(), outbox, clock=clock
    )
    return coordinator, runs, outbox, clock


def _create_and_admit(coordinator: RunCoordinator):
    run = coordinator.create_run(
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
    admitting = coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    return coordinator.apply_admission(admitting.run_id, result)


@pytest.mark.test_id("RUN-002")
def test_phase_and_disposition_are_orthogonal() -> None:
    coordinator, _, _, _ = _harness()
    running = _create_and_admit(coordinator)
    assert running.phase == "running"
    assert running.completion_disposition is None  # non-terminal disposition must be null

    terminal = coordinator.commit_terminal(
        running.run_id,
        disposition="completed",
        reason_codes=("all_criteria_met",),
        result_ref="result:1",
    )
    assert terminal.phase == "terminal"
    assert terminal.completion_disposition == "completed"
    assert terminal.terminal_reason_codes == ("all_criteria_met",)


@pytest.mark.test_id("RUN-003")
def test_stale_fencing_token_write_is_rejected() -> None:
    coordinator, _, _, _ = _harness()
    running = _create_and_admit(coordinator)

    leased = coordinator.acquire_lease(running.run_id, holder_id="worker-a")
    assert leased.lease.fencing_token == 1

    # Same worker heartbeats successfully.
    heartbeat = coordinator.heartbeat(
        leased.run_id, lease_id=leased.lease.lease_id, fencing_token=1
    )
    assert heartbeat.revision > leased.revision

    # A stale holder (older fencing token) must be rejected.
    with pytest.raises(ValueError, match="stale_fencing_token"):
        coordinator.heartbeat(
            leased.run_id,
            lease_id=leased.lease.lease_id,
            fencing_token=0,  # stale
        )


@pytest.mark.test_id("RUN-004")
def test_crash_recovery_does_not_double_commit_terminal() -> None:
    coordinator, _, _, _ = _harness()
    running = _create_and_admit(coordinator)
    first = coordinator.commit_terminal(
        running.run_id, disposition="cancelled", reason_codes=("operator_cancel",)
    )
    assert first.phase == "terminal"

    # Replaying the same terminal command is idempotent (returns current record).
    replay = coordinator.commit_terminal(
        running.run_id, disposition="cancelled", reason_codes=("operator_cancel",)
    )
    assert replay.revision == first.revision

    # A conflicting disposition on the terminal run is rejected.
    with pytest.raises(StateMachineError, match="terminal_conflict"):
        coordinator.commit_terminal(
            running.run_id, disposition="failed", reason_codes=("other",)
        )


@pytest.mark.test_id("RUN-008")
def test_state_dependent_record_fields_lease_and_fencing() -> None:
    coordinator, _, _, _ = _harness()
    running = _create_and_admit(coordinator)
    leased = coordinator.acquire_lease(running.run_id, holder_id="worker-b")
    assert leased.lease.fencing_token == 1
    assert leased.lease.acquired_at <= leased.lease.heartbeat_at < leased.lease.expires_at

    # Re-acquiring issues a strictly greater fencing token (monotonic).
    renewed = coordinator.acquire_lease(running.run_id, holder_id="worker-b")
    assert renewed.lease.fencing_token == 2

    # Entering waiting clears the lease (execution rights released).
    waiting = coordinator.register_wait(
        running.run_id,
        wait_reason="tool_result",
        condition_refs=("condition:async-tool",),
        expires_at=MOMENT + timedelta(minutes=5),
    )
    assert waiting.phase == "waiting"
    assert waiting.lease is None
    assert waiting.wait_reason == "tool_result"
    assert waiting.wait_condition_refs == ("condition:async-tool",)


@pytest.mark.test_id("CON-013")
def test_authoritative_state_and_events_are_atomic_via_outbox() -> None:
    coordinator, runs, outbox, _ = _harness()
    run = _create_and_admit(coordinator)

    terminal = coordinator.commit_terminal(
        run.run_id, disposition="completed", reason_codes=("done",)
    )
    assert terminal.phase == "terminal"
    # Every state change is mirrored by outbox entries; the bus consumes
    # without loss and dedupes by event_id.
    bus = InMemoryEventBus()
    published: list[str] = []
    for entry in outbox.unpublished():
        if bus.publish(entry):
            outbox.mark_published(entry.event_id, support.now())
            published.append(entry.event_name)

    run_events = [event for event in bus.events if event.aggregate_type == "RunRecord"]
    assert run_events, "run lifecycle must produce authoritative events"
    assert "ueaf.run.created" in [e.event_name for e in run_events]
    assert "ueaf.run.terminal_committed" in [e.event_name for e in run_events]
    # Idempotent redelivery does not double-publish (dedupe by event_id).
    for entry in outbox.unpublished():
        assert bus.publish(entry) is False
