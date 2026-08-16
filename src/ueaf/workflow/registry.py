"""工作流注册表（功能模块 06）。

管理工作流定义、模式、所有者、兼容性与发布。运行实例绑定不可变的定义版本；更新的兼容
定义绝不静默改写正在运行中的 run。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ueaf.workflow.objects import WorkflowDefinition


@dataclass(frozen=True, slots=True)
class WorkflowCompatibility:
    compatible: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(slots=True)
class WorkflowRegistry:
    """按 (id, version) 组织的工作流定义不可变注册表。"""

    _definitions: dict[tuple[str, str], WorkflowDefinition] = field(default_factory=dict)

    def register(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        key = (definition.workflow_id, definition.workflow_version)
        if key in self._definitions:
            raise ValueError(f"WorkflowDefinition {key} already registered")
        self._definitions[key] = definition
        return definition

    def get(self, workflow_id: str, workflow_version: str) -> WorkflowDefinition | None:
        return self._definitions.get((workflow_id, workflow_version))

    def require(self, workflow_id: str, workflow_version: str) -> WorkflowDefinition:
        definition = self.get(workflow_id, workflow_version)
        if definition is None:
            raise KeyError(f"WorkflowDefinition {workflow_id}@{workflow_version} not found")
        return definition

    def check_compatibility(
        self, a: WorkflowDefinition, b: WorkflowDefinition
    ) -> WorkflowCompatibility:
        if a.workflow_id != b.workflow_id:
            return WorkflowCompatibility(False, ("different_workflow_id",))
        if a.schema_ref != b.schema_ref:
            return WorkflowCompatibility(False, ("schema_ref_changed",))
        if a.owner != b.owner:
            return WorkflowCompatibility(False, ("owner_changed",))
        return WorkflowCompatibility(True, ("compatible",))


__all__ = ["WorkflowRegistry", "WorkflowCompatibility"]
