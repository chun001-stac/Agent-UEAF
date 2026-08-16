"""基于 Qdrant 的 RAG 检索层 ``VectorBackend``。

集合按 (tenant, purpose) 隔离：集合名称同时编码两者，因此一个 tenant/purpose 的
候选不会泄漏到另一个（RAG-009）。每个点的 payload 携带 chunk_id / source_ref /
source_version / locator / text，因此命中结果无需二次查询即可重建为规范的
``Chunk``。删除按 ``source_ref`` payload 过滤（RAG-008）。

``qdrant-client`` 为懒导入，因此缺少它时模块仍可正常导入；首次使用时若缺失会抛出
明确的 ``RuntimeError``。连接 URL 来自 ``UEAF_QDRANT_URL``（默认
``http://127.0.0.1:6333``），并可在构造函数中覆盖。
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Sequence
from typing import Any

from ueaf.common.identifiers import sha256_hex
from ueaf.rag.index import Chunk
from ueaf.rag.retrieval import RetrievalConstraint, RetrievalResult

DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"


def _import_qdrant_client() -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError as error:
        raise RuntimeError(
            "QdrantBackend 需要安装 qdrant-client；请通过 "
            "`pip install 'qdrant-client>=1.13,<1.14'` 安装"
        ) from error
    return QdrantClient


def _safe_part(part: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", part).strip("_")
    return cleaned or "default"


class QdrantBackend:
    """按 (tenant, purpose) 隔离的 Qdrant ``VectorBackend``。"""

    def __init__(
        self,
        *,
        tenant_id: str,
        purpose: str,
        url: str | None = None,
        collection_prefix: str = "ueaf",
    ) -> None:
        if not tenant_id:
            raise ValueError("tenant_id must not be empty")
        if not purpose:
            raise ValueError("purpose must not be empty")
        self._tenant_id = tenant_id
        self._purpose = purpose
        self._url = url or os.environ.get("UEAF_QDRANT_URL", DEFAULT_QDRANT_URL)
        self._collection = self._collection_name(collection_prefix, tenant_id, purpose)
        self._client: Any | None = None
        self._dimension: int | None = None
        # RAG-008 墓碑集合：已删除的来源绝不会重新进入生产检索，
        # 即使之后再次 upsert 相同的 source_ref 也不行。
        self._deleted_sources: set[str] = set()

    @property
    def collection_name(self) -> str:
        return self._collection

    @property
    def url(self) -> str:
        return self._url

    @staticmethod
    def _collection_name(prefix: str, tenant_id: str, purpose: str) -> str:
        # ``_safe_part`` 是有损的清理函数（例如 ``tenant:a`` 与 ``tenant_a``
        # 会归一化为同一 token），因此我们附加原始 (tenant_id, purpose) 对的稳定
        # 哈希。即使清理后的名称发生冲突，也能保证不同租户拥有不同集合
        # （RAG-009 租户隔离）。
        base = "_".join([_safe_part(prefix), _safe_part(tenant_id), _safe_part(purpose)])
        digest = sha256_hex(f"{tenant_id}|{purpose}")[:12]
        return f"{base}_{digest}"

    def _resolve_dimension(self) -> int | None:
        """解析集合维度，并在进程重启后依然有效（M1）。

        ``_dimension`` 仅由该实例自身的 ``upsert`` 填充；否则，一个指向已存在集合的
        新进程会在 ``search`` 中返回空结果集。此处我们探测实时的 Qdrant 集合，使
        之前进程索引的数据仍可被检索。
        """
        if self._dimension is not None:
            return self._dimension
        client = self._qdrant
        try:
            if not client.collection_exists(self._collection):
                return None
            info = client.get_collection(self._collection)
        except Exception:
            # 将不可读的集合视为尚未索引；调用方会回退到降级词法路径而不是崩溃。
            return None
        vectors = getattr(getattr(getattr(info, "config", None), "params", None), "vectors", None)
        size: int | None = None
        if hasattr(vectors, "size"):
            size = vectors.size  # type: ignore[union-attr]
        elif isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            size = getattr(first, "size", None)
        if size is None:
            return None
        self._dimension = int(size)
        return self._dimension

    @property
    def _qdrant(self) -> Any:
        if self._client is None:
            self._client = _import_qdrant_client()(url=self._url)
        return self._client

    def upsert(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]]
    ) -> tuple[Chunk, ...]:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have equal length")
        points: list[Any] = []
        accepted: list[Chunk] = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if chunk.source_ref in self._deleted_sources:
                # RAG-008：已删除的来源绝不会重新进入生产检索。
                continue
            dimension = len(vector)
            if dimension == 0:
                raise ValueError(f"empty vector for chunk {chunk.chunk_id}")
            if self._dimension is None:
                self._dimension = dimension
                self._ensure_collection(dimension)
            elif dimension != self._dimension:
                raise ValueError(
                    f"vector dimension {dimension} != {self._dimension} for chunk {chunk.chunk_id}"
                )
            accepted.append(chunk)
            points.append(self._point(chunk, vector))
        if points:
            self._qdrant.upsert(collection_name=self._collection, points=points)
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
        if self._resolve_dimension() is None:
            return ()  # 集合尚不存在（或不可读）
        from qdrant_client.models import (
            FieldCondition,
            MatchAny,
        )
        from qdrant_client.models import (
            Filter as QdrantFilter,
        )

        conditions: list[Any] = []
        allowlist = filter.source_allowlist
        if allowlist:
            conditions.append(FieldCondition(key="source_ref", match=MatchAny(any=list(allowlist))))
        query_filter = QdrantFilter(must=conditions) if conditions else None
        hits = self._qdrant.search(
            collection_name=self._collection,
            query_vector=list(query_vector),
            limit=top_k,
            query_filter=query_filter,
        )
        results: list[RetrievalResult] = []
        for hit in hits:
            payload = getattr(hit, "payload", None) or {}
            chunk = Chunk(
                chunk_id=str(payload.get("chunk_id", "")),
                source_ref=str(payload.get("source_ref", "")),
                source_version=str(payload.get("source_version", "")),
                text=str(payload.get("text", "")),
                locator=str(payload.get("locator", "")),
                embedding_ref=self._collection,
            )
            results.append(RetrievalResult(chunk=chunk, score=float(getattr(hit, "score", 0.0))))
        return tuple(results)

    def delete(self, source_ref: str) -> int:
        from qdrant_client.models import (
            FieldCondition,
            FilterSelector,
            MatchValue,
        )
        from qdrant_client.models import (
            Filter as QdrantFilter,
        )

        client = self._qdrant
        query_filter = QdrantFilter(
            must=[FieldCondition(key="source_ref", match=MatchValue(value=source_ref))]
        )
        count = int(client.count(collection_name=self._collection, count_filter=query_filter).count)
        if count:
            client.delete(
                collection_name=self._collection,
                points_selector=FilterSelector(filter=query_filter),
            )
        # RAG-008 墓碑：即使之后重新 upsert 相同的 source_ref，也不能让已删除的
        # 来源重新进入生产检索。
        self._deleted_sources.add(source_ref)
        return count

    def _ensure_collection(self, dimension: int) -> None:
        from qdrant_client.models import (
            Distance,
            VectorParams,
        )

        client = self._qdrant
        if client.collection_exists(self._collection):
            return
        client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )

    def _point(self, chunk: Chunk, vector: Sequence[float]) -> Any:
        from qdrant_client.models import PointStruct

        return PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
            vector=list(vector),
            payload={
                "chunk_id": chunk.chunk_id,
                "source_ref": chunk.source_ref,
                "source_version": chunk.source_version,
                "locator": chunk.locator,
                "text": chunk.text,
                "embedding_ref": self._collection,
                "digest": sha256_hex(chunk.chunk_id),
            },
        )

    def delete_collection(self) -> None:
        """删除本实例所对应的整个集合（用于测试清理/重建）。

        属于实现细节：仅在需要完整清理某 (tenant, purpose) 集合时使用
        （例如集成测试的收尾），不会影响既有 RAG 规范对象语义。
        """
        client = self._qdrant
        if client.collection_exists(self._collection):
            client.delete_collection(self._collection)
        self._deleted_sources.clear()
        self._dimension = None


__all__ = ["QdrantBackend", "DEFAULT_QDRANT_URL"]
