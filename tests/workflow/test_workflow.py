"""Workflow module tests (functional module 06).

Covers the Workflow slices missing from the reference implementation:
WorkflowRun/NodeRun/NodeAttempt objects, the Workflow Registry, and node
orchestration (dependencies, scheduling, retry attempts). Mapped to registered
core IDs: ADP-003 (definition registry) and CON-007 (core capability ports /
handoff).
"""

from __future__ import annotations

import pytest

from tests import support
from ueaf.common.meta import ContractMeta
from ueaf.ports import HandoffEnvelope, HandoffProgress, PortResult, Success
from ueaf.workflow.objects import (
    NodeRun,
    WorkflowDefinition,
    WorkflowRun,
)
from ueaf.workflow.orchestrator import WorkflowOrchestrator
from ueaf.workflow.registry import WorkflowCompatibility, WorkflowRegistry


def _meta(contract: str, object_id: str) -> ContractMeta:
    return ContractMeta(
        contract_name=contract,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=support.TENANT,
        created_at=support.now(),
        producer="ueaf-test",
        producer_version="0.1.0",
    )


def _definition(*, version: str = "1.0.0") -> WorkflowDefinition:
    return WorkflowDefinition(
        meta=_meta("WorkflowDefinition", "workflow:1"),
        workflow_id="workflow:1",
        workflow_version=version,
        owner="team-a",
        schema_ref="schema://workflow/1.0.0",
        nodes=("agent:research", "action:orders", "wait:approval"),
        edges=(("agent:research", "action:orders"), ("action:orders", "wait:approval")),
    )


@pytest.mark.test_id("ADP-003")
def test_workflow_registry_binds_immutable_versions() -> None:
    registry = WorkflowRegistry()
    definition = _definition()
    registry.register(definition)
    assert registry.require("workflow:1", "1.0.0").workflow_id == "workflow:1"
    # A newer version is registered separately; the in-flight v1 stays bound.
    registry.register(_definition(version="2.0.0"))
    assert registry.get("workflow:1", "1.0.0") is definition
    # Duplicate (id, version) is rejected.
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_definition(version="1.0.0"))
    # Compatibility: same workflow + schema + owner is compatible.
    compat = registry.check_compatibility(definition, _definition(version="2.0.0"))
    assert isinstance(compat, WorkflowCompatibility)
    assert compat.compatible


@pytest.mark.test_id("CON-007")
def test_workflow_orchestrator_schedules_ready_nodes_by_dependency() -> None:
    orchestrator = WorkflowOrchestrator(object())
    definition = _definition()
    run = orchestrator.instantiate(definition, workflow_run_id="wfr:1", budget_slice_ref="budget:1")
    assert isinstance(run, WorkflowRun)
    assert len(run.node_runs) == 3

    # Only the root node (no dependencies) is ready initially.
    first = orchestrator.schedule_ready(run)
    assert first.node_run_ids == ("wfr:1:agent:research",)
    assert [nr.status for nr in run.node_runs] == ["running", "pending", "pending"]

    # Completing the root unblocks the next node.
    orchestrator.complete_node(run, "agent:research")
    second = orchestrator.schedule_ready(run)
    assert second.node_run_ids == ("wfr:1:action:orders",)

    # NodeRun kinds are preserved from the node id prefix.
    kinds = {nr.node_id: nr.kind for nr in run.node_runs}
    assert kinds == {
        "agent:research": "agent",
        "action:orders": "action",
        "wait:approval": "wait",
    }


@pytest.mark.test_id("CON-007")
def test_workflow_run_completion_and_failure() -> None:
    orchestrator = WorkflowOrchestrator(object(), max_attempts=2)
    run = orchestrator.instantiate(_definition(), workflow_run_id="wfr:2")

    # Node attempts are recorded and preserved.
    orchestrator.record_attempt("wfr:2:action:orders", attempt=1, status="failed", result_ref="r:1")
    orchestrator.record_attempt(
        "wfr:2:action:orders", attempt=2, status="succeeded", result_ref="r:2"
    )
    attempts = orchestrator.attempts_for("wfr:2:action:orders")
    assert [a.attempt for a in attempts] == [1, 2]

    # Drive the run to completion.
    orchestrator.schedule_ready(run)
    orchestrator.complete_node(run, "agent:research")
    orchestrator.schedule_ready(run)
    orchestrator.complete_node(run, "action:orders")
    orchestrator.schedule_ready(run)
    assert orchestrator.complete_node(run, "wait:approval") is True
    assert run.status == "completed"

    # A failed node fails the run.
    run2 = orchestrator.instantiate(_definition(), workflow_run_id="wfr:3")
    orchestrator.schedule_ready(run2)
    assert orchestrator.fail_node(run2, "agent:research") is False
    assert run2.status == "failed"


@pytest.mark.test_id("CON-007")
def test_workflow_handoff_goes_through_core_port() -> None:
    class _FakeHandoff:
        def submit(self, envelope: HandoffEnvelope) -> PortResult[HandoffProgress]:
            return Success(
                HandoffProgress(
                    handoff_id=envelope.handoff_id,
                    disposition="accepted",
                    target_run_ref="run:2",
                    result_ref=None,
                )
            )

    from ueaf.workflow.coordinator import WorkflowCoordinator

    coordinator = WorkflowCoordinator(_FakeHandoff())
    envelope = HandoffEnvelope(
        handoff_id="handoff:1",
        tenant_id=support.TENANT,
        source_run_id="run:1",
        target_ref="agent:2",
        subgoal_ref="subgoal:1",
        budget_slice_ref="budget-slice:1",
        principal_context_ref="principal:1",
        expires_at=support.now(),
    )
    import asyncio

    result = asyncio.run(coordinator.submit(envelope))
    assert isinstance(result, Success)
    assert coordinator.status("handoff:1").disposition == "accepted"


@pytest.mark.test_id("CON-007")
def test_node_run_object_contract() -> None:
    node = NodeRun(
        meta=_meta("NodeRun", "n:1"),
        node_run_id="n:1",
        workflow_run_id="wfr:1",
        node_id="action:x",
        kind="action",
    )
    assert node.status == "pending"
    assert node.attempt == 0
    # Invalid kind is rejected.
    with pytest.raises(ValueError, match="kind"):
        NodeRun(
            meta=_meta("NodeRun", "n:2"),
            node_run_id="n:2",
            workflow_run_id="wfr:1",
            node_id="bad",
            kind="invalid",  # type: ignore[arg-type]
        )
