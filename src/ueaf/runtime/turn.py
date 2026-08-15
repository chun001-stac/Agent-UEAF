"""Turn lifecycle (core spec 01 §9.2, functional module 02 §4.4).

A ``TurnRecord`` captures one model observation -> decision -> result exchange
within a Run. Streaming and non-streaming paths normalize to the same terminal
semantics; only the final StructuredDecision is authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ueaf.common.meta import ContractMeta

TurnOutcome = Literal[
    "final_response", "tool_intents", "handoff", "need_input", "refusal", "no_progress"
]


@dataclass(frozen=True, slots=True)
class TurnRecord:
    """One authoritative model exchange inside a run."""

    meta: ContractMeta
    turn_id: str
    run_id: str
    turn_no: int
    context_manifest_ref: str
    prompt_contract_ref: str
    output_schema_ref: str
    model_route_ref: str
    model_invocation_ref: str
    model_run_result_ref: str | None = None
    structured_decision_ref: str | None = None
    tool_intent_refs: tuple[str, ...] = ()
    outcome: TurnOutcome | None = None
    stop_reason: Literal["stop", "length", "tool_calls", "content_filter"] | None = None
    usage_tokens: int = 0
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.turn_id != self.meta.object_id:
            raise ValueError("TurnRecord.meta.object_id must equal turn_id")
        if self.turn_no < 1:
            raise ValueError("TurnRecord.turn_no must be >= 1")


class InMemoryTurnRegistry:
    """Turn append-only store (authoritative per-run turn sequence)."""

    def __init__(self) -> None:
        self._turns: dict[str, TurnRecord] = {}
        self._by_run: dict[str, list[TurnRecord]] = {}

    def add(self, turn: TurnRecord) -> TurnRecord:
        if turn.turn_id in self._turns:
            raise ValueError(f"TurnRecord {turn.turn_id} already exists")
        self._turns[turn.turn_id] = turn
        self._by_run.setdefault(turn.run_id, []).append(turn)
        return turn

    def get(self, turn_id: str) -> TurnRecord | None:
        return self._turns.get(turn_id)

    def for_run(self, run_id: str) -> list[TurnRecord]:
        return list(self._by_run.get(run_id, []))
