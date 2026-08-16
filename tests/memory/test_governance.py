"""记忆治理：去重/冲突/更正链/保留期/同意撤销/删除传播/CAS（§5.3/§6/§7/§8）。

CTX-004 superseded 历史、CTX-005 更正谱系、CTX-006 冲突保留、RAG-007 撤销传播、
RAG-008 已删除消失、RAG-011 去重、RAG-012 冲突不被去重消解。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.memory.helpers import MOMENT, candidate, meta
from ueaf.memory.governance import MemoryGovernanceRules, RetentionPolicy
from ueaf.memory.objects import MemoryRecord
from ueaf.memory.service import InMemoryMemoryStore, MemoryGovernanceError, MemoryService


@pytest.mark.test_id("RAG-011")
def test_duplicate_candidate_is_rejected_without_touching_existing() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    first = service.promote(
        candidate("cand:1", statement="user prefers short-term trades"), moment=MOMENT
    )
    duplicate = candidate("cand:2", statement="user prefers short-term trades")
    resolution = service.resolve(duplicate, moment=MOMENT)
    assert resolution.outcome == "rejected"
    assert "duplicate" in resolution.reason_codes
    # 既有记录绝不被后写覆盖。
    assert service.recall("principal:1", moment=MOMENT) == [first]


@pytest.mark.test_id("CTX-006")
def test_conflict_candidate_isolated_needs_review_and_never_overwrites() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    first = service.promote(
        candidate("cand:1", statement="用户偏好短线交易", confidence=0.9), moment=MOMENT
    )
    conflicting = candidate("cand:2", statement="用户偏好长线交易", confidence=0.9)
    resolution = service.resolve(conflicting, moment=MOMENT)
    assert resolution.outcome == "needs_review"
    assert "conflict_detected" in resolution.reason_codes
    # 后写绝不覆盖已确认记录（CTX-006 / RAG-012），冲突被计数。
    assert service.recall("principal:1", moment=MOMENT) == [first]
    assert service.audit_metrics()["conflict_total"] == 1


@pytest.mark.test_id("CTX-004")
def test_correction_chain_supersedes_old_version() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    old = service.promote(
        candidate("cand:1", statement="user prefers short-term trades"), moment=MOMENT
    )
    new = service.correct(
        old.record_id, statement="user prefers medium-term trades", confidence=0.9, moment=MOMENT
    )
    assert new.status == "active"
    assert new.supersedes_ref == old.record_id
    assert store.get(old.record_id) is not None
    assert store.get(old.record_id).status == "superseded"  # type: ignore[union-attr]
    # 召回只返回新版本（旧版 superseded 不命中）。
    assert [r.record_id for r in service.recall("principal:1", moment=MOMENT)] == [new.record_id]


@pytest.mark.test_id("CTX-005")
def test_correction_lineage_is_traceable() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    v1 = service.promote(candidate("cand:1", statement="a"), moment=MOMENT)
    v2 = service.correct(v1.record_id, statement="b", confidence=0.9, moment=MOMENT)
    v3 = service.correct(v2.record_id, statement="c", confidence=0.9, moment=MOMENT)
    assert v2.supersedes_ref == v1.record_id
    assert v3.supersedes_ref == v2.record_id
    assert store.get(v1.record_id).status == "superseded"  # type: ignore[union-attr]
    assert store.get(v2.record_id).status == "superseded"  # type: ignore[union-attr]
    assert store.get(v3.record_id).status == "active"  # type: ignore[union-attr]
    assert [r.record_id for r in service.recall("principal:1", moment=MOMENT)] == [v3.record_id]


@pytest.mark.test_id("CTX-001")
def test_retention_hint_controls_expiry() -> None:
    rules = MemoryGovernanceRules(retention=RetentionPolicy(default_days=0, by_hint={"90d": 90}))
    service = MemoryService(rules=rules)
    record = service.promote(candidate("cand:1", retention_hint="90d"), moment=MOMENT)
    assert record.expires_at == MOMENT + timedelta(days=90)
    assert service.recall("principal:1", moment=MOMENT + timedelta(days=89)) == [record]
    # 到期点不再命中（moment >= expires_at）。
    assert service.recall("principal:1", moment=MOMENT + timedelta(days=90)) == []


@pytest.mark.test_id("CTX-001")
def test_session_retention_hint_not_persisted() -> None:
    service = MemoryService()
    resolution = service.resolve(candidate("cand:1", retention_hint="session"), moment=MOMENT)
    assert resolution.outcome == "rejected"
    assert "session_memory_not_persisted" in resolution.reason_codes
    assert service.recall("principal:1", moment=MOMENT) == []


@pytest.mark.test_id("RAG-007")
def test_revoke_consent_invalidates_affected_records() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    record = MemoryRecord(
        meta=meta("MemoryRecord", "memory:1"),
        record_id="memory:1",
        subject_ref="principal:1",
        scope="user",
        source_refs=("evidence:1",),
        statement="user PII preference",
        confidence=0.9,
        consent_ref="consent:principal:1:cand:1",
        sensitivity="confidential",
        valid_from=MOMENT,
    )
    store.save(record)
    assert service.recall("principal:1", moment=MOMENT) == [record]
    affected = service.revoke_consent("consent:principal:1:cand:1", moment=MOMENT)
    assert affected == ("memory:1",)
    assert store.get("memory:1").status == "deleted"  # type: ignore[union-attr]
    # 撤销传播到投影：不再命中。
    assert service.recall("principal:1", moment=MOMENT) == []


@pytest.mark.test_id("RAG-008")
def test_delete_propagates_to_store_and_projection() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    record = service.promote(candidate("cand:1", statement="workflow preference"), moment=MOMENT)
    assert service.recall("principal:1", moment=MOMENT) == [record]
    deleted = service.delete(record.record_id, moment=MOMENT, reason="user_request")
    assert deleted.status == "deleted"
    assert deleted.deletion_state == "user_request"
    assert store.get(record.record_id).status == "deleted"  # type: ignore[union-attr]
    # 权威 Store 与检索投影都被覆盖（RAG-008：已删除来源消失）。
    assert store.active_for("principal:1", moment=MOMENT) == []
    assert service.recall("principal:1", moment=MOMENT) == []


@pytest.mark.test_id("CTX-001")
def test_revision_cas_rejects_stale_update() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    record = service.promote(candidate("cand:1", statement="a"), moment=MOMENT)
    stale = replace(record, status="expired")  # revision 仍为 1，不是 2。
    with pytest.raises(MemoryGovernanceError):
        store.update(stale)
    # 失败后记录保持原状。
    assert store.get(record.record_id).status == "active"  # type: ignore[union-attr]
