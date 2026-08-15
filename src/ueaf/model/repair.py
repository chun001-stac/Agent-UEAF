"""Bounded structural repair vs semantic/security no-repair (PRM-007/008).

Recoverable JSON/typed-output structural errors may be repaired with bounded
passes (PRM-007). Semantic or security failures — missing evidence, safety hard
fails, over-scope ToolIntents, business semantic conflicts, unknown providers or
model refusals — must never be "repaired away" by a repair prompt (PRM-008).
"""

from __future__ import annotations

from dataclasses import dataclass

_NON_REPAIRABLE_KINDS: frozenset[str] = frozenset({"refusal", "no_progress", "need_input"})
_NON_REPAIRABLE_FINISH_REASONS: frozenset[str] = frozenset({"content_filter", "tool_calls"})


class NonRepairableFailure(ValueError):
    """A semantic/security failure that must not be repaired (PRM-008)."""


@dataclass(frozen=True, slots=True)
class RepairResult:
    content: str
    repaired: bool
    pass_count: int
    reason_codes: tuple[str, ...] = ()


def is_non_repairable_failure(kind: str, finish_reason: str) -> bool:
    """Semantic/security failures are never structurally repaired (PRM-008)."""
    return kind in _NON_REPAIRABLE_KINDS or finish_reason in _NON_REPAIRABLE_FINISH_REASONS


class StructuralRepairer:
    """Fixes only recoverable structural errors, with a hard pass bound."""

    def __init__(self, *, max_passes: int = 1) -> None:
        if max_passes < 1:
            raise ValueError("max_passes must be >= 1")
        self._max_passes = max_passes

    def repair(
        self, content: str, *, kind: str = "final_response", finish_reason: str = "stop"
    ) -> RepairResult:
        if is_non_repairable_failure(kind, finish_reason):
            raise NonRepairableFailure(f"not repairable: kind={kind} finish={finish_reason}")
        current = content
        passes = 0
        for _ in range(self._max_passes):
            repaired = _repair_truncated_json(current)
            if repaired == current:
                break
            current = repaired
            passes += 1
        return RepairResult(
            content=current,
            repaired=passes > 0,
            pass_count=passes,
            reason_codes=(f"structural_repair_passes:{passes}",) if passes else (),
        )


def _repair_truncated_json(content: str) -> str:
    """Close unclosed JSON structural delimiters (recoverable truncation)."""
    if not content.strip():
        return content
    stripped = content.rstrip()
    open_braces = stripped.count("{") - stripped.count("}")
    open_brackets = stripped.count("[") - stripped.count("]")
    if open_braces < 0 or open_brackets < 0:
        return stripped  # malformed beyond a simple truncation -> not repairable
    return stripped + "}" * open_braces + "]" * open_brackets


__all__ = [
    "StructuralRepairer",
    "RepairResult",
    "NonRepairableFailure",
    "is_non_repairable_failure",
]
