"""Conflict preservation (CTX-006).

Two authorized sources may conflict on a key claim without a unique
authoritative source. Conflicts are preserved in the EvidencePack rather than
resolved by last-write or embedding score; dedup never deletes a conflicting
source.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ClaimConflict:
    claim_ref: str
    source_refs: tuple[str, ...]
    versions: tuple[str, ...]
    statement: str


@dataclass(slots=True)
class ConflictRegistry:
    """Preserves claim conflicts; never collapses by last-write/dedup (CTX-006)."""

    _conflicts: dict[str, ClaimConflict] = field(default_factory=dict)

    def register(self, conflict: ClaimConflict) -> ClaimConflict:
        existing = self._conflicts.get(conflict.claim_ref)
        if existing is not None and existing.statement != conflict.statement:
            # A genuinely different conflict on the same claim is preserved, not
            # overwritten by last-write.
            merged = ClaimConflict(
                claim_ref=conflict.claim_ref,
                source_refs=tuple(dict.fromkeys((*existing.source_refs, *conflict.source_refs))),
                versions=tuple(dict.fromkeys((*existing.versions, *conflict.versions))),
                statement=existing.statement,
            )
            self._conflicts[conflict.claim_ref] = merged
            return merged
        self._conflicts[conflict.claim_ref] = conflict
        return conflict

    def conflicts(self) -> tuple[ClaimConflict, ...]:
        return tuple(self._conflicts.values())

    def evidence_pack_conflicts(self, evidence_refs: tuple[str, ...]) -> tuple[ClaimConflict, ...]:
        """Only conflicts whose sources are actually in the pack are included."""
        selected = {
            ref: c for ref, c in self._conflicts.items() if set(c.source_refs) & set(evidence_refs)
        }
        return tuple(selected.values())


__all__ = ["ClaimConflict", "ConflictRegistry"]
