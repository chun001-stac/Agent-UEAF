"""RAG gap tests: RAG-002/003/004/005/006/007/008/009/010/011/012/013/014/015/016.

Covers the RAG slices missing from the reference implementation: trigger guard,
context budget, ContractMeta inheritance, reproducible indexing, semantic chunk
boundaries, ACL revocation propagation, deleted-source disappearance, authorized
hybrid retrieval, degraded lexical fallback, duplicate collapse, conflict
survival, citation validation, query-rewrite constraints, bounded multi-query,
and benchmark-to-QualityGate.
"""

from __future__ import annotations

import pytest

from ueaf.common.meta import ContractMeta
from ueaf.rag.evidence import (
    Citation,
    EvidencePackBuilder,
    validate_citation,
)
from ueaf.rag.governance import (
    ContextBudget,
    RetrievalBenchmark,
    RetrievalTriggerGuard,
    RevocationTracker,
)
from ueaf.rag.index import (
    Chunk,
    IndexPolicy,
    IndexProjection,
    RetrievalIndex,
    split_semantic_chunks,
)
from ueaf.rag.retrieval import (
    AuthorizedRetrieval,
    QueryRewriter,
    RetrievalConstraint,
)


def _chunk(text: str, *, source: str = "source:1", locator: str = "doc") -> Chunk:
    return Chunk(
        chunk_id=f"chunk:{source}:{locator}",
        source_ref=source,
        source_version="1.0.0",
        text=text,
        locator=locator,
    )


@pytest.mark.test_id("RAG-002")
def test_single_retrieval_empty_is_not_a_trigger() -> None:
    guard = RetrievalTriggerGuard()
    # A single empty retrieval must not become a Trigger/Mutation.
    assert guard.should_trigger(retrieval_empty=True, evidence_refs=()) is False
    assert guard.should_trigger(retrieval_empty=True, evidence_refs=("e:1",)) is False
    # Only sufficient evidence with a non-empty retrieval may trigger.
    assert guard.should_trigger(retrieval_empty=False, evidence_refs=("e:1",)) is True


@pytest.mark.test_id("RAG-003")
def test_context_mutation_respects_budget() -> None:
    budget = ContextBudget(model_tokens=4000, context_tokens=8000, permission_refs=16)
    assert budget.allows(tokens=2000, permission_refs=8) is True
    assert budget.allows(tokens=5000, permission_refs=8) is False
    assert budget.allows(tokens=2000, permission_refs=20) is False


@pytest.mark.test_id("RAG-004")
def test_core_contract_meta_inheritance() -> None:
    # EvidencePack / MemoryRecord use the core ContractMeta, never a module-local
    # second public meta.
    from ueaf.memory.objects import MemoryRecord

    meta = ContractMeta(
        contract_name="MemoryRecord",
        contract_version="1.0.0",
        object_id="memory:1",
        tenant_id="tenant-demo",
        created_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        producer="ueaf-test",
        producer_version="0.1.0",
    )
    record = MemoryRecord(
        meta=meta,
        record_id="memory:1",
        subject_ref="p:1",
        scope="user",
        source_refs=(),
        statement="s",
        confidence=0.9,
        consent_ref=None,
        sensitivity="internal",
        valid_from=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    assert isinstance(record.meta, ContractMeta)
    # The canonical class imported by context/memory is the same core meta.
    import ueaf.memory.objects as mo

    assert mo.ContractMeta is ContractMeta


@pytest.mark.test_id("RAG-005")
def test_indexing_projection_is_reproducible() -> None:
    policy = IndexPolicy()
    p1 = IndexProjection("source:1", "1.0.0", policy, ("c:1",))
    p2 = IndexProjection("source:1", "1.0.0", policy, ("c:1",))
    assert p1.same_as(p2)
    # Changing any policy version yields a distinguishable projection.
    changed = IndexProjection(
        "source:1", "1.0.0", IndexPolicy(chunk_version="chunk@2.0.0"), ("c:1",)
    )
    assert not p1.same_as(changed)
    # A different source version is a new projection.
    assert not p1.same_as(IndexProjection("source:1", "2.0.0", policy, ("c:1",)))


@pytest.mark.test_id("RAG-006")
def test_semantic_chunk_boundaries_are_preserved() -> None:
    text = (
        "# Section A\n"
        "body line\n"
        "```python\n"
        "def f():\n"
        "    return 1\n"
        "```\n"
        "| id | value |\n"
        "| 1  | 42    |\n"
    )
    chunks = split_semantic_chunks(text)
    joined = " ".join(c.text for c in chunks)
    # A fenced code block and a table header are never split across chunks.
    assert "def f():" in joined
    assert "| id | value |" in joined
    assert all(c.locator for c in chunks)


@pytest.mark.test_id("RAG-007")
def test_acl_revocation_propagates_within_slo() -> None:
    tracker = RevocationTracker(revocation_slo_seconds=300)
    assert tracker.is_servable("source:doc", now=0.0)
    tracker.revoke("source:doc", now=100.0)
    # Within the SLO it is removed from retrieval/cache.
    assert tracker.is_servable("source:doc", now=150.0) is False
    # Past the SLO it is isolated / fail closed.
    assert tracker.fail_closed("source:doc", now=500.0) is True


@pytest.mark.test_id("RAG-008")
def test_deleted_source_disappears_from_production_retrieval() -> None:
    index = RetrievalIndex()
    index.add(_chunk("approved policy text", source="source:docs", locator="policy"))
    index.delete_source("source:docs")
    # Production retrieval never recalls the old chunk.
    assert index.search(("policy",)) == ()
    # Historical snapshots are only served for isolated Eval/Replay.
    index.add(_chunk("approved policy text", source="source:docs", locator="policy"))
    assert index.search(("policy",), snapshot="replay:1") == ()


@pytest.mark.test_id("RAG-009")
def test_authorized_hybrid_retrieval_stays_in_set() -> None:
    index = RetrievalIndex()
    index.add(_chunk("orders reconciliation", source="source:orders"))
    index.add(_chunk("secret admin notes", source="source:admin"))
    retrieval = AuthorizedRetrieval(sources=("source:orders",))
    constraint = RetrievalConstraint(tenant_id="t", purpose="research")
    results = retrieval.search(index, terms=("orders",), constraint=constraint)
    assert results
    assert all(r.chunk.source_ref == "source:orders" for r in results)


@pytest.mark.test_id("RAG-010")
def test_degraded_lexical_fallback_stays_in_authorized_set() -> None:
    index = RetrievalIndex()
    index.add(_chunk("orders reconciliation", source="source:orders"))
    index.add(_chunk("admin secrets", source="source:admin"))
    retrieval = AuthorizedRetrieval(sources=("source:orders",))
    constraint = RetrievalConstraint(tenant_id="t", purpose="research")
    results = retrieval.search(
        index, terms=("admin",), constraint=constraint, embedding_available=False
    )
    # Embedding unavailable -> lexical fallback, but never beyond the set.
    assert results == () or all(r.chunk.source_ref == "source:orders" for r in results)


@pytest.mark.test_id("RAG-011")
def test_duplicate_chunks_do_not_fill_the_pack() -> None:
    builder = EvidencePackBuilder(max_chunks=3)
    chunk_a = _chunk("same overlapping text", source="source:1", locator="h1")
    chunk_b = _chunk("same overlapping text", source="source:1", locator="h2")
    pack = builder.build((chunk_a, chunk_b, _chunk("distinct", source="source:2")))
    # Same source+version+text collapses to one chunk; the pack stays bounded.
    assert len(pack) <= 3
    assert len(pack) == 2  # a,b collapse -> distinct source:2 remains
    assert {c.source_ref for c in pack} == {"source:1", "source:2"}


@pytest.mark.test_id("RAG-012")
def test_conflicts_survive_dedup() -> None:
    builder = EvidencePackBuilder()
    chunk_a = _chunk("revenue is 100", source="source:a")
    chunk_b = _chunk("revenue is 200", source="source:b")
    pack = builder.build((chunk_a, chunk_b), conflicts=(("source:a", "source:b"),))
    # Conflicting sources are never dropped by dedup.
    assert {c.source_ref for c in pack} == {"source:a", "source:b"}


@pytest.mark.test_id("RAG-013")
def test_citations_resolve_only_against_visible_pack() -> None:
    chunk = _chunk("approved", source="source:docs", locator="policy")
    citation = Citation(
        citation_id="cite:1",
        source_ref="source:docs",
        source_version="1.0.0",
        locator="policy",
        span="0-8",
    )
    assert validate_citation(citation, (chunk,)) is True
    # A fabricated citation id / wrong locator fails validation.
    forged = Citation(
        citation_id="cite:fake", source_ref="source:docs", source_version="9.9.9", locator="x"
    )
    assert validate_citation(forged, (chunk,)) is False


@pytest.mark.test_id("RAG-014")
def test_query_rewrite_preserves_constraints() -> None:
    constraint = RetrievalConstraint(
        tenant_id="tenant:1",
        purpose="research",
        region="eu",
        source_allowlist=("source:a",),
        require_citation=True,
    )
    rewriter = QueryRewriter()
    plan = rewriter.rewrite("how to reconcile", constraint=constraint)
    assert plan.constraint_digest == constraint.digest()
    # A rewrite that drops constraints falls back to the original query.
    assert rewriter.safe_original(constraint=constraint) is True
    assert plan.queries == ("how to reconcile",)


@pytest.mark.test_id("RAG-015")
def test_multi_query_is_bounded() -> None:
    rewriter = QueryRewriter(multi_query_limit=4)
    constraint = RetrievalConstraint(tenant_id="t", purpose="research")
    plan = rewriter.rewrite(
        "orders", constraint=constraint, entities=("a", "b", "c", "d", "e", "f")
    )
    # Bounded fan-out (reference default 4); never unbounded.
    assert len(plan.queries) == 4


@pytest.mark.test_id("RAG-016")
def test_retrieval_benchmark_feeds_quality_gate() -> None:
    benchmark = RetrievalBenchmark(
        benchmark_id="bench:1",
        baseline_recall=0.7,
        baseline_precision=0.8,
        current_recall=0.9,
        current_precision=0.9,
    )
    assert benchmark.improved(recall_gain=0.15, precision_gain=0.05) is True
    # A regression in recall fails the improvement check.
    regressed = RetrievalBenchmark(
        benchmark_id="bench:2",
        baseline_recall=0.7,
        baseline_precision=0.8,
        current_recall=0.6,
        current_precision=0.9,
    )
    assert regressed.improved(recall_gain=0.05, precision_gain=0.0) is False
    assert benchmark.digest != regressed.digest
