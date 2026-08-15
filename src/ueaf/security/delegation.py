"""Delegation scopes can only narrow after Handoff/Resume/Retry (SEC-002).

A handoff, resume or retry may grant the target a subset of the caller's
scopes — never a superset. ``narrow_scopes`` rejects any attempt to widen the
effective scope set.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DelegationScope:
    """A single permission scope bound to a tenant."""

    tenant_id: str
    scope: str


class ScopeWideningError(ValueError):
    """Raised when a delegation would widen the original scopes (SEC-002)."""


def narrow_scopes(
    original: frozenset[str], granted: frozenset[str]
) -> frozenset[str]:
    """Return the granted scopes, requiring they stay within the original set.

    Handoff/Resume/Retry must only keep or narrow scopes; any granted scope not
    present in the original set is a widening attempt and is rejected.
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
    """Narrow, or return the original set when nothing is granted."""
    if not granted:
        return original
    return narrow_scopes(original, granted)


__all__ = ["DelegationScope", "ScopeWideningError", "narrow_scopes", "delegation_scopes"]
