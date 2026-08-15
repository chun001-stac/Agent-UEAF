"""DLP result minimization (SEC-015).

Tool/RAG output may contain sensitive fields beyond the request purpose.
``DLPResultMinimizer`` trims or blocks those fields; a prompt or judge can
never override the minimization decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DLPDecision:
    allowed: bool
    reason_codes: tuple[str, ...] = ()
    trimmed_keys: tuple[str, ...] = ()


# Sensitivity tiers: internal/confidential/restricted fields need a purpose.
_PURPOSE_SENSITIVE: frozenset[str] = frozenset(
    {
        "ssn",
        "passport",
        "bank_account",
        "card_number",
        "medical",
        "salary",
        "personal_email",
        "phone",
        "internal_id",
        "staff_id",
    }
)


class DLPResultMinimizer:
    """Trims out-of-purpose sensitive fields from Tool/RAG results (SEC-015)."""

    def __init__(self, *, sensitive_keys: frozenset[str] | None = None) -> None:
        self._sensitive = (
            frozenset(sensitive_keys) if sensitive_keys is not None else _PURPOSE_SENSITIVE
        )

    def minimize(
        self, result: Mapping[str, Any], *, purpose: str, allowed_sensitive: tuple[str, ...] = ()
    ) -> DLPDecision:
        allowed = set(allowed_sensitive)
        trimmed: list[str] = []
        for key in result:
            if str(key).lower() in self._sensitive and str(key) not in allowed:
                trimmed.append(str(key))
        if trimmed:
            return DLPDecision(False, ("sensitive_fields_outside_purpose",), tuple(trimmed))
        return DLPDecision(True, ("allowed",))

    def trim(
        self, result: Mapping[str, Any], *, purpose: str, allowed_sensitive: tuple[str, ...] = ()
    ) -> tuple[dict[str, Any], DLPDecision]:
        """Return the minimized payload (sensitive fields dropped)."""
        allowed = set(allowed_sensitive)
        minimized: dict[str, Any] = {}
        trimmed: list[str] = []
        for key, value in result.items():
            if str(key).lower() in self._sensitive and str(key) not in allowed:
                trimmed.append(str(key))
                continue
            minimized[str(key)] = value
        decision = DLPDecision(
            False if trimmed else True,
            ("sensitive_fields_outside_purpose",) if trimmed else ("allowed",),
            tuple(trimmed),
        )
        return minimized, decision


__all__ = ["DLPResultMinimizer", "DLPDecision"]
