"""ContextCache：授权感知缓存（RAG-001/RAG-007/RAG-008）。

缓存键至少包含 tenant、授权范围摘要、purpose、查询摘要、来源版本、策略版本
与地域，并且必须绑定主体——禁止只按自然语言 query 跨主体复用（RAG-001：
未授权内容永不进入缓存）。删除来源（RAG-008）或权限收回（RAG-007）都会
显式使相关缓存项失效；超时后缓存项不可直接复用于新调用。本模块提供内存实现
与模块内 SPI（不在核心 ``ports.py`` 注册，仅 context 模块内部使用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


def cache_key(
    *,
    tenant_id: str,
    scope_summary: str,
    purpose: str,
    query_digest: str,
    source_versions_digest: str,
    policy_version: str,
    region: str,
    principal_ref: str,
) -> str:
    """稳定缓存键：主体/租户/授权范围/用途/查询/版本/地域全部参与。

    跨主体的相同自然语言 query 会产生不同的键，绝不会命中同一不安全缓存项。
    """
    return "|".join(
        [
            tenant_id,
            scope_summary,
            purpose,
            query_digest,
            source_versions_digest,
            policy_version,
            region,
            principal_ref,
        ]
    )


@dataclass(frozen=True, slots=True)
class CachedEvidence:
    """授权缓存项（模块内部派生对象，非持久化规范对象）。"""

    cache_key: str
    evidence_pack_ref: str
    source_refs: tuple[str, ...]
    scope_ref: str
    expires_at: datetime


class ContextCachePort(Protocol):
    """模块内授权感知缓存 SPI（不在核心 ports.py 注册）。"""

    def get(self, key: str, *, now: datetime) -> CachedEvidence | None: ...
    def put(self, evidence: CachedEvidence, *, now: datetime) -> None: ...
    def invalidate_source(self, source_ref: str) -> int: ...
    def invalidate_scope(self, scope_ref: str) -> int: ...


class InMemoryContextCache:
    """内存授权感知缓存：键含主体/范围/用途/版本，失效显式传播。"""

    def __init__(self) -> None:
        self._entries: dict[str, CachedEvidence] = {}
        self._by_source: dict[str, set[str]] = {}
        self._by_scope: dict[str, set[str]] = {}

    def get(self, key: str, *, now: datetime) -> CachedEvidence | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if now >= entry.expires_at:
            self._remove(key)
            return None
        return entry

    def put(self, evidence: CachedEvidence, *, now: datetime) -> None:
        del now
        self._entries[evidence.cache_key] = evidence
        self._by_source.setdefault(evidence.scope_ref, set())
        for source in evidence.source_refs:
            self._by_source.setdefault(source, set()).add(evidence.cache_key)
        self._by_scope.setdefault(evidence.scope_ref, set()).add(evidence.cache_key)

    def invalidate_source(self, source_ref: str) -> int:
        """删除传播（RAG-008）：来源删除/版本更新时显式失效相关缓存项。"""
        keys = self._by_source.pop(source_ref, set())
        for key in keys:
            self._remove(key)
        return len(keys)

    def invalidate_scope(self, scope_ref: str) -> int:
        """权限收回传播（RAG-007）：授权范围变化时显式失效相关缓存项。"""
        keys = self._by_scope.pop(scope_ref, set())
        for key in keys:
            self._remove(key)
        return len(keys)

    def _remove(self, key: str) -> None:
        self._entries.pop(key, None)
        for index in (self._by_source, self._by_scope):
            for refs in index.values():
                refs.discard(key)


__all__ = ["ContextCachePort", "InMemoryContextCache", "CachedEvidence", "cache_key"]
