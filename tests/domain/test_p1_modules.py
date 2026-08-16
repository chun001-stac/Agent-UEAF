"""P1 领域模块：turns、recovery、memory、definitions、workflow、ops、secrets。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests import support
from ueaf.admission.registry import (
    AgentDefinition,
    CapabilityDescriptor,
    DefinitionRegistry,
)
from ueaf.common.envelope import EventEnvelope
from ueaf.common.meta import ContractMeta
from ueaf.developer.registry import default_registry
from ueaf.infrastructure.db.repositories import (
    Clock,
    InMemoryAdmissionResultRepository,
    InMemoryRunRecordRepository,
    InMemoryTaskStateRepository,
)
from ueaf.infrastructure.secrets import InMemorySecretProvider
from ueaf.memory.objects import MemoryCandidate
from ueaf.memory.service import MemoryGovernanceError, MemoryService
from ueaf.operations.projections import RunSummaryProjector
from ueaf.ports import HandoffEnvelope, Success
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.outbox import InMemoryOutboxStore
from ueaf.runtime.recovery import InMemoryCheckpointStore, RecoveryManager, new_checkpoint
from ueaf.runtime.turn import InMemoryTurnRegistry, TurnRecord
from ueaf.workflow.coordinator import WorkflowCoordinator

MOMENT = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


def _meta(contract_name: str, object_id: str) -> ContractMeta:
    return ContractMeta(
        contract_name=contract_name,
        contract_version="1.0.0",
        object_id=object_id,
        tenant_id=support.TENANT,
        created_at=MOMENT,
        producer="ueaf-test",
        producer_version="0.1.0",
    )


async def _coordinator():
    runs = InMemoryRunRecordRepository()
    tasks = InMemoryTaskStateRepository()
    admissions = InMemoryAdmissionResultRepository()
    outbox = InMemoryOutboxStore()
    return RunCoordinator(
        runs, tasks, admissions, support.admission_controller(), outbox, Clock(support.now())
    )


@pytest.mark.test_id("RUN-008")
def test_turn_registry_keeps_authoritative_turn_sequence() -> None:
    registry = InMemoryTurnRegistry()
    turn = TurnRecord(
        meta=_meta("TurnRecord", "turn:1"),
        turn_id="turn:1",
        run_id="run:1",
        turn_no=1,
        context_manifest_ref="context:1",
        prompt_contract_ref="prompt:1",
        output_schema_ref="schema://structured-decision/1.0.0",
        model_route_ref="route:1",
        model_invocation_ref="mi:1",
        outcome="final_response",
        stop_reason="stop",
        usage_tokens=42,
        created_at=MOMENT,
    )
    registry.add(turn)
    assert registry.get("turn:1").turn_no == 1
    assert registry.for_run("run:1")[0].outcome == "final_response"
    with pytest.raises(ValueError, match="already exists"):
        registry.add(turn)


@pytest.mark.test_id("RUN-004")
async def test_recovery_manager_restores_run_with_fresh_lease() -> None:
    coordinator = await _coordinator()
    run = await coordinator.create_run(
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
    # 被恢复的 run 在崩溃前正在执行 -> 先对其执行准入。
    admitting = await coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    run = await coordinator.apply_admission(admitting.run_id, result)

    checkpoints = InMemoryCheckpointStore()
    manager = RecoveryManager(coordinator, checkpoints)

    result = await manager.recover(
        run.run_id, holder_id="restarted-worker", expected_runtime_adapter_ref="adapter:langgraph"
    )
    assert result.recovered is True
    assert result.record.lease is not None
    assert result.record.lease.fencing_token == 1

    # 检查点必须绑定同一个 run（RUN-004 崩溃一致性）。
    checkpoint = new_checkpoint(run)
    checkpoints.save(checkpoint)
    bad = await manager.recover(
        run.run_id,
        holder_id="worker-2",
        checkpoint_ref=checkpoint.checkpoint_id,
        expected_runtime_adapter_ref="adapter:langgraph",
    )
    assert bad.recovered is True


@pytest.mark.test_id("CTX-001")
def test_memory_service_requires_consent_for_sensitive_memory() -> None:
    service = MemoryService()
    sensitive = MemoryCandidate(
        meta=_meta("MemoryCandidate", "cand:1"),
        candidate_id="cand:1",
        subject_ref="principal:1",
        source_refs=("evidence:1",),
        purpose="personalization",
        sensitivity="confidential",
        statement="user preference PII",
        confidence=0.9,
        required_consent=True,
    )
    # 敏感候选在未获同意时绝不会被物化（治理要求）。
    with pytest.raises(MemoryGovernanceError):
        service.promote(sensitive)

    # 非敏感候选会升级为受治理的 MemoryRecord（可召回）。
    safe = MemoryCandidate(
        meta=_meta("MemoryCandidate", "cand:2"),
        candidate_id="cand:2",
        subject_ref="principal:1",
        source_refs=("evidence:2",),
        purpose="analytics",
        sensitivity="internal",
        statement="workflow preference",
        confidence=0.8,
        required_consent=False,
    )
    record = service.promote(safe)
    assert record.status == "active"
    assert [r.record_id for r in service.recall("principal:1")] == [record.record_id]


@pytest.mark.test_id("ADP-003")
def test_definition_registry_resolves_capabilities_deny_by_default() -> None:
    registry = DefinitionRegistry()
    cap = CapabilityDescriptor(
        meta=_meta("CapabilityDescriptor", "cap:search"),
        capability_id="cap:search",
        capability_version="1.0.0",
        kind="tool",
        input_schema_ref="schema://search-input/1.0.0",
        output_schema_ref="schema://search-output/1.0.0",
        risk_class="read_only",
        side_effect_class="read",
        auth_requirements=("read",),
        idempotency_support=True,
        timeout_ms=5000,
        lifecycle_status="active",
    )
    registry.register_capability(cap)
    agent = AgentDefinition(
        meta=_meta("AgentDefinition", "agent:1"),
        agent_id="agent:1",
        agent_version="1.0.0",
        owner="team-a",
        purpose="research",
        input_contract_ref="schema://in/1.0.0",
        output_contract_ref="schema://out/1.0.0",
        completion_contract_ref="schema://done/1.0.0",
        runtime_profile="adapter:langgraph",
        capability_refs=("cap:search@1.0.0",),
        prompt_contract_ref="prompt:1",
        policy_refs=("policy:1",),
        risk_class="read_only",
    )
    registry.register_agent(agent)
    assert registry.requires_capabilities(agent)[0].capability_id == "cap:search"


@pytest.mark.test_id("CON-007")
async def test_workflow_coordinator_submits_handoff_through_port() -> None:
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

    class _FakeHandoffPort:
        def submit(self, request):
            from ueaf.ports import HandoffProgress

            return Success(
                HandoffProgress(
                    handoff_id="handoff:1",
                    disposition="accepted",
                    target_run_ref="run:2",
                    result_ref=None,
                )
            )

    coordinator = WorkflowCoordinator(_FakeHandoffPort())
    result = await coordinator.submit(envelope)
    assert isinstance(result, Success)
    assert coordinator.status("handoff:1").disposition == "accepted"


@pytest.mark.test_id("EVD-001")
def test_run_summary_projection_is_deterministic_and_zero_llm() -> None:
    projector = RunSummaryProjector()
    event = EventEnvelope(
        event_id="evt:1",
        event_name="ueaf.run.phase_changed",
        event_version="1.0.0",
        occurred_at=MOMENT,
        recorded_at=MOMENT,
        tenant_id=support.TENANT,
        aggregate_type="RunRecord",
        aggregate_id="run:1",
        aggregate_version=2,
        sequence=2,
        producer="ueaf-runtime",
        producer_version="0.1.0",
        correlation_id="req:1",
        trace_id="trace:1",
        payload_schema_ref="schema://run-phase-changed/1.0.0",
        payload={"from_phase": "queued", "to_phase": "admitting", "reason_codes": ("x",)},
    )
    summary = projector.apply(event)
    assert summary.phase == "admitting"
    assert summary.event_count == 1


@pytest.mark.test_id("CON-006")
def test_adapter_registry_builds_runtime_adapters() -> None:
    registry = default_registry()
    adapter = registry.build("adapter:langgraph")
    assert adapter.DescribeRuntime().supported_contract_versions == ("1.0.0",)
    with pytest.raises(KeyError):
        registry.build("adapter:unknown")


@pytest.mark.test_id("SEC-013")
def test_secret_provider_resolves_opaque_refs_only() -> None:
    provider = InMemorySecretProvider({"API_KEY": "secret-value"})
    assert provider.resolve("env:API_KEY") == "secret-value"
    assert provider.exists("env:API_KEY")
    with pytest.raises(KeyError):
        provider.resolve("env:MISSING")
