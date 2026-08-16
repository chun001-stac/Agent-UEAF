"""Memory Service 全链路集成（CTX-001/CTX-005/CTX-007，RAG-007）。

候选 → 评审 → 晋升 → 更正 → 过期 → 删除 全生命周期；保留既有 promote/recall 兼容
（不破坏 test_p1_modules.py 的 CTX-001 测试）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.memory.helpers import MOMENT, candidate
from ueaf.memory.service import InMemoryMemoryStore, MemoryGovernanceError, MemoryService


@pytest.mark.test_id("CTX-001")
def test_full_lifecycle_candidate_review_promote_correct_expire_delete() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    cand = candidate("cand:1", statement="user prefers short-term trades", confidence=0.9)
    service.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate("cand:1", decision="approved", reviewed_by="reviewer:1", moment=MOMENT)
    resolution = service.promote_from_review("cand:1", moment=MOMENT)
    assert resolution.outcome == "promoted"
    record = store.get(resolution.record_ref)
    assert record is not None
    assert record.status == "active"

    # 更正链：旧版 superseded，新版 active。
    corrected = service.correct(
        record.record_id, statement="user prefers medium-term trades", confidence=0.9, moment=MOMENT
    )
    assert corrected.status == "active"
    assert corrected.supersedes_ref == record.record_id

    # 过期：状态置 expired，观测过期滞后。
    expired = service.expire(corrected.record_id, moment=MOMENT + timedelta(days=400))
    assert expired.status == "expired"
    assert service.audit_metrics()["expiry_lag_seconds"] > 0

    # 删除：传播到 Store + 投影。
    deleted = service.delete(expired.record_id, moment=MOMENT)
    assert deleted.status == "deleted"
    assert service.recall("principal:1", moment=MOMENT) == []
    assert store.active_for("principal:1", moment=MOMENT) == []


@pytest.mark.test_id("CTX-001")
def test_promote_legacy_direct_promotion_preserved() -> None:
    service = MemoryService()
    safe = candidate("cand:1", purpose="analytics", sensitivity="internal", required_consent=False)
    record = service.promote(safe, moment=MOMENT)
    assert record.status == "active"
    assert [r.record_id for r in service.recall("principal:1", moment=MOMENT)] == [record.record_id]


@pytest.mark.test_id("CTX-001")
def test_promote_sensitive_without_consent_raises() -> None:
    service = MemoryService()
    sensitive = candidate("cand:1", sensitivity="confidential", required_consent=True)
    with pytest.raises(MemoryGovernanceError):
        service.promote(sensitive, moment=MOMENT)


@pytest.mark.test_id("CTX-001")
def test_resolve_sensitive_without_consent_is_rejected_not_crash() -> None:
    # M1：敏感候选无论 required_consent 标志如何，都以受控 rejected 拒绝，
    # 绝不带缺失 consent_ref 进入 MemoryRecord 抛裸 ValueError。
    service = MemoryService()
    for flag in (True, False):
        sensitive = candidate(
            f"cand:{flag}", sensitivity="confidential", required_consent=flag
        )
        resolution = service.resolve(sensitive, moment=MOMENT)
        assert resolution.outcome == "rejected"
        assert "consent_required" in resolution.reason_codes
    # 无任何记录被物化，敏感内容绝不被召回。
    assert service.recall("principal:1", moment=MOMENT) == []


@pytest.mark.test_id("CTX-005")
def test_correct_superseded_or_expired_record_is_rejected() -> None:
    # M2：更正链必须线性——只允许更正当前 active 版本，避免谱系分叉。
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    v1 = service.promote(candidate("cand:1", statement="a"), moment=MOMENT)
    v2 = service.correct(v1.record_id, statement="b", confidence=0.9, moment=MOMENT)
    assert store.get(v1.record_id).status == "superseded"  # type: ignore[union-attr]
    # 更正已 superseded 的旧版本 -> 拒绝。
    with pytest.raises(MemoryGovernanceError):
        service.correct(v1.record_id, statement="c", confidence=0.9, moment=MOMENT)
    # 更正已 expired 的记录 -> 拒绝。
    service.expire(v2.record_id, moment=MOMENT)
    with pytest.raises(MemoryGovernanceError):
        service.correct(v2.record_id, statement="d", confidence=0.9, moment=MOMENT)
    # 谱系保持线性：同 subject/scope 只保留一条 active（v2 已 expired，无残留 active）。
    assert service.recall("principal:1", moment=MOMENT) == []


@pytest.mark.test_id("CTX-007")
def test_promote_from_review_requires_approval() -> None:
    service = MemoryService()
    cand = candidate("cand:1", confidence=0.9)
    # 未提交评审：不可晋升。
    resolution = service.promote_from_review("cand:1", moment=MOMENT)
    assert resolution.outcome == "needs_review"
    assert "not_approved" in resolution.reason_codes
    # 仅 pending_review：仍不可晋升。
    service.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    resolution = service.promote_from_review("cand:1", moment=MOMENT)
    assert resolution.outcome == "needs_review"
    assert "not_approved" in resolution.reason_codes


@pytest.mark.test_id("RAG-007")
def test_team_tenant_candidate_requires_review_before_promote() -> None:
    service = MemoryService()
    team_cand = candidate("cand:1", scope_requested="team", confidence=0.97)
    # 未评审直接 promote -> 治理拒绝（§7 更高审查阈值）。
    with pytest.raises(MemoryGovernanceError):
        service.promote(team_cand, moment=MOMENT)
    # 评审 approved（高置信度通过更高阈值）后晋升成功。
    service.submit_candidate(team_cand, reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate("cand:1", decision="approved", reviewed_by="reviewer:1", moment=MOMENT)
    resolution = service.promote_from_review("cand:1", moment=MOMENT)
    assert resolution.outcome == "promoted"


@pytest.mark.test_id("CTX-005")
def test_correct_expire_delete_chain_observable() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    v1 = service.promote(candidate("cand:1", statement="a"), moment=MOMENT)
    v2 = service.correct(v1.record_id, statement="b", confidence=0.9, moment=MOMENT)
    assert store.get(v1.record_id).status == "superseded"  # type: ignore[union-attr]
    assert v2.supersedes_ref == v1.record_id
    service.expire(v2.record_id, moment=MOMENT)
    assert store.get(v2.record_id).status == "expired"  # type: ignore[union-attr]
    service.delete(v2.record_id, moment=MOMENT)
    assert store.get(v2.record_id).status == "deleted"  # type: ignore[union-attr]
    assert service.recall("principal:1", moment=MOMENT) == []
    # 指标可采集（供 TelemetryPort）。
    assert service.audit_metrics()["candidate_promoted"] == 1
