"""混合检索：授权词法 + 向量融合，降级兜底。

RAG-009 授权混合检索：词法（``AuthorizedRetrieval``）与向量（``VectorBackend``）
候选通过倒数排名融合（RRF）确定性融合，并且绝不会超出授权来源集合——即使后端
没有过滤，混合层也会再次对向量结果进行过滤。
RAG-010 降级词法兜底：当嵌入器或向量后端不可用（或在查询时失败）时，检索在
授权集合内降级为仅词法检索，并显式标记 degraded/coverage gap。来源集合
绝不会扩大。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ueaf.rag.embedding import EmbeddingProvider
from ueaf.rag.index import Chunk, RetrievalIndex
from ueaf.rag.retrieval import (
    AuthorizedRetrieval,
    RetrievalConstraint,
    RetrievalResult,
)

if TYPE_CHECKING:
    # 仅在类型注解中使用：若在此处运行时导入 VectorBackend 会造成循环导入
    # （vector -> rag.index -> rag 包再导出 -> rag.hybrid -> vector）。
    from ueaf.infrastructure.vector import VectorBackend

DEFAULT_RRF_K = 60
DEGRADED_COVERAGE_GAP = "embedding_unavailable:lexical_fallback_within_authorized_set"


@dataclass(frozen=True, slots=True)
class HybridQuery:
    """混合检索的派生查询计划（非持久化的规范对象）。"""

    query: str
    terms: tuple[str, ...] = ()


class HybridRetriever:
    """授权词法 + 向量检索的确定性 RRF 融合。

    当 ``constraint.source_allowlist`` 为空时，``sources`` 是用于限定向量结果的授权
    来源集合；它必须与 ``AuthorizedRetrieval`` 配置的来源一致（RAG-009）。
    """

    def __init__(
        self,
        *,
        lexical: AuthorizedRetrieval,
        vector: VectorBackend | None = None,
        embedder: EmbeddingProvider | None = None,
        sources: tuple[str, ...] = (),
        rrf_k: int = DEFAULT_RRF_K,
        top_k: int = 8,
    ) -> None:
        if rrf_k < 1:
            raise ValueError("rrf_k must be >= 1")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        self._lexical = lexical
        self._vector = vector
        self._embedder = embedder
        self._sources = frozenset(sources)
        self._rrf_k = rrf_k
        self._top_k = top_k

    def search(
        self,
        index: RetrievalIndex,
        *,
        query: str,
        constraint: RetrievalConstraint,
        terms: tuple[str, ...] | None = None,
    ) -> tuple[RetrievalResult, ...]:
        search_terms = terms or (query,)
        query_vector, embedding_available = self._embed_query(query)

        # RAG-009/010：词法通道始终限定在授权集合内。
        lexical_results = self._lexical.search(
            index,
            terms=search_terms,
            constraint=constraint,
            embedding_available=embedding_available,
        )

        vector_results: tuple[RetrievalResult, ...] = ()
        degraded = not embedding_available
        if embedding_available and query_vector is not None and self._vector is not None:
            try:
                vector_results = self._vector.search(
                    query_vector, top_k=self._top_k, filter=constraint
                )
            except Exception:
                # 向量通道失败时降级为仅词法检索（RAG-010）。
                vector_results = ()
                degraded = True
            else:
                # 纵深防御（RAG-009）：即使后端返回了多余候选，也绝不超出授权集合召回。
                allowlist = frozenset(constraint.source_allowlist) or self._sources
                vector_results = tuple(
                    result for result in vector_results if result.chunk.source_ref in allowlist
                )

        fused = self._fuse(lexical_results, vector_results, k=self._rrf_k)
        coverage_gap = DEGRADED_COVERAGE_GAP if degraded else None
        return tuple(
            RetrievalResult(
                chunk=chunk,
                score=score,
                degraded=degraded,
                coverage_gap=coverage_gap,
            )
            for chunk, score in fused[: self._top_k]
        )

    def _embed_query(self, query: str) -> tuple[tuple[float, ...] | None, bool]:
        if self._embedder is None or self._vector is None:
            return None, False
        try:
            return self._embedder.embed((query,))[0], True
        except Exception:
            # 任何嵌入失败都降级为词法兜底（RAG-010）。
            return None, False

    @staticmethod
    def _fuse(
        lexical: tuple[RetrievalResult, ...],
        vector: tuple[RetrievalResult, ...],
        *,
        k: int,
    ) -> list[tuple[Chunk, float]]:
        """倒数排名融合：确定性，无需分数归一化。"""
        scores: dict[str, float] = defaultdict(float)
        chunks: dict[str, Chunk] = {}
        for rank, result in enumerate(lexical, start=1):
            chunk_id = result.chunk.chunk_id
            scores[chunk_id] += 1.0 / (k + rank)
            chunks[chunk_id] = result.chunk
        for rank, result in enumerate(vector, start=1):
            chunk_id = result.chunk.chunk_id
            scores[chunk_id] += 1.0 / (k + rank)
            chunks[chunk_id] = result.chunk
        ordered = sorted(chunks, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        return [(chunks[chunk_id], scores[chunk_id]) for chunk_id in ordered]


__all__ = [
    "HybridQuery",
    "HybridRetriever",
    "DEFAULT_RRF_K",
    "DEGRADED_COVERAGE_GAP",
]
