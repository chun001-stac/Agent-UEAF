"""RAG 检索层的向量后端 SPI + 内存实现。

``VectorBackend`` 是混合检索器（RAG-009）和索引流水线使用的 SPI。集合按
(tenant, purpose) 隔离，因此一个 tenant/purpose 的候选不会泄漏到另一个；
``search`` 接收 ``RetrievalConstraint``，使后端能在不扩大范围的前提下将候选
限定到授权来源集合（RAG-009）。

内存后端遵循 ``RetrievalIndex`` 的删除语义（RAG-008）：来源一旦被删除，
绝不会重新进入生产检索。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from ueaf.rag.index import Chunk
from ueaf.rag.retrieval import RetrievalConstraint, RetrievalResult


class VectorBackend(Protocol):
    """RAG 检索层使用的向量存储 SPI。

    ``upsert`` 将 ``chunks`` 与其 ``vectors``（对齐的序列）持久化，并返回已确认的
    分块。``search`` 返回限定在授权集合内的排序 ``RetrievalResult``。``delete``
    移除 ``source_ref`` 的每个分块，并返回被移除的数量（RAG-008）。
    """

    def upsert(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> tuple[Chunk, ...]: ...

    def search(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        filter: RetrievalConstraint,
    ) -> tuple[RetrievalResult, ...]: ...

    def delete(self, source_ref: str) -> int: ...


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """显式处理零向量的余弦相似度。"""
    if len(a) != len(b):
        raise ValueError("vector dimensions differ")
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryVectorBackend:
    """用于测试/本地开发的确定性内存 ``VectorBackend``。

    遵循 RAG-008：已删除的来源会从召回中移除，且重新 upsert 已删除的来源会被忽略
    （与 ``RetrievalIndex`` 保持一致）。
    """

    def __init__(self) -> None:
        self._points: dict[str, tuple[Chunk, tuple[float, ...]]] = {}
        self._deleted_sources: set[str] = set()

    def upsert(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> tuple[Chunk, ...]:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have equal length")
        accepted: list[Chunk] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if chunk.source_ref in self._deleted_sources:
                continue
            self._points[chunk.chunk_id] = (chunk, tuple(vector))
            accepted.append(chunk)
        return tuple(accepted)

    def search(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        filter: RetrievalConstraint,
    ) -> tuple[RetrievalResult, ...]:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        allowlist = frozenset(filter.source_allowlist)
        scored: list[tuple[float, Chunk]] = []
        for chunk, vector in self._points.values():
            if chunk.source_ref in self._deleted_sources:
                continue
            if allowlist and chunk.source_ref not in allowlist:
                continue
            scored.append((cosine_similarity(query_vector, vector), chunk))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return tuple(
            RetrievalResult(chunk=chunk, score=score, degraded=False)
            for score, chunk in scored[:top_k]
        )

    def delete(self, source_ref: str) -> int:
        self._deleted_sources.add(source_ref)
        removed = [
            chunk_id
            for chunk_id, (chunk, _) in self._points.items()
            if chunk.source_ref == source_ref
        ]
        for chunk_id in removed:
            del self._points[chunk_id]
        return len(removed)


__all__ = [
    "VectorBackend",
    "InMemoryVectorBackend",
    "cosine_similarity",
]
