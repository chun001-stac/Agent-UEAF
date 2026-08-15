"""Workflow Registry (functional module 06).

Manages workflow Definitions, schemas, owners, compatibility and publication.
A run instance binds an immutable Definition version; a newer compatible
definition never silently rewrites an in-flight run.
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
    """Immutable registry of workflow definitions by (id, version)."""

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
