"""Phase 2 context ownership / RAG ACL tests (CTX-*, RAG-001)."""

from __future__ import annotations

import pytest

from tests import support
from ueaf.context.context_build import ContextBuilder, SourceDocument
from ueaf.ports import ContextBuildRequest, Success

SCOPE = ("read",)


def _request(run_id: str = "run:1") -> ContextBuildRequest:
    return ContextBuildRequest(
        tenant_id=support.TENANT,
        run_id=run_id,
        query_intent_ref=f"query:{run_id}",
        policy_snapshot_ref=f"policy:{run_id}",
        budget_snapshot_ref=f"budget:{run_id}",
        deadline_at=support.now(),
    )


def _source(ref: str, *, scopes, trust: str, snippet: str = "s") -> SourceDocument:
    return SourceDocument(
        source_ref=ref,
        source_version="1.0.0",
        content_digest=f"sha256:{ref}",
        allowed_scopes=scopes,
        trust_label=trust,
        snippet=snippet,
    )


@pytest.mark.test_id("CTX-001")
def test_context_builder_is_the_only_writer_of_context_manifest() -> None:
    builder = ContextBuilder(
        sources=[
            _source("doc:1", scopes=("read",), trust="high"),
            _source("secret:1", scopes=("restricted",), trust="high"),
        ],
        principal_scopes=("read",),
    )
    result = builder.build(_request())
    assert isinstance(result, Success)
    assert "secret:1" not in result.value.evidence_pack_refs
    assert "doc:1" in result.value.evidence_pack_refs


@pytest.mark.test_id("CTX-002")
def test_packing_priority_is_deterministic_by_trust() -> None:
    builder = ContextBuilder(
        sources=[
            _source("low:1", scopes=SCOPE, trust="low"),
            _source("high:1", scopes=SCOPE, trust="high"),
            _source("mid:1", scopes=SCOPE, trust="medium"),
        ],
        principal_scopes=SCOPE,
    )
    result = builder.build(_request())
    assert isinstance(result, Success)
    packed = list(result.value.evidence_pack_refs)
    assert packed[0] == "high:1"
    assert set(packed) == {"high:1", "low:1", "mid:1"}


@pytest.mark.test_id("CTX-008")
def test_low_priority_cannot_starve_reserve() -> None:
    builder = ContextBuilder(
        sources=[_source(f"doc:{i}", scopes=SCOPE, trust="low") for i in range(20)],
        principal_scopes=SCOPE,
        max_snippets=3,
    )
    result = builder.build(_request())
    assert isinstance(result, Success)
    assert len(result.value.evidence_pack_refs) == 3


@pytest.mark.test_id("RAG-001")
def test_acl_filter_precedes_relevance_selection() -> None:
    builder = ContextBuilder(
        sources=[
            _source("allowed:1", scopes=("read",), trust="high"),
            _source("denied:1", scopes=("restricted",), trust="high"),
        ],
        principal_scopes=("read",),
    )
    result = builder.build(_request())
    assert isinstance(result, Success)
    assert result.value.evidence_pack_refs == ("allowed:1",)
