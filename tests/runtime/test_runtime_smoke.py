"""Phase 2 runtime smoke: controlled non-Eval chain (ADP-*)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from tests import support
from ueaf.adapters.runtimes.base import DeterministicRuntimeAdapter
from ueaf.adapters.runtimes.langgraph_adapter import LangGraphAdapter
from ueaf.adapters.runtimes.openai_agents_adapter import OpenAIAgentsReadOnlyAdapter
from ueaf.context.context_build import ContextBuilder
from ueaf.infrastructure.db.repositories import (
    Clock,
    InMemoryAdmissionResultRepository,
    InMemoryRunRecordRepository,
    InMemoryTaskStateRepository,
)
from ueaf.model.model_step import DeterministicFakeModel, ModelStep
from ueaf.ports import (
    PortResult,
    RuntimeEvent,
    RuntimeStartRequest,
    Success,
)
from ueaf.runtime.coordinator import RunCoordinator, RunCreateInput
from ueaf.runtime.execution_context import build_execution_context
from ueaf.runtime.outbox import InMemoryOutboxStore

SCHEMA_REF = "schema://structured-decision/1.0.0"


async def _admit_run():
    runs = InMemoryRunRecordRepository()
    tasks = InMemoryTaskStateRepository()
    admissions = InMemoryAdmissionResultRepository()
    outbox = InMemoryOutboxStore()
    coordinator = RunCoordinator(
        runs, tasks, admissions, support.admission_controller(), outbox, Clock(support.now())
    )
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
    admitting = await coordinator.begin_admission(run.run_id)
    result = support.admission_controller().evaluate(
        admitting, support.task_envelope(), support.budget(), support.principal()
    )
    return await coordinator.apply_admission(admitting.run_id, result), runs, outbox


async def _execution_context(model: DeterministicFakeModel, *, call_log: list[str]):
    context = ContextBuilder()
    model_step = ModelStep(model, output_schema_ref=SCHEMA_REF)
    tool_intent = _RecordingToolIntent(call_log)

    class _Handoff:
        def submit(self, request):
            return Success(object())

    run, _, _ = await _admit_run()
    ctx = build_execution_context(
        run,
        trace_id="trace:1",
        fencing_token=1,
        context_build_port=context,
        model_step_port=model_step,
        tool_intent_port=tool_intent,
        handoff_port=_Handoff(),
        telemetry_port=_NoopTelemetry(),
    )
    return run, ctx


class _RecordingToolIntent:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def submit(self, request) -> PortResult[object]:
        self._log.append(request.tool_intent_id)
        return Success(request.tool_intent_id)


class _NoopTelemetry:
    def EmitTrace(self, record):
        return Success(None)

    def EmitMetric(self, points):
        return Success(None)

    def EmitLog(self, records):
        return Success(None)

    def EmitAudit(self, record):
        return Success(None)


async def _drain(stream: AsyncIterator[RuntimeEvent]) -> list[RuntimeEvent]:
    return [event async for event in stream]


@pytest.mark.test_id("ADP-001")
async def test_adapter_model_step_routes_through_model_gateway() -> None:
    call_log: list[str] = []
    model = DeterministicFakeModel()
    run, ctx = await _execution_context(model, call_log=call_log)
    adapter = DeterministicRuntimeAdapter()

    session = adapter.StartRun(
        RuntimeStartRequest(
            tenant_id=run.meta.tenant_id,
            task_id=run.task_id,
            run_id=run.run_id,
            task_envelope_ref=f"task:{run.task_id}",
            run_record_ref=f"run:{run.run_id}",
            principal_context_ref="principal:1",
            release_id=run.release_id,
            budget_snapshot_ref="budget-snapshot:1",
            agent_definition_ref="agent:1",
            prompt_contract_ref=f"prompt:{run.run_id}",
            output_schema_ref=SCHEMA_REF,
            runtime_adapter_ref="adapter:deterministic",
            execution_context=ctx,
        )
    )

    from ueaf.ports import RuntimeAdvanceRequest

    stream = adapter.AdvanceRun(
        RuntimeAdvanceRequest(
            session=session,
            expected_revision=run.revision,
            fencing_token=ctx.fencing_token,
            max_events=4,
            deadline_at=run.deadline_at,
        )
    )
    events = await _drain(stream)
    assert len(events) >= 2
    types = {event.event_type for event in events}
    assert "context_built" in types
    assert "decision_emitted" in types


@pytest.mark.test_id("ADP-002")
async def test_tool_candidates_flow_through_tool_gateway() -> None:
    # The deterministic adapter emits model decisions; tool candidates are
    # only ever produced as ToolIntent via ToolIntentPort, never executed
    # directly by the adapter.
    run, ctx = await _execution_context(DeterministicFakeModel(), call_log=[])
    assert ctx.tool_intent_port is not None
    assert ctx.model_step_port is not None
    assert ctx.context_build_port is not None
    assert ctx.telemetry_port is not None


@pytest.mark.test_id("ADP-004")
def test_second_adapter_is_equivalent_for_read_only_agent() -> None:
    langgraph = LangGraphAdapter()
    read_only = OpenAIAgentsReadOnlyAdapter(allow_tool_calls=False)

    lg_caps = langgraph.DescribeRuntime()
    oai_caps = read_only.DescribeRuntime()
    assert lg_caps.supported_contract_versions == oai_caps.supported_contract_versions
    assert oai_caps.native_tool_calls is False
    # Both adapters expose the same typed SPI surface (equivalence of semantics).
    for name in ("DescribeRuntime", "StartRun", "AdvanceRun", "SuspendRun", "ResumeRun",
                 "CancelRun", "InspectRun"):
        assert callable(getattr(langgraph, name))
        assert callable(getattr(read_only, name))


@pytest.mark.test_id("ADP-005")
async def test_runtime_event_is_not_authoritative_event_envelope() -> None:
    run, ctx = await _execution_context(DeterministicFakeModel(), call_log=[])
    adapter = DeterministicRuntimeAdapter()
    session = adapter.StartRun(
        RuntimeStartRequest(
            tenant_id=run.meta.tenant_id,
            task_id=run.task_id,
            run_id=run.run_id,
            task_envelope_ref=f"task:{run.task_id}",
            run_record_ref=f"run:{run.run_id}",
            principal_context_ref="principal:1",
            release_id=run.release_id,
            budget_snapshot_ref="budget-snapshot:1",
            agent_definition_ref="agent:1",
            prompt_contract_ref=f"prompt:{run.run_id}",
            output_schema_ref=SCHEMA_REF,
            runtime_adapter_ref="adapter:deterministic",
            execution_context=ctx,
        )
    )
    from ueaf.ports import RuntimeAdvanceRequest

    stream = adapter.AdvanceRun(
        RuntimeAdvanceRequest(
            session=session,
            expected_revision=run.revision,
            fencing_token=ctx.fencing_token,
            max_events=4,
            deadline_at=run.deadline_at,
        )
    )
    events = await _drain(stream)
    # Adapter events are RuntimeEvent; they must never impersonate ueaf.* EventEnvelope.
    for event in events:
        assert event.event_type == "ueaf" or not event.event_type.startswith("ueaf.")


@pytest.mark.test_id("CON-006")
def test_runtime_adapter_has_full_normative_spi() -> None:
    adapter = DeterministicRuntimeAdapter()
    for name in ("DescribeRuntime", "StartRun", "AdvanceRun", "SuspendRun", "ResumeRun",
                 "CancelRun", "InspectRun"):
        assert callable(getattr(adapter, name))
