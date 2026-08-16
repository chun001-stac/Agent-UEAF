"""混合检索测试：RRF 融合、降级兜底、授权、删除。

RAG-008 已删除来源消失：删除后，向量通道永远不会召回旧分块，混合结果对其为空。
RAG-009 授权混合检索：即使向量后端返回未授权候选，融合结果也绝不会超出授权
来源集合，且融合是确定性的。
RAG-010 降级词法兜底：没有嵌入器/向量后端——或向量通道在查询时失败——检索器
都会在授权集合内降级为仅词法检索，并显式标记 degraded/coverage gap。
"""

from __future__ import annotations

import pytest

from ueaf.infrastructure.vector import InMemoryVectorBackend, cosine_similarity
from ueaf.rag.embedding import DeterministicHashEmbedding
from ueaf.rag.hybrid import DEGRADED_COVERAGE_GAP, HybridRetriever
from ueaf.rag.index import Chunk, RetrievalIndex
from ueaf.rag.retrieval import (
    AuthorizedRetrieval,
    RetrievalConstraint,
    RetrievalResult,
)

_EMBEDDER = DeterministicHashEmbedding()


def _chunk(text: str, *, chunk_id: str, source: str, locator: str = "doc") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_ref=source,
        source_version="1.0.0",
        text=text,
        locator=locator,
    )


def _constraint(*, sources: tuple[str, ...]) -> RetrievalConstraint:
    return RetrievalConstraint(
        tenant_id="tenant-demo", purpose="research", source_allowlist=sources
    )


def _index(chunks: tuple[Chunk, ...]) -> RetrievalIndex:
    index = RetrievalIndex()
    for chunk in chunks:
        index.add(chunk)
    return index


class _ExplodingVectorBackend:
    """在查询时失败的向量后端（RAG-010 向量通道失败）。"""

    def upsert(
        self,
        chunks: tuple[Chunk, ...],
        vectors: tuple[tuple[float, ...], ...],
    ) -> tuple[Chunk, ...]:
        return chunks

    def search(
        self,
        query_vector: tuple[float, ...],
        *,
        top_k: int,
        filter: RetrievalConstraint,
    ) -> tuple[RetrievalResult, ...]:
        del query_vector, top_k, filter
        raise RuntimeError("向量后端不可用")

    def delete(self, source_ref: str) -> int:
        del source_ref
        return 0


class _UnfilteredVectorBackend(InMemoryVectorBackend):
    """忽略约束的内存后端——用于验证混合检索器自身的授权守卫
    （RAG-009 纵深防御）。"""

    def search(
        self,
        query_vector: tuple[float, ...],
        *,
        top_k: int,
        filter: RetrievalConstraint,
    ) -> tuple[RetrievalResult, ...]:
        del filter
        scored: list[tuple[float, Chunk]] = []
        for chunk, vector in self._points.values():
            if chunk.source_ref in self._deleted_sources:
                continue
            scored.append((cosine_similarity(query_vector, vector), chunk))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return tuple(RetrievalResult(chunk=chunk, score=score) for score, chunk in scored[:top_k])


@pytest.mark.test_id("RAG-009")
def test_hybrid_fusion_ranks_chunks_present_in_both_legs_first() -> None:
    orders = _chunk("orders reconciliation", chunk_id="c:orders", source="source:orders")
    revenue = _chunk("revenue forecast", chunk_id="c:revenue", source="source:orders")
    index = _index((orders, revenue))
    backend = InMemoryVectorBackend()
    backend.upsert((orders, revenue), _EMBEDDER.embed((orders.text, revenue.text)))
    retriever = HybridRetriever(
        lexical=AuthorizedRetrieval(sources=("source:orders",)),
        vector=backend,
        embedder=_EMBEDDER,
        sources=("source:orders",),
        top_k=8,
    )
    results = retriever.search(
        index, query="orders", constraint=_constraint(sources=("source:orders",))
    )
    assert results
    assert results[0].chunk.chunk_id == "c:orders"
    assert all(result.chunk.source_ref == "source:orders" for result in results)
    # RRF 分数在多次调用间递减且确定。
    scores = [result.score for result in results]
    assert scores == sorted(scores, reverse=True)
    assert (
        retriever.search(index, query="orders", constraint=_constraint(sources=("source:orders",)))
        == results
    )


@pytest.mark.test_id("RAG-010")
def test_hybrid_degrades_to_lexical_without_embedder() -> None:
    orders = _chunk("orders reconciliation", chunk_id="c:orders", source="source:orders")
    index = _index((orders,))
    retriever = HybridRetriever(
        lexical=AuthorizedRetrieval(sources=("source:orders",)),
        vector=None,
        embedder=None,
        sources=("source:orders",),
    )
    results = retriever.search(
        index, query="orders", constraint=_constraint(sources=("source:orders",))
    )
    assert results
    assert results[0].chunk.chunk_id == "c:orders"
    assert all(result.degraded for result in results)
    assert results[0].coverage_gap == DEGRADED_COVERAGE_GAP
    # 降级检索绝不超出授权集合。
    assert all(result.chunk.source_ref == "source:orders" for result in results)


@pytest.mark.test_id("RAG-010")
def test_hybrid_degrades_when_vector_backend_fails_at_query_time() -> None:
    orders = _chunk("orders reconciliation", chunk_id="c:orders", source="source:orders")
    index = _index((orders,))
    retriever = HybridRetriever(
        lexical=AuthorizedRetrieval(sources=("source:orders",)),
        vector=_ExplodingVectorBackend(),
        embedder=_EMBEDDER,
        sources=("source:orders",),
    )
    results = retriever.search(
        index, query="orders", constraint=_constraint(sources=("source:orders",))
    )
    # 词法通道仍在授权集合内提供服务，并显式标记降级。
    assert results
    assert all(result.degraded for result in results)
    assert results[0].coverage_gap == DEGRADED_COVERAGE_GAP
    assert all(result.chunk.source_ref == "source:orders" for result in results)


@pytest.mark.test_id("RAG-009")
def test_hybrid_never_recalls_beyond_authorized_set() -> None:
    orders = _chunk("orders reconciliation", chunk_id="c:orders", source="source:orders")
    secret = _chunk("secret admin notes", chunk_id="c:secret", source="source:admin")
    index = _index((orders, secret))
    backend = _UnfilteredVectorBackend()
    backend.upsert((orders, secret), _EMBEDDER.embed((orders.text, secret.text)))
    retriever = HybridRetriever(
        lexical=AuthorizedRetrieval(sources=("source:orders",)),
        vector=backend,
        embedder=_EMBEDDER,
        sources=("source:orders",),
    )
    # 向量通道本会先返回 source:admin，但授权集合将其排除在混合结果之外
    # （RAG-009 纵深防御）。
    results = retriever.search(
        index, query="secret admin notes", constraint=_constraint(sources=("source:orders",))
    )
    assert all(result.chunk.source_ref == "source:orders" for result in results)
    assert not any(result.chunk.chunk_id == "c:secret" for result in results)


@pytest.mark.test_id("RAG-008")
def test_deleted_source_is_not_recalled_by_hybrid() -> None:
    orders = _chunk("orders reconciliation", chunk_id="c:orders", source="source:orders")
    index = _index((orders,))
    backend = InMemoryVectorBackend()
    backend.upsert((orders,), _EMBEDDER.embed((orders.text,)))
    retriever = HybridRetriever(
        lexical=AuthorizedRetrieval(sources=("source:orders",)),
        vector=backend,
        embedder=_EMBEDDER,
        sources=("source:orders",),
    )
    constraint = _constraint(sources=("source:orders",))
    assert retriever.search(index, query="orders", constraint=constraint)

    # 删除会同步到两个通道（RAG-008）。
    backend.delete("source:orders")
    index.delete_source("source:orders")
    assert retriever.search(index, query="orders", constraint=constraint) == ()

    # 已删除的来源绝不会重新进入生产检索。
    backend.upsert((orders,), _EMBEDDER.embed((orders.text,)))
    index.add(orders)
    assert retriever.search(index, query="orders", constraint=constraint) == ()
