"""记忆使用审计与指标（功能模块 04 §9，RAG-005/CTX-001）。

每次 recall 记录（subject/scope/purpose/时刻/命中）+ 计数；提供
candidate_promoted/rejected、review_total、recall_use_total、conflict_total、
expiry_lag、deletion_slo_breach 指标供 TelemetryPort 采集（§9）。
"""

from __future__ import annotations

import pytest

from tests.memory.helpers import MOMENT, candidate
from ueaf.memory.memory_audit import MemoryAudit
from ueaf.memory.service import MemoryService


@pytest.mark.test_id("RAG-005")
def test_recall_usage_is_recorded() -> None:
    service = MemoryService()
    record = service.promote(candidate("cand:1", statement="a"), moment=MOMENT)
    service.recall("principal:1", moment=MOMENT)
    service.recall("principal:1", purpose="analytics", moment=MOMENT)
    usages = service.audit_usages()
    assert len(usages) == 2
    assert usages[0].subject_ref == "principal:1"
    assert usages[0].recorded_at == MOMENT
    assert usages[0].hit_count == 1
    assert usages[0].record_refs == (record.record_id,)
    assert usages[1].purpose == "analytics"
    assert service.audit_metrics()["recall_use_total"] == 2


@pytest.mark.test_id("RAG-005")
def test_metric_counters_track_lifecycle() -> None:
    service = MemoryService()
    # promoted：非敏感 subject 级。
    service.promote(candidate("cand:1", statement="用户偏好短线交易"), moment=MOMENT)
    # rejected：敏感未同意。
    service.resolve(
        candidate("cand:2", statement="b", sensitivity="confidential", required_consent=True),
        moment=MOMENT,
    )
    # rejected：重复。
    service.resolve(candidate("cand:3", statement="用户偏好短线交易"), moment=MOMENT)
    # needs_review：冲突（绝不后写覆盖）。
    service.resolve(candidate("cand:4", statement="用户偏好长线交易"), moment=MOMENT)

    metrics = service.audit_metrics()
    assert metrics["candidate_promoted"] == 1
    assert metrics["candidate_rejected"] == 2
    assert metrics["conflict_total"] == 1
    assert metrics["recall_use_total"] == 0


@pytest.mark.test_id("RAG-005")
def test_review_metric_counts_reviews() -> None:
    service = MemoryService()
    cand = candidate("cand:1", statement="a")
    service.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate("cand:1", decision="approved", reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate(
        "cand:1", decision="needs_review", reviewed_by="reviewer:1", moment=MOMENT
    )
    assert service.audit_metrics()["review_total"] == 2


@pytest.mark.test_id("RAG-005")
def test_expiry_lag_and_deletion_slo_breach_metrics() -> None:
    audit = MemoryAudit()
    audit.observe_expiry_lag(12.5)
    audit.observe_expiry_lag(3.0)  # 取观测最大值。
    assert audit.metrics()["expiry_lag_seconds"] == 12.5
    audit.observe_deletion(1.5, 1.0)  # 传播超过 SLO -> 计数。
    audit.observe_deletion(0.5, 1.0)  # 未超 SLO -> 不计数。
    assert audit.metrics()["deletion_slo_breach"] == 1


@pytest.mark.test_id("CTX-001")
def test_unknown_metric_counter_is_rejected() -> None:
    audit = MemoryAudit()
    with pytest.raises(KeyError):
        audit.increment("not_a_registered_counter")
