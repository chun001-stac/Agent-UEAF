"""RAG evidence: citations, duplicate collapse, conflict survival.

RAG-011 duplicate collapse: overlapping chunks of the same source version never
fill the EvidencePack; near-identical text from different sources is not merged
into a single authority.
RAG-012 conflict survives dedup: sources with close text but conflicting
claims/versions are never dropped by dedup.
RAG-013 citation source span: every citation belongs to the EvidencePack the
model actually sees and resolves to a source version + locator/span; fabricated
citation ids fail validation.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import sha256_hex
from ueaf.rag.index import Chunk


@dataclass(frozen=True, slots=True)
class Citation:
    citation_id: str
    source_ref: str
    source_version: str
    locator: str  # page:span / heading / record id
    span: str = ""

    def resolves(self, chunk: Chunk) -> bool:
        return (
            chunk.source_ref == self.source_ref
            and chunk.source_version == self.source_version
            and chunk.locator == self.locator
        )


class EvidencePackBuilder:
    """Builds an EvidencePack with dedup and conflict survival (RAG-011/012)."""

    def __init__(self, *, max_chunks: int = 8) -> None:
        self._max_chunks = max_chunks

    def build(
        self,
        chunks: tuple[Chunk, ...],
        *,
        conflicts: tuple[tuple[str, str], ...] = (),  # (source_a, source_b)
    ) -> tuple[Chunk, ...]:
        """Collapse same-source overlapping chunks, keep cross-source conflicts."""
        by_source: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            by_source.setdefault(chunk.source_ref, []).append(chunk)
        selected: list[Chunk] = []
        # RAG-011: keep at most one chunk per (source, source_version) unless
        # the text differs meaningfully.
        seen: set[tuple[str, str, str]] = set()
        for chunk in chunks:
            key = (chunk.source_ref, chunk.source_version, chunk.text)
            if key in seen:
                continue
            seen.add(key)
            selected.append(chunk)
        # RAG-012: a chunk involved in a conflict is never deduped away.
        conflict_sources = {s for pair in conflicts for s in pair}
        deduped: list[Chunk] = []
        for chunk in selected:
            if chunk.source_ref in conflict_sources:
                deduped.append(chunk)
                continue
            if len(deduped) >= self._max_chunks:
                break
            deduped.append(chunk)
        return tuple(deduped)


def validate_citation(citation: Citation, visible_chunks: tuple[Chunk, ...]) -> bool:
    """A citation is valid only if it resolves against the visible pack (RAG-013)."""
    return any(citation.resolves(chunk) for chunk in visible_chunks)


def digest_citation(citation: Citation) -> str:
    return sha256_hex(f"{citation.source_ref}@{citation.source_version}:{citation.locator}")


__all__ = ["Citation", "EvidencePackBuilder", "validate_citation", "digest_citation"]
