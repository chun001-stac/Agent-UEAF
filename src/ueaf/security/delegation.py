"""委托范围在 Handoff/Resume/Retry 之后只能收窄（SEC-002）。

交接（handoff）、恢复（resume）或重试（retry）只能授予目标对象调用者范围的一个子集，
绝不能是超集。``narrow_scopes`` 拒绝任何扩大有效范围集的尝试。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DelegationScope:
    """绑定到租户的单个权限范围。"""

    tenant_id: str
    scope: str


class ScopeWideningError(ValueError):
    """当委托会扩大原始范围时抛出（SEC-002）。"""


def narrow_scopes(
    original: frozenset[str], granted: frozenset[str]
) -> frozenset[str]:
    """返回授予的范围，要求其保持在原始集合之内。

    Handoff/Resume/Retry 只能保持或收窄范围；任何不在原始集合中的授予范围都属于
    扩大范围的尝试，将被拒绝。
    """
    widened = granted - original
    if widened:
        raise ScopeWideningError(
            f"delegation widened scopes beyond original: {sorted(widened)}"
        )
    return frozenset(granted)


def delegation_scopes(
    original: frozenset[str], granted: frozenset[str]
) -> frozenset[str]:
    """收窄范围；当未授予任何内容时返回原始集合。"""
    if not granted:
        return original
    return narrow_scopes(original, granted)


__all__ = ["DelegationScope", "ScopeWideningError", "narrow_scopes", "delegation_scopes"]
