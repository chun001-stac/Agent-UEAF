"""RAG 索引流水线：来源 -> 语义分块 -> 嵌入 -> 后端。

RAG-005 可复现索引元数据：ingest 生成一个 ``IndexProjection``，其摘要取决于来源
版本以及 parser/chunk/embedding/index 策略；其中任何一项变化都会产生可区分的投影。
RAG-006 语义分块边界：分块复用了 ``split_semantic_chunks``，因此标题/表格表头/
围栏代码块永远不会被拆分。
RAG-008 已删除来源消失：``delete`` 会同步到向量后端和可选的词法镜像，因此该来源
不会再被召回。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ueaf.rag.embedding import EmbeddingProvider
from ueaf.rag.index import (
    Chunk,
    IndexPolicy,
    IndexProjection,
    RetrievalIndex,
    split_semantic_chunks,
)

if TYPE_CHECKING:
    # 仅在类型注解中使用：若在此处运行时导入 VectorBackend 会造成循环导入
    # （vector -> rag.index -> rag 包再导出 -> rag.pipeline -> vector）。
    from ueaf.infrastructure.vector import VectorBackend


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """索引流水线的派生输入（非持久化的规范对象）。

    仅携带可复现索引所需的最小身份信息：来源引用和版本，以及待分块的原始文本。
    """

    source_ref: str
    source_version: str
    text: str
    locator: str = "doc"


class IndexingPipeline:
    """将来源摄入向量后端，并跟踪投影元数据。

    ``lexical_index`` 为可选：提供时，流水线还会把分块镜像到内存中的
    ``RetrievalIndex``，使混合检索器的词法通道与向量后端保持一致。
    """

    def __init__(
        self,
        *,
        backend: VectorBackend,
        embedder: EmbeddingProvider,
        policy: IndexPolicy | None = None,
        lexical_index: RetrievalIndex | None = None,
    ) -> None:
        self._backend = backend
        self._embedder = embedder
        self._policy = policy or IndexPolicy()
        self._lexical_index = lexical_index

    def ingest(self, document: SourceDocument) -> IndexProjection:
        raw = split_semantic_chunks(document.text, locator=document.locator)
        chunks = tuple(self._materialize(document, index, chunk) for index, chunk in enumerate(raw))
        vectors = self._embedder.embed(tuple(chunk.text for chunk in chunks))
        self._backend.upsert(chunks, vectors)
        if self._lexical_index is not None:
            for chunk in chunks:
                self._lexical_index.add(chunk)
        # 投影记录实际的嵌入器，以便模型/策略变化可区分（RAG-005）。
        policy = IndexPolicy(
            parser_version=self._policy.parser_version,
            chunk_version=self._policy.chunk_version,
            embedding_version=self._embedder.name,
            index_version=self._policy.index_version,
        )
        return IndexProjection(
            source_ref=document.source_ref,
            source_version=document.source_version,
            policy=policy,
            chunk_refs=tuple(chunk.chunk_id for chunk in chunks),
        )

    def delete(self, source_ref: str) -> None:
        """从向量后端和词法镜像中移除一个来源。"""
        self._backend.delete(source_ref)
        if self._lexical_index is not None:
            self._lexical_index.delete_source(source_ref)

    @staticmethod
    def _materialize(document: SourceDocument, index: int, chunk: Chunk) -> Chunk:
        return Chunk(
            chunk_id=f"{document.source_ref}@{document.source_version}:{index}",
            source_ref=document.source_ref,
            source_version=document.source_version,
            text=chunk.text,
            locator=chunk.locator,
            embedding_ref=None,
        )


__all__ = ["SourceDocument", "IndexingPipeline"]
