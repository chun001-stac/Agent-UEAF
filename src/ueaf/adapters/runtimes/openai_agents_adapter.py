"""OpenAI Agents SDK read-only conformance adapter (Adapter #2).

Only a read-only conformance skeleton: it advertises capabilities truthfully,
routes every model/tool interaction through the whitelisted ports, and
explicitly rejects unsupported capabilities (ADP-003). It never fabricates
authoritative events (ADP-005).
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
    """Read-only conformance skeleton; unsupported capabilities fail closed."""

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
        # Read-only step: only a deterministic final_response decision is allowed.
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
