"""召回投影：scope/purpose/有效期过滤、非 active 不命中、team/tenant 级（§5.1/§5.3/§7）。

CTX-007（04 只在授权范围内重建投影）、RAG-007（撤销/删除传播）、RAG-008（已删除来源
消失）。team/tenant 级记录通过直接构造受治理 MemoryRecord 写入 Store 以独立验证投影。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.memory.helpers import MOMENT, candidate, meta
from ueaf.memory.objects import MemoryRecord
from ueaf.memory.service import InMemoryMemoryStore, MemoryService


def _direct_record(
    record_id: str,
    *,
    subject_ref: str,
    scope: str,
    statement: str = "statement",
    valid_from=MOMENT,
    expires_at=None,
) -> MemoryRecord:
    """直接构造受治理记录（如权威同步路径），用于隔离测试投影。"""
    return MemoryRecord(
        meta=meta("MemoryRecord", record_id),
        record_id=record_id,
        subject_ref=subject_ref,
        scope=scope,
        source_refs=("evidence:1",),
        statement=statement,
        confidence=0.9,
        consent_ref=None,
        sensitivity="internal",
        valid_from=valid_from,
        expires_at=expires_at,
    )


@pytest.mark.test_id("CTX-007")
def test_recall_filters_by_scope_and_purpose() -> None:
    service = MemoryService()
    a = service.promote(
        candidate(
            "cand:1", subject_ref="principal:1", purpose="personalization", statement="pref a"
        ),
        moment=MOMENT,
    )
    b = service.promote(
        candidate("cand:2", subject_ref="principal:1", purpose="analytics", statement="pref b"),
        moment=MOMENT,
    )
    # purpose 过滤（scope 在晋升时承载来源 purpose）。
    assert [r.record_id for r in service.recall(
        "principal:1", purpose="analytics", moment=MOMENT
    )] == [b.record_id]
    # scope 过滤。
    assert [r.record_id for r in service.recall(
        "principal:1", scope="personalization", moment=MOMENT
    )] == [a.record_id]
    # 无过滤时全部命中。
    assert len(service.recall("principal:1", moment=MOMENT)) == 2


@pytest.mark.test_id("RAG-008")
def test_recall_excludes_superseded_deleted_expired() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    active = service.promote(candidate("cand:1", statement="a"), moment=MOMENT)
    src_superseded = service.promote(candidate("cand:2", statement="b"), moment=MOMENT)
    corrected = service.correct(
        src_superseded.record_id, statement="b2", confidence=0.9, moment=MOMENT
    )
    src_deleted = service.promote(candidate("cand:3", statement="c"), moment=MOMENT)
    service.delete(src_deleted.record_id, moment=MOMENT)
    src_expired = service.promote(candidate("cand:4", statement="d"), moment=MOMENT)
    service.expire(src_expired.record_id, moment=MOMENT)
    # 只有 active 记录命中；superseded/deleted/expired 全部排除（RAG-008）。
    hits = service.recall("principal:1", moment=MOMENT)
    hit_ids = [r.record_id for r in hits]
    # 更正后的新版本是 active 且命中；旧版（superseded）与 deleted/expired 均不命中。
    assert set(hit_ids) == {active.record_id, corrected.record_id}
    assert src_superseded.record_id not in hit_ids
    assert src_deleted.record_id not in hit_ids
    assert src_expired.record_id not in hit_ids


@pytest.mark.test_id("RAG-008")
def test_recall_validity_window_filters() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    # 未到 valid_from 的记录。
    store.save(
        _direct_record(
            "memory:1",
            subject_ref="principal:1",
            scope="user",
            valid_from=MOMENT + timedelta(days=1),
        )
    )
    # 已过 expires_at 的记录（valid_from 更早以满足 expires_at > valid_from）。
    store.save(
        _direct_record(
            "memory:2",
            subject_ref="principal:1",
            scope="user",
            valid_from=MOMENT - timedelta(days=10),
            expires_at=MOMENT - timedelta(days=1),
        )
    )
    assert service.recall("principal:1", moment=MOMENT) == []
    assert [r.record_id for r in service.recall(
        "principal:1", moment=MOMENT + timedelta(days=2)
    )] == ["memory:1"]


@pytest.mark.test_id("RAG-007")
def test_recall_team_tenant_scope_inclusion() -> None:
    store = InMemoryMemoryStore()
    service = MemoryService(store)
    subject = _direct_record("memory:1", subject_ref="principal:1", scope="user")
    team = _direct_record("memory:2", subject_ref="team:risk", scope="team")
    tenant = _direct_record("memory:3", subject_ref="tenant:demo", scope="tenant")
    store.save(subject)
    store.save(team)
    store.save(tenant)
    # 默认只命中主体自身记录。
    assert [r.record_id for r in service.recall("principal:1", moment=MOMENT)] == ["memory:1"]
    # M3：开启 team/tenant 但未授权时，绝不返回团队/租户级记忆（§7 授权贯穿）。
    ids_no_auth = [
        r.record_id
        for r in service.recall("principal:1", moment=MOMENT, include_team_tenant=True)
    ]
    assert ids_no_auth == ["memory:1"]
    # M3：声明授权团队/租户后，team/tenant 记忆才被召回（§7）。
    ids = [
        r.record_id
        for r in service.recall(
            "principal:1",
            moment=MOMENT,
            include_team_tenant=True,
            authorized_team_refs=("team:risk",),
            authorized_tenant_ref="tenant:demo",
        )
    ]
    assert set(ids) == {"memory:1", "memory:2", "memory:3"}
    # scope 过滤到团队级。
    team_only = [
        r.record_id
        for r in service.recall(
            "principal:1",
            moment=MOMENT,
            include_team_tenant=True,
            scope="team",
            authorized_team_refs=("team:risk",),
        )
    ]
    assert team_only == ["memory:2"]
    # 只授权了团队（非租户）时，租户级记忆仍不可见。
    team_only_no_tenant = [
        r.record_id
        for r in service.recall(
            "principal:1",
            moment=MOMENT,
            include_team_tenant=True,
            authorized_team_refs=("team:risk",),
        )
    ]
    assert team_only_no_tenant == ["memory:1", "memory:2"]
