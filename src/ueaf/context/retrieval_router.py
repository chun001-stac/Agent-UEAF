"""Retrieval Router：在授权集合内选择词法/向量/组合检索路由（RAG-009/010）。

路由只处理已授权候选：无论后端返回什么，都会再次按来源 ACL 过滤
（RAG-009 纵深防御：即使后端返回多余候选，也绝不超出授权集合召回）；
嵌入/向量不可用或失败时，在授权集合内降级为词法兜底（RAG-010），绝不扩大
来源集合。返回的候选携带来源版本与 ACL 证明（供下游 Evidence Assembler
复用）。真正的混合融合（RRF）由 RAG 层的 ``HybridRetriever`` 负责，本路由只
负责“授权集合内的路由选择”这一上下文层职责。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from ueaf.common.identifiers import sha256_hex
from ueaf.context.query_planner import QueryIntent


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """获授权检索候选（模块内部派生对象，非持久化规范对象）。

    只携带来源/版本/定位/内容引用与最小片段（正文与元数据分离），并带有
    ACL 证明 ref；候选绝不包含未经授权的内容。
    """

    source_ref: str
    source_version: str
    locator: str
    content_ref: str
    snippet: str
    allowed_scopes: tuple[str, ...]
    trust_label: str
    citation_handle: str
    route: str = "lexical"
    acl_proof_ref: str | None = None
    observed_at: datetime | None = None


Backend = Callable[[QueryIntent], Sequence[RetrievalCandidate]]


class RetrievalRouter:
    """在授权集合内选择词法/向量/组合路由；绝不绕过来源 ACL（RAG-009/010）。"""

    def __init__(
        self,
        *,
        authorized_sources: tuple[str, ...],
        principal_scopes: tuple[str, ...],
        selection_policy_ref: str,
        default_route: str = "lexical",
    ) -> None:
        self._authorized = frozenset(authorized_sources)
        self._principal_scopes = frozenset(principal_scopes)
        self._selection_policy_ref = selection_policy_ref
        self._default_route = default_route

    def search(
        self,
        intent: QueryIntent,
        *,
        backends: Mapping[str, Backend],
    ) -> tuple[RetrievalCandidate, ...]:
        route_name = self._select_route(backends)
        raw: tuple[RetrievalCandidate, ...]
        try:
            # 立即物化：生成器/迭代器在调用时才抛错，也必须被降级逻辑捕获。
            raw = tuple(backends[route_name](intent))
        except Exception:
            # RAG-010：所选路由失败时在授权集合内降级到词法兜底。
            if route_name == self._default_route or self._default_route not in backends:
                return ()
            route_name = self._default_route
            try:
                raw = tuple(backends[route_name](intent))
            except Exception:
                return ()
        return self._authorize(raw, route_name)

    def _select_route(self, backends: Mapping[str, Backend]) -> str:
        """确定性路由选择：优先组合（hybrid），其次向量，最后词法兜底。"""
        for preferred in ("hybrid", "vector", self._default_route):
            if preferred in backends:
                return preferred
        return self._default_route

    def _authorize(
        self,
        candidates: Sequence[RetrievalCandidate],
        route: str,
    ) -> tuple[RetrievalCandidate, ...]:
        allowed: list[RetrievalCandidate] = []
        for candidate in candidates:
            # 纵深防御（RAG-009）：即使后端返回了多余候选，也绝不超出授权集合。
            if candidate.source_ref not in self._authorized:
                continue
            if not set(candidate.allowed_scopes).intersection(self._principal_scopes):
                continue
            source_key = f"{candidate.source_ref}@{candidate.source_version}"
            proof_ref = f"{self._selection_policy_ref}|{source_key}"
            proof = f"acl-proof:{sha256_hex(proof_ref)}"
            allowed.append(
                RetrievalCandidate(
                    source_ref=candidate.source_ref,
                    source_version=candidate.source_version,
                    locator=candidate.locator,
                    content_ref=candidate.content_ref,
                    snippet=candidate.snippet,
                    allowed_scopes=candidate.allowed_scopes,
                    trust_label=candidate.trust_label,
                    citation_handle=candidate.citation_handle,
                    route=route,
                    acl_proof_ref=proof,
                    observed_at=candidate.observed_at,
                )
            )
        return tuple(allowed)


__all__ = ["RetrievalCandidate", "RetrievalRouter", "Backend"]
