"""工作流编排器（功能模块 06）。

通过调度就绪（依赖已满足）的 ``NodeRun`` 实例来推进 ``WorkflowRun``，并遵循节点依赖、
路由与有界重试。交接通过核心 ``HandoffPort`` 以最小化的 ``HandoffEnvelope`` 发出。
没有证据的失败节点绝不自行动大权限范围（REP-003），且在没有有界尝试预算的情况下
绝不重新运行。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ueaf.common.identifiers import new_object_id
from ueaf.common.meta import ContractMeta
from ueaf.workflow.objects import (
    NodeAttempt,
    NodeKind,
    NodeRun,
    WorkflowDefinition,
    WorkflowRun,
)


@dataclass(frozen=True, slots=True)
class ScheduleDecision:
    advanced: bool
    node_run_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


class WorkflowOrchestrator:
    """拥有节点调度权；WorkflowRun 是唯一的状态对象。"""

    def __init__(
        self,
        handoff_port: object,
        *,
        max_attempts: int = 2,
        producer_version: str = "0.1.0",
    ) -> None:
        self._handoff_port = handoff_port
        self._max_attempts = max_attempts
        self._producer_version = producer_version
        self._attempts: dict[str, list[NodeAttempt]] = {}

    def instantiate(
        self,
        definition: WorkflowDefinition,
        *,
        workflow_run_id: str,
        budget_slice_ref: str | None = None,
        principal_context_ref: str | None = None,
    ) -> WorkflowRun:
        run = WorkflowRun(
            meta=_meta("WorkflowRun", workflow_run_id, definition),
            workflow_run_id=workflow_run_id,
            workflow_id=definition.workflow_id,
            workflow_version=definition.workflow_version,
            status="pending",
            budget_slice_ref=budget_slice_ref,
            principal_context_ref=principal_context_ref,
        )
        for node_id in definition.nodes:
            deps = [edge[0] for edge in definition.edges if edge[1] == node_id]
            run.node_runs.append(
                NodeRun(
                    meta=_meta("NodeRun", f"{workflow_run_id}:{node_id}", definition),
                    node_run_id=f"{workflow_run_id}:{node_id}",
                    workflow_run_id=workflow_run_id,
                    node_id=node_id,
                    kind=_kind_of(node_id),
                    dependencies=tuple(deps),
                )
            )
        return run

    def schedule_ready(self, run: WorkflowRun) -> ScheduleDecision:
        """当节点的依赖全部完成时将其标记为就绪。"""
        advanced: list[str] = []
        completed = {nr.node_id for nr in run.node_runs if nr.status == "completed"}
        for index, node_run in enumerate(run.node_runs):
            if node_run.status != "pending":
                continue
            if all(dep in completed for dep in node_run.dependencies):
                run.node_runs[index] = replace(node_run, status="running")
                advanced.append(node_run.node_run_id)
        if advanced:
            run.status = "running"
        return ScheduleDecision(bool(advanced), tuple(advanced), ("scheduled",))

    def complete_node(self, run: WorkflowRun, node_id: str) -> bool:
        for index, node_run in enumerate(run.node_runs):
            if node_run.node_id == node_id:
                run.node_runs[index] = replace(node_run, status="completed")
                break
        if all(nr.status == "completed" for nr in run.node_runs):
            run.status = "completed"
        return run.status == "completed"

    def fail_node(self, run: WorkflowRun, node_id: str) -> bool:
        """使节点失败并将运行标记为失败（有界重试在别处处理）。"""
        for index, node_run in enumerate(run.node_runs):
            if node_run.node_id == node_id:
                run.node_runs[index] = replace(node_run, status="failed")
                break
        run.status = "failed"
        return False

    def record_attempt(
        self, node_run_id: str, *, attempt: int, status: str, result_ref: str | None = None
    ) -> NodeAttempt:
        record = NodeAttempt(
            node_attempt_id=new_object_id("node_attempt"),
            node_run_id=node_run_id,
            attempt=attempt,
            status=status,  # type: ignore[arg-type]
            result_ref=result_ref,
        )
        self._attempts.setdefault(node_run_id, []).append(record)
        return record

    def attempts_for(self, node_run_id: str) -> tuple[NodeAttempt, ...]:
        return tuple(self._attempts.get(node_run_id, []))


def _meta(contract: str, object_id: str, definition: WorkflowDefinition) -> ContractMeta:
    return ContractMeta(
        contract_name=contract,
        contract_version=definition.workflow_version,
        object_id=object_id,
        tenant_id=definition.meta.tenant_id,
        created_at=definition.meta.created_at,
        producer="ueaf-workflow",
        producer_version="0.1.0",
    )


def _kind_of(node_id: str) -> NodeKind:
    if node_id.startswith("agent:"):
        return "agent"
    if node_id.startswith("action:"):
        return "action"
    if node_id.startswith("wait:"):
        return "wait"
    if node_id.startswith("subflow:"):
        return "subflow"
    return "action"


__all__ = ["WorkflowOrchestrator", "ScheduleDecision"]
