"""Retrieval Router 测试：授权集合内路由与 ACL 过滤（RAG-009/010）。"""

from __future__ import annotations

import pytest

from tests import support
from ueaf.context.query_planner import QueryIntent
from ueaf.context.retrieval_router import RetrievalCandidate, RetrievalRouter


def _intent() -> QueryIntent:
    return QueryIntent(
        query_intent_id="intent:1",
        run_id="run:1",
        principal_context_ref="principal:1",
        query="orders reconciliation",
        purpose="research",
        source_constraints=("orders:read",),
        authorization_scope_ref="scope:orders:read",
        freshness_requirement="max_age_seconds=3600",
        citation_requirement=True,
        budget_slice="token:4000",
        normalized_query_hash="hash:1",
        policy_snapshot_ref="policy:1",
        expires_at=support.now(),
    )


def _candidate(source_ref: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        source_ref=source_ref,
        source_version="1.0.0",
        locator=f"doc:{source_ref}",
        content_ref=f"content:{source_ref}",
        snippet="candidate",
        allowed_scopes=("orders:read",),
        trust_label="high",
        citation_handle=f"cite:{source_ref}",
        route="lexical",
    )


def _router() -> RetrievalRouter:
    return RetrievalRouter(
        authorized_sources=("source:orders",),
        principal_scopes=("orders:read",),
        selection_policy_ref="policy:select@1.0.0",
    )


@pytest.mark.test_id("RAG-009")
def test_router_only_returns_authorized_candidates() -> None:
    router = _router()
    intent = _intent()
    # 词法后端返回了授权与越权来源。
    results = router.search(
        intent,
        backends={"lexical": lambda _i: (_candidate("source:orders"), _candidate("source:admin"))},
    )
    # RAG-009：结果绝不超出授权来源集合。
    assert results
    assert all(r.source_ref == "source:orders" for r in results)
    # 返回的候选携带来源版本与 ACL 证明。
    assert all(r.source_version == "1.0.0" for r in results)
    assert all(r.acl_proof_ref for r in results)


@pytest.mark.test_id("RAG-009")
def test_backend_bypassing_acl_is_filtered() -> None:
    router = _router()
    intent = _intent()
    # 有缺陷/恶意后端无视 ACL，返回了高相关但越权的来源。

    def _bypassing_backend(_intent: QueryIntent) -> tuple[RetrievalCandidate, ...]:
        return (_candidate("source:orders"), _candidate("source:secret-admin"))

    results = router.search(intent, backends={"lexical": _bypassing_backend})
    # 纵深防御（RAG-009）：即使后端返回多余候选，也绝不超出授权集合召回。
    assert {r.source_ref for r in results} == {"source:orders"}


@pytest.mark.test_id("RAG-010")
def test_router_selects_hybrid_and_falls_back_to_lexical() -> None:
    router = _router()
    intent = _intent()
    # 组合路由可用时优先选择 hybrid。
    results = router.search(
        intent,
        backends={"hybrid": lambda _i: (_candidate("source:orders"),), "lexical": lambda _i: ()},
    )
    assert results
    assert all(r.route == "hybrid" for r in results)

    # RAG-010：组合/向量后端失败时，在授权集合内降级为词法兜底。

    def _broken(_intent: QueryIntent) -> tuple[RetrievalCandidate, ...]:
        raise RuntimeError("backend down")

    fallback = router.search(
        intent,
        backends={"hybrid": _broken, "lexical": lambda _i: (_candidate("source:orders"),)},
    )
    assert fallback
    assert all(r.route == "lexical" for r in fallback)
    assert all(r.source_ref == "source:orders" for r in fallback)
