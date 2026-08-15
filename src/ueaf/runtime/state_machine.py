"""Run state machine (core spec 02 §5.1).

Encodes the closed transition matrix. Any transition not listed is rejected as
``invalid_state_transition`` (never guessed from logs).
"""

from __future__ import annotations

from typing import Final

from ueaf.runtime.objects import RunPhase

_TRANSITIONS: Final[dict[RunPhase, frozenset[RunPhase]]] = {
    "queued": frozenset({"admitting", "terminal"}),
    "admitting": frozenset({"running", "waiting", "terminal"}),
    "running": frozenset({"waiting", "retrying", "paused", "terminal"}),
    "waiting": frozenset({"admitting", "running", "retrying", "paused", "terminal"}),
    "retrying": frozenset({"running", "waiting", "paused", "terminal"}),
    "paused": frozenset({"admitting", "running", "terminal"}),
    "terminal": frozenset(),
}

# Terminal dispositions accepted per command origin (spec 02 §5.1).
TERMINAL_ON_CANCEL: frozenset[str] = frozenset({"cancelled"})
TERMINAL_ON_ADMISSION_REJECT: frozenset[str] = frozenset({"rejected"})
TERMINAL_ON_ADMISSION_FATAL: frozenset[str] = frozenset({"failed"})


class StateMachineError(RuntimeError):
    """Raised when a run/action transition violates the closed state machine."""

    code = "invalid_state_transition"

    def __init__(self, from_phase: str, to_phase: str, detail: str = "") -> None:
        self.from_phase = from_phase
        self.to_phase = to_phase
        message = f"invalid_state_transition: {from_phase} -> {to_phase}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


def validate_transition(from_phase: RunPhase, to_phase: RunPhase) -> None:
    """Raise ``StateMachineError`` unless the transition is listed."""
    if from_phase not in _TRANSITIONS:
        raise StateMachineError(from_phase, to_phase, f"unknown from phase {from_phase!r}")
    if to_phase not in _TRANSITIONS[from_phase]:
        raise StateMachineError(from_phase, to_phase)


def can_transition(from_phase: RunPhase, to_phase: RunPhase) -> bool:
    return to_phase in _TRANSITIONS.get(from_phase, frozenset())
