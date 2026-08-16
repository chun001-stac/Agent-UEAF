"""MCP 工具元数据仅供发现，绝不影响风险/审批/策略（SEC-012）。

MCP 工具描述可能声称 ``safe``、``no approval`` 或 ``admin-approved``。这些声明仅属于
发现元数据：UEAF 的风险分级、审批要求与策略判定由 PDP 拥有，绝不取决于 MCP 的
自我描述。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MCPToolMetadata:
    """从 MCP 工具描述中解析出的发现元数据（SEC-012）。"""

    tool_name: str
    description: str
    claims_safe: bool = False
    claims_no_approval: bool = False
    claims_admin_approved: bool = False

    @classmethod
    def from_description(cls, tool_name: str, description: str) -> MCPToolMetadata:
        lowered = description.lower()
        return cls(
            tool_name=tool_name,
            description=description,
            claims_safe="safe" in lowered or "read-only" in lowered,
            claims_no_approval="no approval" in lowered or "no-approval" in lowered,
            claims_admin_approved="admin-approved" in lowered
            or "admin approved" in lowered,
        )

    @property
    def any_authorization_claim(self) -> bool:
        return self.claims_safe or self.claims_no_approval or self.claims_admin_approved


def is_discovery_claim_only(metadata: MCPToolMetadata) -> bool:
    """MCP 声明不具约束力：风险/审批/策略仍由 UEAF 决定（SEC-012）。"""
    return True


__all__ = ["MCPToolMetadata", "is_discovery_claim_only"]
