"""Evidence Assembler 测试：证据包装配与元数据分离（RAG-001/CTX-006/RAG-013）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests import support
from ueaf.context.conflict import ClaimConflict, ConflictRegistry
from ueaf.context.evidence_assembler import EvidenceAssembler
from ueaf.context.query_planner import QueryIntent
from ueaf.context.retrieval_router import RetrievalCandidate


def _intent() -> QueryIntent:
    return QueryIntent(
        query_intent_id="intent:1",
        run_id="run:1",
        principal_context_ref="principal:1",
        query="revenue trend",
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


def _candidate(
    source_ref: str,
    *,
    acl_proof: str | None = "proof:1",
    snippet: str = "s",
    observed_at=None,
) -> RetrievalCandidate:
    return RetrievalCandidate(
        source_ref=source_ref,
        source_version="1.0.0",
        locator=f"doc:{source_ref}",
        content_ref=f"content:{source_ref}",
        snippet=snippet,
        allowed_scopes=("orders:read",),
        trust_label="high",
        citation_handle=f"cite:{source_ref}",
        route="lexical",
        acl_proof_ref=acl_proof,
        observed_at=observed_at,
    )


def _assembler() -> EvidenceAssembler:
    return EvidenceAssembler(selection_policy_ref="policy:select@1.0.0")


@pytest.mark.test_id("RAG-013")
def test_items_carry_refs_and_citation_map_resolves() -> None:
    pack = _assembler().assemble(
        _intent(), candidates=(_candidate("source:a"), _candidate("source:b"))
    )
    assert len(pack.items) == 2
    # 证据正文与元数据分离：items 只存内容引用/最小片段，不复制正文。
    assert all(item.content_ref and item.snippet == "s" for item in pack.items)
    assert all(item.allowed_scopes and item.trust_label for item in pack.items)
    assert len(pack.source_versions) == 2
    # RAG-013：citation 解析到来源版本 + locator。
    citation = pack.citation_map[0]
    item = pack.items[0]
    assert citation.citation_handle == item.citation_handle
    assert citation.source_ref == item.source_ref
    assert citation.source_version == item.source_version
    assert citation.locator == item.locator
    assert pack.authorization_proof_refs


@pytest.mark.test_id("CTX-006")
def test_conflicts_are_preserved_in_pack() -> None:
    registry = ConflictRegistry()
    registry.register(
        ClaimConflict(
            claim_ref="claim:revenue",
            source_refs=("source:a",),
            versions=("1.0.0",),
            statement="revenue is 100",
        )
    )
    registry.register(
        ClaimConflict(
            claim_ref="claim:revenue",
            source_refs=("source:b",),
            versions=("2.0.0",),
            statement="revenue is 200",
        )
    )
    pack = _assembler().assemble(
        _intent(),
        candidates=(_candidate("source:a"), _candidate("source:b")),
        registry=registry,
    )
    # CTX-006：来源冲突保留在包中，绝不静默消解。
    assert len(pack.conflicts) == 1
    assert set(pack.conflicts[0].source_refs) == {"source:a", "source:b"}
    assert pack.coverage.contradictions == ("claim:revenue",)


@pytest.mark.test_id("RAG-013")
def test_coverage_reports_covered_missing_and_contradictions() -> None:
    registry = ConflictRegistry()
    registry.register(
        ClaimConflict(
            claim_ref="claim:x",
            source_refs=("source:b",),
            versions=("2.0.0",),
            statement="contradictory",
        )
    )
    pack = _assembler().assemble(
        _intent(),
        candidates=(
            _candidate("source:a", acl_proof="proof:a"),
            _candidate("source:b", acl_proof="proof:b"),
        ),
        registry=registry,
        required_question_refs=("source:a", "source:c"),
    )
    assert "source:a" in pack.coverage.covered
    assert "source:c" in pack.coverage.missing
    assert "claim:x" in pack.coverage.contradictions


@pytest.mark.test_id("RAG-013")
def test_freshness_marked_and_stale_candidates_omitted() -> None:
    moment = support.now()
    fresh = _candidate("source:fresh", acl_proof="proof:f", observed_at=moment)
    stale = _candidate(
        "source:stale", acl_proof="proof:s", observed_at=moment - timedelta(hours=2)
    )
    pack = _assembler().assemble(
        _intent(),
        candidates=(fresh, stale),
        max_freshness_seconds=3600,
        observed_at=moment,
    )
    # 过期来源被排除，并显式记录 freshness/omission。
    assert {i.source_ref for i in pack.items} == {"source:fresh"}
    assert pack.omission_summary.expired_omitted == 1
    assert all(f.satisfies for f in pack.freshness)


@pytest.mark.test_id("RAG-001")
def test_unauthorized_candidates_omitted_fail_closed() -> None:
    pack = _assembler().assemble(
        _intent(),
        candidates=(
            _candidate("source:a", acl_proof="proof:a"),
            _candidate("source:no-proof", acl_proof=None),
        ),
    )
    # RAG-001：无 ACL 证明的候选以 fail-closed 省略，绝不进入证据包。
    assert {i.source_ref for i in pack.items} == {"source:a"}
    assert pack.omission_summary.authorization_omitted == 1


@pytest.mark.test_id("RAG-001")
def test_omission_summary_counts_conflict_exclusions() -> None:
    registry = ConflictRegistry()
    registry.register(
        ClaimConflict(
            claim_ref="claim:z",
            source_refs=("source:not-in-pack",),
            versions=("1.0.0",),
            statement="z",
        )
    )
    pack = _assembler().assemble(
        _intent(), candidates=(_candidate("source:a"),), registry=registry
    )
    # 引用未进入包来源的冲突被安全统计（不泄露内容）。
    assert pack.conflicts == ()
    assert pack.omission_summary.conflict_omitted == 1
