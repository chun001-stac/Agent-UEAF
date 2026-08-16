"""运行时/运行状态规范对象（core spec 01 §9，spec 02 §3）。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta

RunPhase = Literal[
    "queued", "admitting", "running", "waiting", "retrying", "paused", "terminal"
]
CompletionDisposition = Literal[
    "completed", "rejected", "incomplete", "failed", "cancelled"
]
WaitReason = Literal[
    "user_input", "tool_result", "approval", "dependency", "capacity", "reconciliation"
]

RUN_PHASES: frozenset[str] = frozenset(
    {"queued", "admitting", "running", "waiting", "retrying", "paused", "terminal"}
)
COMPLETION_DISPOSITIONS: frozenset[str] = frozenset(
    {"completed", "rejected", "incomplete", "failed", "cancelled"}
)
WAIT_REASONS: frozenset[str] = frozenset(
    {"user_input", "tool_result", "approval", "dependency", "capacity", "reconciliation"}
)


@dataclass(frozen=True, slots=True)
class RunLease:
    """执行租约；单调递增的 fencing token 用于隔离过期写入者。"""

    lease_id: str
    holder_id: str
    fencing_token: int
    acquired_at: datetime
    heartbeat_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.lease_id or not self.holder_id:
            raise ValueError("RunLease.lease_id/holder_id must not be empty")
        if self.fencing_token < 1:
            raise ValueError("RunLease.fencing_token must be a positive integer")
        if not (self.acquired_at <= self.heartbeat_at < self.expires_at):
            raise ValueError(
                "RunLease must satisfy acquired_at <= heartbeat_at < expires_at"
            )

    def is_held_at(self, moment: datetime) -> bool:
        return self.acquired_at <= moment < self.expires_at


@dataclass(frozen=True, slots=True)
class BudgetSnapshotRef:
    snapshot_ref: str
    used: Mapping[str, int] = field(default_factory=dict)
    reserved: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """规范 Run 聚合；phase/disposition/wait_reason 保持相互正交。"""

    meta: ContractMeta
    run_id: str
    task_id: str
    agent_ref: str
    runtime_adapter_ref: str
    release_id: str
    phase: RunPhase
    completion_disposition: CompletionDisposition | None = None
    wait_reason: WaitReason | None = None
    wait_condition_refs: tuple[str, ...] = ()
    attempt: int = 1
    budget_snapshot_ref: str | None = None
    checkpoint_ref: str | None = None
    pending_action_refs: tuple[str, ...] = ()
    result_ref: str | None = None
    error_ref: str | None = None
    terminal_reason_codes: tuple[str, ...] = ()
    revision: int = 1
    sequence: int = 0
    lease: RunLease | None = None
    deadline_at: datetime | None = None
    parent_run_id: str | None = None
    wait_origin: Literal["admission_deferred", "admitted_execution"] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.run_id != self.meta.object_id:
            raise ValueError("RunRecord.meta.object_id must equal run_id")
        if self.phase not in RUN_PHASES:
            raise ValueError(f"invalid RunPhase {self.phase!r}")
        if self.completion_disposition is not None and self.phase != "terminal":
            raise ValueError(
                "completion_disposition is only valid when phase=terminal (RUN-002)"
            )
        if self.phase == "terminal" and self.completion_disposition is None:
            raise ValueError("terminal RunRecord MUST set completion_disposition (RUN-002)")
        if self.wait_reason is not None and self.phase != "waiting":
            raise ValueError("wait_reason is only valid when phase=waiting")
        if self.phase == "waiting" and not self.wait_condition_refs:
            raise ValueError("waiting RunRecord MUST set wait_condition_refs")
        if self.completion_disposition is not None and not self.terminal_reason_codes:
            raise ValueError("terminal RunRecord MUST set terminal_reason_codes")
        if self.attempt < 1:
            raise ValueError("RunRecord.attempt must be >= 1")
        if self.revision < 1:
            raise ValueError("RunRecord.revision must be >= 1")
        if self.lease is not None and self.phase in ("queued", "waiting", "paused"):
            raise ValueError(
                f"RunLease is not valid while phase={self.phase!r}"
            )
        if self.wait_origin is not None and self.phase != "waiting":
            raise ValueError("wait_origin is only valid when phase=waiting")

    @property
    def is_terminal(self) -> bool:
        return self.phase == "terminal"


@dataclass(frozen=True, slots=True)
class TaskState:
    """可变的任务域状态；只记录确定性进展，不记录摘要。"""

    meta: ContractMeta
    task_id: str
    completion_criteria_state: Mapping[str, object] = field(default_factory=dict)
    confirmed_facts: tuple[str, ...] = ()
    pending_conditions: tuple[str, ...] = ()
    derived_summary_ref: str | None = None
    revision: int = 1

    def __post_init__(self) -> None:
        if self.task_id != self.meta.object_id:
            raise ValueError("TaskState.meta.object_id must equal task_id")
        if self.revision < 1:
            raise ValueError("TaskState.revision must be >= 1")


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """可恢复的运行位置；不证明不存在外部副作用。"""

    meta: ContractMeta
    checkpoint_id: str
    run_id: str
    state_schema_version: str
    runtime_native_checkpoint_ref: str | None = None
    pending_condition_refs: tuple[str, ...] = ()
    in_flight_action_refs: tuple[str, ...] = ()
    frozen_release_id: str | None = None
    concurrency_token: int | None = None
    integrity_ref: str | None = None

    def __post_init__(self) -> None:
        if self.checkpoint_id != self.meta.object_id:
            raise ValueError("Checkpoint.meta.object_id must equal checkpoint_id")
