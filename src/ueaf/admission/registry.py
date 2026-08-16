"""Agent / 能力定义注册表（核心规范 01 §8.1-8.2）。

``AgentDefinition`` 与 ``CapabilityDescriptor`` 是不可变的版本化定义；能力可被发现
绝不等于已获授权。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from ueaf.common.meta import ContractMeta

RiskClass = Literal["compute_only", "read_only", "reversible_write", "high_risk_write"]


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """不可变的 agent 定义；任何行为变更都会提升版本号。"""

    meta: ContractMeta
    agent_id: str
    agent_version: str
    owner: str
    purpose: str
    input_contract_ref: str
    output_contract_ref: str
    completion_contract_ref: str
    runtime_profile: str
    capability_refs: tuple[str, ...]
    prompt_contract_ref: str
    policy_refs: tuple[str, ...]
    risk_class: RiskClass
    budget_defaults: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.agent_id != self.meta.object_id:
            raise ValueError("AgentDefinition.meta.object_id must equal agent_id")
        if not self.agent_version:
            raise ValueError("AgentDefinition.agent_version must not be empty")


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """可被发现的能力；绝不携带单次调用的授权结果。"""

    meta: ContractMeta
    capability_id: str
    capability_version: str
    kind: str
    input_schema_ref: str
    output_schema_ref: str
    risk_class: RiskClass
    side_effect_class: Literal["none", "read", "reversible_write", "high_risk_write"]
    auth_requirements: tuple[str, ...]
    idempotency_support: bool
    timeout_ms: int
    lifecycle_status: Literal["active", "deprecated", "disabled"]

    def __post_init__(self) -> None:
        if self.capability_id != self.meta.object_id:
            raise ValueError("CapabilityDescriptor.meta.object_id must equal capability_id")


@dataclass(slots=True)
class DefinitionRegistry:
    """agent/能力定义的不可变注册表。"""

    _agents: dict[tuple[str, str], AgentDefinition] = field(default_factory=dict)
    _capabilities: dict[tuple[str, str], CapabilityDescriptor] = field(default_factory=dict)

    def register_agent(self, definition: AgentDefinition) -> AgentDefinition:
        key = (definition.agent_id, definition.agent_version)
        if key in self._agents:
            raise ValueError(f"AgentDefinition {key} already registered")
        self._agents[key] = definition
        return definition

    def get_agent(self, agent_id: str, agent_version: str) -> AgentDefinition | None:
        return self._agents.get((agent_id, agent_version))

    def register_capability(self, capability: CapabilityDescriptor) -> CapabilityDescriptor:
        key = (capability.capability_id, capability.capability_version)
        if key in self._capabilities:
            raise ValueError(f"CapabilityDescriptor {key} already registered")
        self._capabilities[key] = capability
        return capability

    def get_capability(
        self, capability_id: str, capability_version: str
    ) -> CapabilityDescriptor | None:
        return self._capabilities.get((capability_id, capability_version))

    def requires_capabilities(self, agent: AgentDefinition) -> list[CapabilityDescriptor]:
        """解析 agent 所需的能力集合（缺失 -> []）。"""
        resolved: list[CapabilityDescriptor] = []
        for ref in agent.capability_refs:
            cid, _, cver = ref.partition("@")
            capability = self.get_capability(cid, cver or "1.0.0")
            if capability is not None:
                resolved.append(capability)
        return resolved
