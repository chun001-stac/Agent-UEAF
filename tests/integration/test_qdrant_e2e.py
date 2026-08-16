"""向量后端的 Qdrant 端到端集成测试。

覆盖真实 Qdrant 路径：按 (tenant, purpose) 的集合隔离、upsert/search/delete 往返，
以及 RAG-008 删除语义。当 ``qdrant-client`` 不可用或在 ``UEAF_QDRANT_URL``
（默认 ``http://127.0.0.1:6333``）无法访问 Qdrant 时跳过——没有 docker 服务的 CI
会干净地跳过。
"""

from __future__ import annotations

import os
import socket

import pytest

from ueaf.infrastructure.vector.qdrant_backend import QdrantBackend
from ueaf.rag.embedding import DeterministicHashEmbedding
from ueaf.rag.index import Chunk
from ueaf.rag.retrieval import RetrievalConstraint

QDRANT_URL = os.environ.get("UEAF_QDRANT_URL", "http://127.0.0.1:6333")


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def _qdrant_available() -> bool:
    try:
        import qdrant_client  # noqa: F401
    except ImportError:
        return False
    return True


requires_qdrant = pytest.mark.skipif(
    not _qdrant_available() or not _port_open("127.0.0.1", 6333),
    reason="需要 qdrant-client 且可访问的 Qdrant（docker compose up -d qdrant）",
)


def _chunk(text: str, *, chunk_id: str, source: str, locator: str = "doc") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_ref=source,
        source_version="1.0.0",
        text=text,
        locator=locator,
    )


def _constraint(sources: tuple[str, ...]) -> RetrievalConstraint:
    return RetrievalConstraint(tenant_id="tenant-e2e", purpose="p", source_allowlist=sources)


@requires_qdrant
@pytest.mark.test_id("RAG-008")
def test_qdrant_upsert_search_delete_roundtrip() -> None:
    # 每次运行使用唯一集合：(tenant, purpose) 隔离可避免并行执行和重跑之间相互污染。
    backend = QdrantBackend(tenant_id="tenant-e2e", purpose=f"e2e-{os.getpid()}", url=QDRANT_URL)
    embedder = DeterministicHashEmbedding()
    orders = _chunk("orders reconciliation", chunk_id="c:orders", source="source:orders")
    secret = _chunk("secret admin notes", chunk_id="c:secret", source="source:admin")
    chunks = (orders, secret)
    vectors = embedder.embed(tuple(chunk.text for chunk in chunks))
    backend.upsert(chunks, vectors)

    try:
        # 搜索仅在来源白名单内召回最相似的分块。
        query_vector = embedder.embed(("orders reconciliation",))[0]
        results = backend.search(query_vector, top_k=4, filter=_constraint(("source:orders",)))
        assert any(result.chunk.chunk_id == "c:orders" for result in results)
        assert all(result.chunk.source_ref == "source:orders" for result in results)
        # payload 往返携带了规范的 Chunk 字段。
        hit = next(result for result in results if result.chunk.chunk_id == "c:orders")
        assert hit.chunk.text == "orders reconciliation"
        assert hit.chunk.source_version == "1.0.0"
        assert hit.chunk.locator == "doc"

        # RAG-008：删除来源会将其从召回中移除。
        assert backend.delete("source:orders") > 0
        after = backend.search(query_vector, top_k=4, filter=_constraint(("source:orders",)))
        assert all(result.chunk.chunk_id != "c:orders" for result in after)
    finally:
        backend.delete("source:admin")
        backend.delete_collection()


@requires_qdrant
@pytest.mark.test_id("RAG-009")
def test_qdrant_collections_are_isolated_by_tenant_and_purpose() -> None:
    embedder = DeterministicHashEmbedding()
    chunk_a = _chunk("revenue forecast", chunk_id="c:a", source="source:fin")
    chunk_b = _chunk("orders reconciliation", chunk_id="c:b", source="source:ops")
    tenant_a = QdrantBackend(tenant_id="tenant-a", purpose=f"p-{os.getpid()}", url=QDRANT_URL)
    tenant_b = QdrantBackend(tenant_id="tenant-b", purpose=f"p-{os.getpid()}", url=QDRANT_URL)
    tenant_a.upsert((chunk_a,), embedder.embed((chunk_a.text,)))
    tenant_b.upsert((chunk_b,), embedder.embed((chunk_b.text,)))
    assert tenant_a.collection_name != tenant_b.collection_name
    try:
        query_vector = embedder.embed(("revenue forecast",))[0]
        # tenant-a 的集合只能看到自己的分块。
        results_a = tenant_a.search(
            query_vector, top_k=4, filter=_constraint(("source:fin", "source:ops"))
        )
        assert any(result.chunk.chunk_id == "c:a" for result in results_a)
        assert all(result.chunk.source_ref == "source:fin" for result in results_a)
    finally:
        tenant_a.delete("source:fin")
        tenant_b.delete("source:ops")
        tenant_a.delete_collection()
        tenant_b.delete_collection()
