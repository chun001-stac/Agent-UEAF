from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    # 仅在类型注解中使用：ManifestSection/CompressionRecord 定义于 context 模块
    # （模块内部派生对象），此处不产生运行时导入，避免循环依赖。
    from ueaf.context.compression import CompressionRecord
    from ueaf.context.context_build import ManifestSection

Retryability = Literal["never", "safe", "conditional", "after_reconciliation"]
Certainty = Literal["not_executed", "unknown"]


@dataclass(frozen=True, slots=True)
class PortError:
    """A normalized port failure; message bodies remain behind references."""

    code: str
    category: str
    retryability: Retryability
    certainty: Certainty
    message_ref: str | None
    provider_error_ref: str | None
    observed_at: datetime
    details_schema_ref: str | None


@dataclass(frozen=True, slots=True)
class Success[T]:
    value: T
    status: Literal["success"] = field(init=False, default="success")
    error: None = field(init=False, default=None)


@dataclass(frozen=True, slots=True)
class Rejected:
    """The operation is known not to have executed or to have failed definitively."""

    error: PortError
    status: Literal["rejected"] = field(init=False, default="rejected")
    value: None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.error.certainty != "not_executed":
            raise ValueError("Rejected requires PortError.certainty='not_executed'")


@dataclass(frozen=True, slots=True)
class Unknown:
    """The side-effect outcome is unknown and must be reconciled before replay."""

    error: PortError
    status: Literal["unknown"] = field(init=False, default="unknown")
    value: None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.error.certainty != "unknown":
            raise ValueError("Unknown requires PortError.certainty='unknown'")


type PortResult[T] = Success[T] | Rejected | Unknown


class ReleaseActivationVerifier(Protocol):
    """Trusted Phase 4 dependency required before a release can be activated.

    This Protocol only defines the fail-closed integration boundary. Phase 0 does not
    implement integrity resolution, evidence authorization, authority trust, waiver
    conflict detection, scope resolution, or rollback compatibility itself. A real
    implementation must resolve immutable authority-store facts, prove that every
    ``candidate_ref`` binds the candidate digest and complete version graph, and prove
    that each Gate's Evidence covers that exact graph. An allow-all fake is suitable
    only for boundary tests and is never a production verifier.
    """

    def verify_integrity(self, contract_name: str, instance: Mapping[str, object]) -> bool: ...

    def verify_evidence_access(
        self, contract_name: str, instance: Mapping[str, object]
    ) -> bool: ...

    def verify_authority_role_and_trust(
        self,
        contract_name: str,
        authority_ref: str,
        instance: Mapping[str, object],
    ) -> bool: ...

    def verify_waiver_conflicts(
        self, contract_name: str, instance: Mapping[str, object]
    ) -> bool: ...

    def verify_scope_coverage(
        self,
        contract_name: str,
        expected_scope: Mapping[str, object],
        instance: Mapping[str, object],
    ) -> bool: ...

    def verify_rollback_compatibility(
        self,
        release_candidate: Mapping[str, object],
        release_manifest: Mapping[str, object],
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class RuntimeCapabilities:
    streaming: bool
    suspend_resume: bool
    durable_checkpoint: bool
    human_interrupt: bool
    parallel_branches: bool
    deterministic_replay: bool
    native_tool_calls: bool
    structured_output: bool
    handoff: bool
    cancellation_ack: bool
    max_context_tokens: int
    max_steps: int
    supported_contract_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    tenant_id: str
    run_id: str
    query_intent_ref: str
    policy_snapshot_ref: str
    budget_snapshot_ref: str
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class ContextManifest:
    context_manifest_id: str
    run_id: str
    schema_ref: str
    evidence_pack_refs: tuple[str, ...]
    integrity_ref: str
    # ---- 模块 04 Context Builder 的增量装配字段（仅由它构造，带默认值避免
    #      破坏既有构造/测试）。----
    sections: tuple[ManifestSection, ...] = ()
    source_refs: tuple[str, ...] = ()
    policy_snapshot_ref: str | None = None
    budget_before: int | None = None
    budget_after: int | None = None
    selection_decisions: tuple[str, ...] = ()
    omissions: tuple[str, ...] = ()
    compression_records: tuple[CompressionRecord, ...] = ()
    trust_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    model_invocation_id: str
    run_id: str
    prompt_contract_ref: str
    context_manifest_ref: str
    model_route_ref: str
    output_schema_ref: str
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class StructuredDecision:
    structured_decision_id: str
    run_id: str
    turn_id: str
    kind: Literal[
        "final_response",
        "tool_intents",
        "handoff",
        "need_input",
        "refusal",
        "no_progress",
    ]
    schema_ref: str
    validation_result_ref: str
    source_model_result_ref: str


@dataclass(frozen=True, slots=True)
class ToolIntent:
    tool_intent_id: str
    run_id: str
    capability_ref: str
    input_schema_ref: str
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ActionRecordRef:
    action_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class ControlledInterruption:
    wait_reason: Literal["policy", "approval", "external_result", "reconciliation"]
    resume_condition_ref: str
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class HandoffEnvelope:
    handoff_id: str
    tenant_id: str
    source_run_id: str
    target_ref: str
    subgoal_ref: str
    budget_slice_ref: str
    principal_context_ref: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class HandoffProgress:
    handoff_id: str
    disposition: Literal["accepted", "waiting", "completed", "failed"]
    target_run_ref: str | None
    result_ref: str | None


@dataclass(frozen=True, slots=True)
class TraceRecord:
    trace_id: str
    tenant_id: str
    run_id: str
    release_id: str
    adapter_ref: str
    result_class: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class MetricPoint:
    metric_name: str
    value: int | float
    tenant_id: str
    release_id: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class LogRecord:
    level: Literal["debug", "info", "warning", "error", "critical"]
    message_ref: str
    tenant_id: str
    run_id: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AuditRecord:
    audit_record_id: str
    tenant_id: str
    actor_ref: str
    action: str
    object_ref: str
    evidence_refs: tuple[str, ...]
    occurred_at: datetime
    integrity_ref: str


@dataclass(frozen=True, slots=True)
class TelemetryAck:
    accepted_count: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AuditCommitReceipt:
    audit_record_id: str
    commit_ref: str
    committed_at: datetime
    integrity_ref: str


class ContextBuildPort(Protocol):
    def build(self, request: ContextBuildRequest) -> PortResult[ContextManifest]: ...


class ModelStepPort(Protocol):
    def invoke(self, request: ModelInvocation) -> PortResult[StructuredDecision]: ...


class ToolIntentPort(Protocol):
    def submit(
        self, request: ToolIntent
    ) -> PortResult[ActionRecordRef | ControlledInterruption]: ...


class HandoffPort(Protocol):
    def submit(self, request: HandoffEnvelope) -> PortResult[HandoffProgress]: ...


class TelemetryPort(Protocol):
    def EmitTrace(self, record: TraceRecord) -> PortResult[TelemetryAck]: ...
    def EmitMetric(self, points: Sequence[MetricPoint]) -> PortResult[TelemetryAck]: ...
    def EmitLog(self, records: Sequence[LogRecord]) -> PortResult[TelemetryAck]: ...
    def EmitAudit(self, record: AuditRecord) -> PortResult[AuditCommitReceipt]: ...


@dataclass(frozen=True, slots=True)
class RuntimeExecutionContext:
    tenant_id: str
    run_id: str
    release_id: str
    trace_id: str
    revision: int
    fencing_token: int
    deadline_at: datetime
    cancellation_ref: str
    context_build_port: ContextBuildPort
    model_step_port: ModelStepPort
    tool_intent_port: ToolIntentPort
    handoff_port: HandoffPort
    telemetry_port: TelemetryPort


@dataclass(frozen=True, slots=True)
class RuntimeStartRequest:
    tenant_id: str
    task_id: str
    run_id: str
    task_envelope_ref: str
    run_record_ref: str
    principal_context_ref: str
    release_id: str
    budget_snapshot_ref: str
    agent_definition_ref: str
    prompt_contract_ref: str
    output_schema_ref: str
    runtime_adapter_ref: str
    execution_context: RuntimeExecutionContext


@dataclass(frozen=True, slots=True)
class RuntimeSession:
    run_id: str
    session_ref: str
    external_session_ref: str | None
    started_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeAdvanceRequest:
    session: RuntimeSession
    expected_revision: int
    fencing_token: int
    max_events: int
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    event_id: str
    run_id: str
    sequence: int
    event_type: str
    payload_ref: str
    occurred_at: datetime


class RuntimeEventStream(Protocol):
    def __aiter__(self) -> AsyncIterator[RuntimeEvent]: ...


@dataclass(frozen=True, slots=True)
class RuntimeSuspendRequest:
    session: RuntimeSession
    expected_revision: int
    fencing_token: int
    reason_ref: str
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeCheckpointRef:
    checkpoint_id: str
    run_id: str
    state_schema_version: str
    integrity_ref: str


@dataclass(frozen=True, slots=True)
class RuntimeResumeRequest:
    checkpoint_ref: RuntimeCheckpointRef
    expected_runtime_version: str
    fencing_token: int
    execution_context: RuntimeExecutionContext


@dataclass(frozen=True, slots=True)
class RuntimeCancelRequest:
    session: RuntimeSession
    fencing_token: int
    cancellation_ref: str
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeCancellationObservation:
    run_id: str
    disposition: Literal["acknowledged", "already_terminal", "unknown"]
    observed_at: datetime
    unresolved_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeInspectRequest:
    run_id: str
    session_ref: str
    consistency_requirement: Literal["eventual", "strong"]
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    run_id: str
    runtime_phase: str
    observed_revision: int
    last_event_sequence: int
    checkpoint_ref: RuntimeCheckpointRef | None
    observed_at: datetime


class RuntimeAdapter(Protocol):
    def DescribeRuntime(self) -> RuntimeCapabilities: ...
    def StartRun(self, request: RuntimeStartRequest) -> RuntimeSession: ...
    def AdvanceRun(self, request: RuntimeAdvanceRequest) -> RuntimeEventStream: ...
    def SuspendRun(self, request: RuntimeSuspendRequest) -> RuntimeCheckpointRef: ...
    def ResumeRun(self, request: RuntimeResumeRequest) -> RuntimeSession: ...
    def CancelRun(self, request: RuntimeCancelRequest) -> RuntimeCancellationObservation: ...
    def InspectRun(self, request: RuntimeInspectRequest) -> RuntimeObservation: ...
