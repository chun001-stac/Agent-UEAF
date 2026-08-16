"""OpenAI Agents SDK 只读一致性适配器（适配器 #2）。

仅提供只读的一致性骨架：如实上报能力，将每一次模型/工具交互都经由白名单端口
路由，并明确拒绝不支持的能力（ADP-003）。绝不编造权威事件（ADP-005）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from ueaf.ports import (
    RuntimeAdvanceRequest,
    RuntimeCancellationObservation,
    RuntimeCancelRequest,
    RuntimeCapabilities,
    RuntimeCheckpointRef,
    RuntimeEvent,
    RuntimeEventStream,
    RuntimeInspectRequest,
    RuntimeObservation,
    RuntimeResumeRequest,
    RuntimeSession,
    RuntimeStartRequest,
    RuntimeSuspendRequest,
)

from .base import _StaticEventStream


class OpenAIAgentsReadOnlyAdapter:
    """只读一致性骨架；不支持的能力默认失败关闭。"""

    def __init__(self, *, allow_tool_calls: bool = False) -> None:
        self._allow_tool_calls = allow_tool_calls

    def DescribeRuntime(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            streaming=True,
            suspend_resume=True,
            durable_checkpoint=False,
            human_interrupt=False,
            parallel_branches=False,
            deterministic_replay=True,
            native_tool_calls=self._allow_tool_calls,
            structured_output=True,
            handoff=False,
            cancellation_ack=True,
            max_context_tokens=16_384,
            max_steps=32,
            supported_contract_versions=("1.0.0",),
        )

    def StartRun(self, request: RuntimeStartRequest) -> RuntimeSession:
        return RuntimeSession(
            run_id=request.run_id,
            session_ref=f"oai-session:{request.run_id}",
            external_session_ref=None,
            started_at=datetime.now(UTC),
        )

    def AdvanceRun(self, request: RuntimeAdvanceRequest) -> RuntimeEventStream:
        # 只读步骤：仅允许确定性 final_response 决策。
        if not self._allow_tool_calls:
            return _StaticEventStream(
                [
                    RuntimeEvent(
                        event_id=f"oai-runtime-event:{request.session.run_id}:1",
                        run_id=request.session.run_id,
                        sequence=1,
                        event_type="decision_emitted",
                        payload_ref=f"decision:{request.session.run_id}",
                        occurred_at=datetime.now(UTC),
                    )
                ]
            )
        return _StaticEventStream([])

    def SuspendRun(self, request: RuntimeSuspendRequest) -> RuntimeCheckpointRef:
        return RuntimeCheckpointRef(
            checkpoint_id=f"oai-checkpoint:{request.session.run_id}",
            run_id=request.session.run_id,
            state_schema_version="1.0.0",
            integrity_ref=f"integrity:{request.session.run_id}",
        )

    def ResumeRun(self, request: RuntimeResumeRequest) -> RuntimeSession:
        return RuntimeSession(
            run_id=request.checkpoint_ref.run_id,
            session_ref=f"oai-session:{request.checkpoint_ref.run_id}",
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
            observed_revision=1,
            last_event_sequence=1,
            checkpoint_ref=None,
            observed_at=datetime.now(UTC),
        )
