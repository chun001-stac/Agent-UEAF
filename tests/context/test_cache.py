"""ContextCache 测试：缓存键隔离与失效（RAG-001/RAG-007/RAG-008）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests import support
from ueaf.context.cache import CachedEvidence, InMemoryContextCache, cache_key


def _key(
    *,
    principal: str = "principal:1",
    tenant: str = "tenant-demo",
    query_digest: str = "query:1",
    scope: str = "scope:read",
    purpose: str = "research",
    source_versions: str = "source-v:1",
    policy: str = "policy:1",
    region: str = "cn-east",
) -> str:
    return cache_key(
        tenant_id=tenant,
        scope_summary=scope,
        purpose=purpose,
        query_digest=query_digest,
        source_versions_digest=source_versions,
        policy_version=policy,
        region=region,
        principal_ref=principal,
    )


def _entry(key: str, *, source_refs: tuple[str, ...] = ("source:1",)) -> CachedEvidence:
    return CachedEvidence(
        cache_key=key,
        evidence_pack_ref="pack:1",
        source_refs=source_refs,
        scope_ref="scope:read",
        expires_at=support.now() + timedelta(minutes=5),
    )


@pytest.mark.test_id("RAG-001")
def test_cache_key_includes_tenant_scope_purpose_versions() -> None:
    key = _key()
    # 键包含 tenant、授权范围摘要、purpose、查询摘要、来源版本、策略版本、地域与主体。
    parts = (
        "tenant-demo",
        "scope:read",
        "research",
        "query:1",
        "source-v:1",
        "policy:1",
        "cn-east",
        "principal:1",
    )
    assert all(part in key for part in parts)
    # 仅自然语言 query 相同而主体不同 -> 不同键（禁止跨主体复用）。
    assert _key(principal="principal:1") != _key(principal="principal:2")
    # 任一授权维度变化 -> 不同键。
    assert _key(tenant="tenant-other") != key
    assert _key(scope="scope:admin") != key
    assert _key(purpose="billing") != key
    assert _key(query_digest="query:2") != key
    assert _key(source_versions="source-v:2") != key
    assert _key(policy="policy:2") != key
    assert _key(region="us-west") != key


@pytest.mark.test_id("RAG-001")
def test_cross_subject_same_query_does_not_hit() -> None:
    cache = InMemoryContextCache()
    now = support.now()
    alice_key = _key(principal="principal:alice")
    bob_key = _key(principal="principal:bob")
    cache.put(_entry(alice_key), now=now)
    # 同一自然语言 query：alice 命中，bob 绝不命中同一缓存项。
    assert cache.get(alice_key, now=now) is not None
    assert cache.get(bob_key, now=now) is None


@pytest.mark.test_id("RAG-008")
def test_delete_source_invalidates_cache() -> None:
    cache = InMemoryContextCache()
    now = support.now()
    key = _key()
    cache.put(_entry(key, source_refs=("source:1", "source:2")), now=now)
    assert cache.get(key, now=now) is not None
    # RAG-008：来源删除/版本更新 -> 显式失效相关缓存项。
    removed = cache.invalidate_source("source:1")
    assert removed == 1
    assert cache.get(key, now=now) is None


@pytest.mark.test_id("RAG-007")
def test_scope_revocation_invalidates_cache() -> None:
    cache = InMemoryContextCache()
    now = support.now()
    key = _key()
    cache.put(_entry(key), now=now)
    assert cache.get(key, now=now) is not None
    # RAG-007：权限收回 -> 显式失效相关缓存项，绝不继续用旧 ACL 服务。
    removed = cache.invalidate_scope("scope:read")
    assert removed == 1
    assert cache.get(key, now=now) is None


@pytest.mark.test_id("RAG-001")
def test_expired_entry_is_not_served() -> None:
    cache = InMemoryContextCache()
    now = support.now()
    key = _key()
    cache.put(_entry(key), now=now)
    # 超时后不得直接复用于新调用。
    assert cache.get(key, now=now + timedelta(minutes=6)) is None
