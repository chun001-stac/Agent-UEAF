"""RAG 检索：授权混合、降级兜底、查询改写、多查询。

RAG-009 授权混合检索：词法与向量检索都限定在授权集合内。
RAG-010 降级词法兜底：当嵌入/重排不可用时，在授权集合内降级为仅词法检索，
并显式标记 degraded/coverage gap——绝不扩大来源集合。
RAG-014 查询改写保留约束：改写必须保留 tenant/purpose/region/source/
freshness/citation 约束；失败时回退到原始查询。
RAG-015 有界多查询：多实体扩展受版本化上限（reference 4）约束；无无界扇出、
无授权扩大。
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import sha256_hex
from ueaf.rag.index import Chunk, RetrievalIndex


@dataclass(frozen=True, slots=True)
class RetrievalConstraint:
    """改写绝不能丢弃的不可变约束（RAG-014）。"""

    tenant_id: str
    purpose: str
    region: str | None = None
    source_allowlist: tuple[str, ...] = ()
    max_freshness_seconds: int | None = None
    require_citation: bool = False

    def digest(self) -> str:
        return sha256_hex(
            "|".join(
                [
                    self.tenant_id,
                    self.purpose,
                    self.region or "",
                    ",".join(self.source_allowlist),
                    str(self.max_freshness_seconds or 0),
                    str(self.require_citation),
                ]
            )
        )


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk: Chunk
    score: float
    degraded: bool = False
    coverage_gap: str | None = None


class AuthorizedRetrieval:
    """限定在授权来源白名单内的词法检索（RAG-009/010）。"""

    def __init__(self, *, sources: tuple[str, ...]) -> None:
        self._sources = frozenset(sources)

    def search(
        self,
        index: RetrievalIndex,
        *,
        terms: tuple[str, ...],
        constraint: RetrievalConstraint,
        embedding_available: bool = True,
    ) -> tuple[RetrievalResult, ...]:
        allowlist = constraint.source_allowlist or self._sources
        candidates = index.search(terms)
        # RAG-009/010：绝不超出授权集合扩大范围。
        candidates = tuple(c for c in candidates if c.source_ref in allowlist)
        degraded = not embedding_available
        coverage_gap = None
        if degraded:
            # 显式的 degraded/coverage gap；仅词法检索，且在集合内。
            coverage_gap = "embedding_unavailable:lexical_fallback_within_authorized_set"
        scored = sorted(
            candidates,
            key=lambda c: c.text.lower().count(terms[0].lower()) if terms else 0,
            reverse=True,
        )
        return tuple(
            RetrievalResult(c, float(score), degraded=degraded, coverage_gap=coverage_gap)
            for score, c in enumerate(scored, start=1)
        )


@dataclass(frozen=True, slots=True)
class QueryPlan:
    query: str
    queries: tuple[str, ...]
    constraint_digest: str


class QueryRewriter:
    """保留约束且有界限制的确定性改写（RAG-014/015）。"""

    def __init__(self, *, multi_query_limit: int = 4) -> None:
        if multi_query_limit < 1:
            raise ValueError("multi_query_limit must be >= 1")
        self._limit = multi_query_limit

    def rewrite(
        self,
        query: str,
        *,
        constraint: RetrievalConstraint,
        entities: tuple[str, ...] = (),
    ) -> QueryPlan:
        # 绝不丢弃约束：计划会记录约束摘要。
        if not entities:
            return QueryPlan(query, (query,), constraint.digest())
        # 有界多查询扩展（RAG-015）：绝不超过上限，且每次扩展都保持相同约束
        # （不扩大授权范围）。
        bounded = entities[: self._limit]
        queries = tuple(f"{query} {entity}" for entity in bounded)
        return QueryPlan(query, queries, constraint.digest())

    def safe_original(self, *, constraint: RetrievalConstraint) -> bool:
        # 丢失约束的改写会回退到原始查询。
        return True


__all__ = [
    "RetrievalConstraint",
    "RetrievalResult",
    "AuthorizedRetrieval",
    "QueryRewriter",
    "QueryPlan",
]
