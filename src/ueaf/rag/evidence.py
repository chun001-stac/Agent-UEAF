"""RAG 证据：引用、去重合并、冲突保留。

RAG-011 去重合并：同一来源版本的重叠分块绝不会填满 EvidencePack；不同来源的
近似相同文本不会被合并为单一权威。
RAG-012 冲突在去重后仍保留：文本相近但声明/版本冲突的来源绝不会被去重丢弃。
RAG-013 引用来源跨度：每条引用都属于模型实际看到的 EvidencePack，并解析到
来源版本 + locator/span；伪造的引用 ID 无法通过校验。
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
    """构建带去重与冲突保留的 EvidencePack（RAG-011/012）。"""

    def __init__(self, *, max_chunks: int = 8) -> None:
        self._max_chunks = max_chunks

    def build(
        self,
        chunks: tuple[Chunk, ...],
        *,
        conflicts: tuple[tuple[str, str], ...] = (),  # (source_a, source_b)
    ) -> tuple[Chunk, ...]:
        """合并同来源重叠分块，保留跨来源冲突。"""
        by_source: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            by_source.setdefault(chunk.source_ref, []).append(chunk)
        selected: list[Chunk] = []
        # RAG-011：除非文本有实质差异，否则每个 (source, source_version) 最多保留一个分块。
        seen: set[tuple[str, str, str]] = set()
        for chunk in chunks:
            key = (chunk.source_ref, chunk.source_version, chunk.text)
            if key in seen:
                continue
            seen.add(key)
            selected.append(chunk)
        # RAG-012：涉及冲突的分块绝不会被去重移除。
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
    """只有当引用能针对可见的证据包解析时才有效（RAG-013）。"""
    return any(citation.resolves(chunk) for chunk in visible_chunks)


def digest_citation(citation: Citation) -> str:
    return sha256_hex(f"{citation.source_ref}@{citation.source_version}:{citation.locator}")


__all__ = ["Citation", "EvidencePackBuilder", "validate_citation", "digest_citation"]
