"""RAG 领域包：索引、检索、治理、证据与流水线。

RAG 检索层（RAG-001..RAG-016）的公开符号。新增此包初始化也修复了 ``ueaf.rag``
子包的 hatch 打包问题（此前仅作为命名空间目录，被排除在构建出的 wheel 之外）。
"""

from __future__ import annotations

from ueaf.rag.embedding import (
    DEFAULT_BGE_DIMENSION,
    DEFAULT_BGE_MODEL,
    BgeLocalEmbedding,
    DeterministicHashEmbedding,
    EmbeddingProvider,
)
from ueaf.rag.evidence import (
    Citation,
    EvidencePackBuilder,
    digest_citation,
    validate_citation,
)
from ueaf.rag.governance import (
    ContextBudget,
    RetrievalBenchmark,
    RetrievalTriggerGuard,
    RevocationTracker,
)
from ueaf.rag.hybrid import DEGRADED_COVERAGE_GAP, HybridQuery, HybridRetriever
from ueaf.rag.index import (
    Chunk,
    IndexPolicy,
    IndexProjection,
    RetrievalIndex,
    split_semantic_chunks,
)
from ueaf.rag.pipeline import IndexingPipeline, SourceDocument
from ueaf.rag.retrieval import (
    AuthorizedRetrieval,
    QueryPlan,
    QueryRewriter,
    RetrievalConstraint,
    RetrievalResult,
)

__all__ = [
    # 嵌入
    "EmbeddingProvider",
    "DeterministicHashEmbedding",
    "BgeLocalEmbedding",
    "DEFAULT_BGE_MODEL",
    "DEFAULT_BGE_DIMENSION",
    # 证据
    "Citation",
    "EvidencePackBuilder",
    "validate_citation",
    "digest_citation",
    # 治理
    "RetrievalTriggerGuard",
    "ContextBudget",
    "RevocationTracker",
    "RetrievalBenchmark",
    # 混合
    "HybridQuery",
    "HybridRetriever",
    "DEGRADED_COVERAGE_GAP",
    # 索引
    "Chunk",
    "IndexPolicy",
    "IndexProjection",
    "RetrievalIndex",
    "split_semantic_chunks",
    # 流水线
    "SourceDocument",
    "IndexingPipeline",
    # 检索
    "RetrievalConstraint",
    "RetrievalResult",
    "AuthorizedRetrieval",
    "QueryRewriter",
    "QueryPlan",
]
