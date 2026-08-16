"""驱动受控冒烟链的确定性运行时适配器（CI 安全）。

``ContextBuildPort -> ModelStepPort -> StructuredDecision`` 链路在
AdvanceRun 内部运行，仅使用执行上下文中的白名单端口（ADP-001、ADP-002）。
它绝不产生 EvalResult / QualityGateDecision / ReleaseDecision —— 这仅用于
非 Eval 的运行时冒烟测试。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from ueaf.ports import (
    ContextBuildRequest,
    ModelInvocation,
    RuntimeAdvanceRequest,
    RuntimeCancellationObservation,
    RuntimeCancelRequest,
    RuntimeCapabilities,
    RuntimeCheckpointRef,
    RuntimeEvent,
    RuntimeEventStream,
    RuntimeExecutionContext,
    RuntimeInspectRequest,
    RuntimeObservation,
    RuntimeResumeRequest,
    RuntimeSession,
    RuntimeStartRequest,
    RuntimeSuspendRequest,
    Success,
)


class _StaticEventStream:
    """对固定 RuntimeEvents 列表的异步迭代器。"""

    def __init__(self, events: list[RuntimeEvent]) -> None:
        self._events = events

    def __aiter__(self) -> AsyncIterator[RuntimeEvent]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[RuntimeEvent]:
        for event in self._events:
            yield event


class DeterministicRuntimeAdapter:
    """每次 AdvanceRun 调用运行一个受控步骤（单轮冒烟测试）。"""

    def __init__(
        self,
        *,
        adapter_ref: str = "adapter:deterministic",
        supported_contract_versions: tuple[str, ...] = ("1.0.0",),
    ) -> None:
        self._adapter_ref = adapter_ref
        self._contract_versions = supported_contract_versions
        self._sessions: dict[str, RuntimeSession] = {}
        self._contexts: dict[str, RuntimeExecutionContext] = {}
        self._sequence: dict[str, int] = {}

    # -- SPI ---------------------------------------------------------------

    def DescribeRuntime(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            streaming=True,
            suspend_resume=True,
            durable_checkpoint=True,
            human_interrupt=False,
            parallel_branches=False,
            deterministic_replay=True,
            native_tool_calls=False,
            structured_output=True,
            handoff=False,
            cancellation_ack=True,
            max_context_tokens=16_384,
            max_steps=32,
            supported_contract_versions=self._contract_versions,
        )

    def StartRun(self, request: RuntimeStartRequest) -> RuntimeSession:
        session = RuntimeSession(
            run_id=request.run_id,
            session_ref=f"session:{request.run_id}",
            external_session_ref=None,
            started_at=datetime.now(UTC),
        )
        self._sessions[request.run_id] = session
        self._contexts[request.run_id] = request.execution_context
        self._sequence[request.run_id] = 0
        return session

    def AdvanceRun(self, request: RuntimeAdvanceRequest) -> RuntimeEventStream:
        run_id = request.session.run_id
        ctx = self._contexts.get(run_id)
        if ctx is None:
            return _StaticEventStream([])
        if request.fencing_token < ctx.fencing_token:
            return _StaticEventStream([])
        events = self._step(run_id, ctx)
        for event in events:
            self._sequence[run_id] = event.sequence
        return _StaticEventStream(events)

    def SuspendRun(self, request: RuntimeSuspendRequest) -> RuntimeCheckpointRef:
        return RuntimeCheckpointRef(
            checkpoint_id=f"checkpoint:{request.session.run_id}",
            run_id=request.session.run_id,
            state_schema_version="1.0.0",
            integrity_ref=f"integrity:{request.session.run_id}",
        )

    def ResumeRun(self, request: RuntimeResumeRequest) -> RuntimeSession:
        return RuntimeSession(
            run_id=request.checkpoint_ref.run_id,
            session_ref=f"session:{request.checkpoint_ref.run_id}",
            external_session_ref=None,
            started_at=datetime.now(UTC),
        )

    def CancelRun(self, request: RuntimeCancelRequest) -> RuntimeCancellationObservation:
        return RuntimeCancellationObservation(
            run_id=request.session.run_id,
            disposition="acknowledged",
            observed_at=datetime.now(UTC),
            unresolved_refs=(),
        )

    def InspectRun(self, request: RuntimeInspectRequest) -> RuntimeObservation:
        return RuntimeObservation(
            run_id=request.run_id,
            runtime_phase="running",
            observed_revision=request.run_id.count(":") + 1,
            last_event_sequence=self._sequence.get(request.run_id, 0),
            checkpoint_ref=None,
            observed_at=datetime.now(UTC),
        )

    # -- 内部实现 ---------------------------------------------------------

    def _step(
        self, run_id: str, ctx: RuntimeExecutionContext
    ) -> list[RuntimeEvent]:
        events: list[RuntimeEvent] = []
        seq = self._sequence.get(run_id, 0)

        # 1) ContextBuildPort（仅核心 SPI）
        manifest_result = ctx.context_build_port.build(
            self._context_request(run_id, ctx)
        )
        manifest_ref = None
        if isinstance(manifest_result, Success):
            manifest_ref = manifest_result.value.context_manifest_id
        events.append(
            self._event(run_id, seq + 1, "context_built", manifest_ref or "context:omitted")
        )

        # 2) ModelStepPort（冻结的 prompt/route/output schema）
        invocation = ModelInvocation(
            model_invocation_id=f"model-invoke:{run_id}:{seq + 2}",
            run_id=run_id,
            prompt_contract_ref=f"prompt:{run_id}",
            context_manifest_ref=manifest_ref or "context:omitted",
            model_route_ref=f"model-route:{run_id}",
            output_schema_ref="schema://structured-decision/1.0.0",
            deadline_at=datetime.now(UTC),
        )
        decision_result = ctx.model_step_port.invoke(invocation)
        if isinstance(decision_result, Success):
            events.append(
                self._event(
                    run_id,
                    seq + 2,
                    "decision_emitted",
                    decision_result.value.structured_decision_id,
                )
            )
        else:
            events.append(self._event(run_id, seq + 2, "model_step_rejected", run_id))
        return events

    @staticmethod
    def _context_request(
        run_id: str, ctx: RuntimeExecutionContext
    ) -> ContextBuildRequest:
        return ContextBuildRequest(
            tenant_id=ctx.tenant_id,
            run_id=run_id,
            query_intent_ref=f"query:{run_id}",
            policy_snapshot_ref=f"policy:{run_id}",
            budget_snapshot_ref=f"budget:{run_id}",
            deadline_at=datetime.now(UTC),
        )

    @staticmethod
    def _event(run_id: str, sequence: int, event_type: str, payload_ref: str) -> RuntimeEvent:
        return RuntimeEvent(
            event_id=f"runtime-event:{run_id}:{sequence}",
            run_id=run_id,
            sequence=sequence,
            event_type=event_type,
            payload_ref=payload_ref,
            occurred_at=datetime.now(UTC),
        )
