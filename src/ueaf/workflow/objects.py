"""Workflow canonical objects (functional module 06).

``WorkflowRun`` executes a versioned workflow definition as recoverable,
cancellable, budgeted and auditable ``NodeRun`` instances. A ``NodeRun`` is one
node execution (agent / action / wait / subflow); a ``NodeAttempt`` is one
attempt of that node. Handoffs travel as minimal ``HandoffEnvelope``.
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
    """Versioned workflow definition; a run instance binds an immutable version."""

    meta: ContractMeta
    workflow_id: str
    workflow_version: str
    owner: str
    schema_ref: str
    nodes: tuple[str, ...] = ()
    edges: tuple[tuple[str, str], ...] = ()  # (from_node, to_node)

    def __post_init__(self) -> None:
        if self.workflow_id != self.meta.object_id:
            raise ValueError("WorkflowDefinition.meta.object_id must equal workflow_id")


@dataclass(frozen=True, slots=True)
class NodeRun:
    """One node execution within a WorkflowRun."""

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
    """One attempt of a node; all attempts are preserved (EVAL-017 analog)."""

    node_attempt_id: str
    node_run_id: str
    attempt: int
    status: Literal["running", "succeeded", "failed", "unknown"] = "running"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_ref: str | None = None


@dataclass(slots=True)
class WorkflowRun:
    """Executable workflow run (recoverable, cancellable, auditable)."""

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
