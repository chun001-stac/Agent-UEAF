"""权威变更时重建清单（CTX-007）。

当任一权威输入发生变化时，ContextManifest 都会重建（而非增量修补）：主体/委托、目的、
TaskState、ACL、所选来源版本、记忆有效性、预算或路由要求。``ManifestVersionKey`` 从这些
输入推导出稳定键；键发生变化即表示需要重建。
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import sha256_hex


@dataclass(frozen=True, slots=True)
class ManifestVersionKey:
    """基于强制重建的权威输入之上的稳定版本键。"""

    principal_ref: str
    delegation_scope_ref: str
    purpose: str
    task_state_ref: str
    acl_ref: str
    source_versions_ref: str
    memory_validity_ref: str
    budget_ref: str
    route_requirement_ref: str

    @property
    def version(self) -> str:
        return sha256_hex(
            "|".join(
                [
                    self.principal_ref,
                    self.delegation_scope_ref,
                    self.purpose,
                    self.task_state_ref,
                    self.acl_ref,
                    self.source_versions_ref,
                    self.memory_validity_ref,
                    self.budget_ref,
                    self.route_requirement_ref,
                ]
            )
        )

    def differs_from(self, other: ManifestVersionKey) -> bool:
        return self.version != other.version


def rebuild_required(current: ManifestVersionKey, authority: ManifestVersionKey) -> bool:
    """任何权威输入的变化都会强制重建清单（CTX-007）。"""
    return current.differs_from(authority)


__all__ = ["ManifestVersionKey", "rebuild_required"]
