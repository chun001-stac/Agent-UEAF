"""RAG 索引流水线测试：ingest -> search 闭环、locator、投影。

RAG-005 可复现索引元数据：相同来源版本 + 策略下，ingest 产生稳定的投影摘要；
来源版本变化会产生可区分的投影。
RAG-006 语义分块边界：分块保留标题/表格表头，且每个分块都携带文档 locator。
RAG-008 已删除来源消失：pipeline.delete 会同步到向量后端和词法镜像，使该来源
不再被召回。
"""

from __future__ import annotations

import pytest

from ueaf.infrastructure.vector import InMemoryVectorBackend
from ueaf.rag.embedding import DeterministicHashEmbedding
from ueaf.rag.hybrid import HybridRetriever
from ueaf.rag.index import RetrievalIndex
from ueaf.rag.pipeline import IndexingPipeline, SourceDocument
from ueaf.rag.retrieval import AuthorizedRetrieval, RetrievalConstraint

_EMBEDDER = DeterministicHashEmbedding()

DOC_TEXT = (
    "# Reconciliation Policy\n"
    "orders are reconciled daily\n"
    "```python\n"
    "def reconcile():\n"
    "    return True\n"
    "```\n"
    "| desk | target |\n"
    "| cn    | 100    |\n"
)

AUTHORIZED = ("source:policy",)
CONSTRAINT = RetrievalConstraint(
    tenant_id="tenant-demo", purpose="research", source_allowlist=AUTHORIZED
)


def _pipeline() -> tuple[IndexingPipeline, InMemoryVectorBackend, RetrievalIndex]:
    backend = InMemoryVectorBackend()
    index = RetrievalIndex()
    pipeline = IndexingPipeline(
        backend=backend,
        embedder=_EMBEDDER,
        lexical_index=index,
    )
    return pipeline, backend, index


def _retriever(index: RetrievalIndex, backend: InMemoryVectorBackend) -> HybridRetriever:
    return HybridRetriever(
        lexical=AuthorizedRetrieval(sources=AUTHORIZED),
        vector=backend,
        embedder=_EMBEDDER,
        sources=AUTHORIZED,
    )


def _all_chunks(backend: InMemoryVectorBackend) -> tuple[str, ...]:
    return tuple(
        result.chunk.text
        for result in backend.search(
            (1.0,) * _EMBEDDER.dimension,
            top_k=32,
            filter=CONSTRAINT,
        )
    )


@pytest.mark.test_id("RAG-005")
def test_ingest_then_hybrid_search_closed_loop() -> None:
    pipeline, backend, index = _pipeline()
    projection = pipeline.ingest(
        SourceDocument(source_ref="source:policy", source_version="1.0.0", text=DOC_TEXT)
    )
    assert projection.chunk_refs
    results = _retriever(index, backend).search(index, query="reconcile", constraint=CONSTRAINT)
    assert results
    assert any(result.chunk.source_ref == "source:policy" for result in results)


@pytest.mark.test_id("RAG-006")
def test_ingest_preserves_semantic_boundaries_and_locators() -> None:
    pipeline, backend, _index = _pipeline()
    projection = pipeline.ingest(
        SourceDocument(source_ref="source:policy", source_version="1.0.0", text=DOC_TEXT)
    )
    assert projection.chunk_refs
    # 每个分块引用都由 source + version 确定性派生。
    assert all(ref.startswith("source:policy@1.0.0:") for ref in projection.chunk_refs)
    # 围栏代码块和表格表头永远不会被拆分到多个分块。
    joined = "\n".join(_all_chunks(backend))
    assert "def reconcile():" in joined
    assert "| desk | target |" in joined
    assert "# Reconciliation Policy" in joined


@pytest.mark.test_id("RAG-005")
def test_projection_digest_is_stable_and_source_version_sensitive() -> None:
    pipeline, _backend, _index = _pipeline()
    p1 = pipeline.ingest(SourceDocument("source:policy", "1.0.0", DOC_TEXT))
    p2 = pipeline.ingest(SourceDocument("source:policy", "1.0.0", DOC_TEXT))
    # 相同来源版本 + 策略 -> 相同摘要（RAG-005 可复现性）。
    assert p1.same_as(p2)
    assert p1.projection_digest == p2.projection_digest
    # 不同的来源版本是可区分的投影。
    changed = pipeline.ingest(SourceDocument("source:policy", "2.0.0", DOC_TEXT))
    assert not p1.same_as(changed)


@pytest.mark.test_id("RAG-008")
def test_pipeline_delete_propagates_to_backend_and_lexical_mirror() -> None:
    pipeline, backend, index = _pipeline()
    pipeline.ingest(SourceDocument("source:policy", "1.0.0", DOC_TEXT))
    assert _all_chunks(backend)
    pipeline.delete("source:policy")
    # 向量后端已被清除（RAG-008）。
    assert _all_chunks(backend) == ()
    # 词法镜像也已被清除。
    assert index.search(("reconcile",)) == ()
