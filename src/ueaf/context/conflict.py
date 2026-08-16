"""冲突保留（CTX-006）。

两个已授权的来源可能在某个关键主张上冲突，而没有一个唯一的权威来源。冲突会保留在
EvidencePack 中，而不是通过后写优先或嵌入得分来消解；去重绝不会删除存在冲突的来源。
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
    """保留主张冲突；绝不由后写/去重来消解（CTX-006）。"""

    _conflicts: dict[str, ClaimConflict] = field(default_factory=dict)

    def register(self, conflict: ClaimConflict) -> ClaimConflict:
        existing = self._conflicts.get(conflict.claim_ref)
        if existing is not None and existing.statement != conflict.statement:
            # 同一主张上真正不同的冲突会被保留，而不会被后写覆盖。
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
        """仅包含来源确实在包中的冲突。"""
        selected = {
            ref: c for ref, c in self._conflicts.items() if set(c.source_refs) & set(evidence_refs)
        }
        return tuple(selected.values())


__all__ = ["ClaimConflict", "ConflictRegistry"]
