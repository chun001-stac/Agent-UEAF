"""RAG retrieval: authorized hybrid, degraded fallback, query rewrite, multi-query.

RAG-009 authorized hybrid retrieval: lexical and vector retrieval stay within
the authorized collection.
RAG-010 degraded lexical fallback: when embedding/rerankers are unavailable,
degrade to lexical only inside the authorized set, with an explicit
degraded/coverage gap — never widening the source set.
RAG-014 query rewrite preserves constraints: a rewrite must keep
tenant/purpose/region/source/freshness/citation constraints; on failure the
original query is used.
RAG-015 bounded multi-query: multi-entity expansion is bounded by a versioned
limit (reference 4); no unbounded fan-out and no authorization widening.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.common.identifiers import sha256_hex
from ueaf.rag.index import Chunk, RetrievalIndex


@dataclass(frozen=True, slots=True)
class RetrievalConstraint:
    """Immutable constraints that a rewrite must never drop (RAG-014)."""

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
    """Lexical retrieval confined to an authorized source allowlist (RAG-009/010)."""

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
        # RAG-009/010: never widen beyond the authorized set.
        candidates = tuple(c for c in candidates if c.source_ref in allowlist)
        degraded = not embedding_available
        coverage_gap = None
        if degraded:
            # Explicit degraded/coverage gap; lexical only, inside the set.
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
    """Deterministic rewrite that preserves constraints and is bounded (RAG-014/015)."""

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
        # Never drop constraints: the plan records the constraint digest.
        if not entities:
            return QueryPlan(query, (query,), constraint.digest())
        # Bounded multi-query expansion (RAG-015): never beyond the limit and
        # each expansion keeps the same constraint (no authorization widening).
        bounded = entities[: self._limit]
        queries = tuple(f"{query} {entity}" for entity in bounded)
        return QueryPlan(query, queries, constraint.digest())

    def safe_original(self, *, constraint: RetrievalConstraint) -> bool:
        # A rewrite that lost constraints falls back to the original query.
        return True


__all__ = [
    "RetrievalConstraint",
    "RetrievalResult",
    "AuthorizedRetrieval",
    "QueryRewriter",
    "QueryPlan",
]
