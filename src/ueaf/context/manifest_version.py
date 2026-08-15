"""Manifest rebuild on authority change (CTX-007).

A ContextManifest is rebuilt (not incrementally patched) when any authority
input changes: principal/delegation, purpose, TaskState, ACL, selected source
versions, memory validity, budget or route requirement. ``ManifestVersionKey``
derives a stable key from those inputs; a changed key means a rebuild is
required.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import sha256_hex


@dataclass(frozen=True, slots=True)
class ManifestVersionKey:
    """Stable version key over the authority inputs that force a rebuild."""

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
    """Any authority-input change forces a manifest rebuild (CTX-007)."""
    return current.differs_from(authority)


__all__ = ["ManifestVersionKey", "rebuild_required"]
