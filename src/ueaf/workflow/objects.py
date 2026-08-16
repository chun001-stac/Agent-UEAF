"""工作流规范对象（功能模块 06）。

``WorkflowRun`` 以可恢复、可取消、有预算且可审计的 ``NodeRun`` 实例来执行版本化的工作流
定义。一个 ``NodeRun`` 是一次节点执行（agent / action / wait / subflow）；一个
``NodeAttempt`` 是该节点的某一次尝试。交接以最小化的 ``HandoffEnvelope`` 传递。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta

NodeKind = Literal["agent", "action", "wait", "subflow"]
WorkflowRunStatus = Literal["pending", "running", "waiting", "completed", "cancelled", "failed"]
NodeRunStatus = Literal["pending", "running", "waiting", "completed", "failed", "skipped"]

_NODE_KINDS: frozenset[str] = frozenset({"agent", "action", "wait", "subflow"})


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    """版本化工作流定义；运行实例绑定不可变的版本。"""

    meta: ContractMeta
    workflow_id: str
    workflow_version: str
    owner: str
    schema_ref: str
    nodes: tuple[str, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()  # (起点节点, 终点节点)

    def __post_init__(self) -> None:
        if self.workflow_id != self.meta.object_id:
            raise ValueError("WorkflowDefinition.meta.object_id must equal workflow_id")


@dataclass(frozen=True, slots=True)
class NodeRun:
    """WorkflowRun 中的一次节点执行。"""

    meta: ContractMeta
    node_run_id: str
    workflow_run_id: str
    node_id: str
    kind: NodeKind
    status: NodeRunStatus = "pending"
    attempt: int = 0
    dependencies: tuple[str, ...] = ()
    handoff_ref: str | None = None
    result_ref: str | None = None

    def __post_init__(self) -> None:
        if self.node_run_id != self.meta.object_id:
            raise ValueError("NodeRun.meta.object_id must equal node_run_id")
        if self.kind not in _NODE_KINDS:
            raise ValueError(f"invalid NodeRun kind {self.kind!r}")


@dataclass(frozen=True, slots=True)
class NodeAttempt:
    """节点的某一次尝试；所有尝试都会被保留（与 EVAL-017 类似）。"""

    node_attempt_id: str
    node_run_id: str
    attempt: int
    status: Literal["running", "succeeded", "failed", "unknown"] = "running"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_ref: str | None = None


@dataclass(slots=True)
class WorkflowRun:
    """可执行的工作流运行（可恢复、可取消、可审计）。"""

    meta: ContractMeta
    workflow_run_id: str
    workflow_id: str
    workflow_version: str
    status: WorkflowRunStatus = "pending"
    budget_slice_ref: str | None = None
    principal_context_ref: str | None = None
    node_runs: list[NodeRun] = field(default_factory=list)
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.workflow_run_id != self.meta.object_id:
            raise ValueError("WorkflowRun.meta.object_id must equal workflow_run_id")


__all__ = [
    "WorkflowDefinition",
    "NodeRun",
    "NodeAttempt",
    "WorkflowRun",
]
