"""MCP tool metadata is discovery-only; it never changes risk/approval/policy (SEC-012).

An MCP tool description may claim ``safe``, ``no approval`` or
``admin-approved``. Those claims are discovery metadata only: UEAF risk
classification, approval requirements and policy decisions are owned by the
PDP, never by MCP self-description.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MCPToolMetadata:
    """Discovery metadata parsed from an MCP tool description (SEC-012)."""

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
    """MCP claims never bind: risk/approval/policy stay with UEAF (SEC-012)."""
    return True


__all__ = ["MCPToolMetadata", "is_discovery_claim_only"]
