"""Route capacity gate: a frozen ContextManifest is never mutated (PRM-006).

Module 03 (Model/Prompt) selects a route; if that route cannot fit the already
frozen ContextManifest produced by Module 04, the request fails with a
structured budget problem instead of truncating or rewriting the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.ports import ContextManifest


@dataclass(frozen=True, slots=True)
class RouteCapacityDecision:
    accepted: bool
    route_capacity_tokens: int
    required_tokens: int
    reason_codes: tuple[str, ...] = ()

    @property
    def rejected(self) -> bool:
        return not self.accepted


def estimate_manifest_tokens(manifest: ContextManifest) -> int:
    """Deterministic token estimate for a frozen manifest (never mutated)."""
    return 64 + len(manifest.evidence_pack_refs) * 24 + len(manifest.integrity_ref or "")


class RouteCapacityGate:
    """Checks a route can fit the frozen manifest; manifest is read-only (PRM-006)."""

    def __init__(self, *, reserve_tokens: int = 128) -> None:
        self._reserve_tokens = reserve_tokens

    def evaluate(
        self, manifest: ContextManifest, *, route_capacity_tokens: int
    ) -> RouteCapacityDecision:
        required = estimate_manifest_tokens(manifest) + self._reserve_tokens
        if required > route_capacity_tokens:
            return RouteCapacityDecision(
                False,
                route_capacity_tokens,
                required,
                ("route_cannot_fit_frozen_manifest",),
            )
        return RouteCapacityDecision(True, route_capacity_tokens, required, ("fit",))


__all__ = ["RouteCapacityGate", "RouteCapacityDecision", "estimate_manifest_tokens"]
