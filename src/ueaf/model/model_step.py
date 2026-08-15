"""ModelStepPort reference implementation with a deterministic CI fake model.

Prompt/Context/ModelRoute/output schema are frozen before invocation; only the
final ``StructuredDecision`` returned by the port is authoritative (stream
fragments are never treated as decisions).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.ports import (
    ModelInvocation,
    PortError,
    PortResult,
    Rejected,
    StructuredDecision,
    Success,
)

DecisionKind = Literal[
    "final_response", "tool_intents", "handoff", "need_input", "refusal", "no_progress"
]
VALID_KINDS: frozenset[str] = frozenset(
    {"final_response", "tool_intents", "handoff", "need_input", "refusal", "no_progress"}
)

_DECISION_SCHEMA_REF = "schema://structured-decision/1.0.0"


@dataclass(frozen=True, slots=True)
class FakeModelResult:
    """Deterministic provider result used in CI (never a live provider)."""

    kind: DecisionKind
    content: str = ""
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"] = "stop"
    usage_tokens: int = 0


class DeterministicFakeModel:
    """Maps a frozen ModelInvocation to a deterministic result.

    A pluggable ``policy`` callable lets tests script outcomes (refusal, tool
    intents, no_progress, etc.) without any network access.
    """

    def __init__(
        self,
        policy: Callable[[ModelInvocation], FakeModelResult] | None = None,
    ) -> None:
        self._policy = policy or (
            lambda invocation: FakeModelResult(kind="final_response", content="ok")
        )

    def invoke(self, request: ModelInvocation) -> FakeModelResult:
        result = self._policy(request)
        if result.kind not in VALID_KINDS:
            raise ValueError(f"invalid decision kind {result.kind!r}")
        return result


class ModelStep:
    """Implements the core ModelStepPort contract (typed invoke)."""

    def __init__(self, model: DeterministicFakeModel, *, output_schema_ref: str) -> None:
        self._model = model
        self._output_schema_ref = output_schema_ref

    def invoke(self, request: ModelInvocation) -> PortResult[StructuredDecision]:
        if request.output_schema_ref != self._output_schema_ref:
            return Rejected(
                PortError(
                    code="output_schema_mismatch",
                    category="validation",
                    retryability="never",
                    certainty="not_executed",
                    message_ref=None,
                    provider_error_ref=None,
                    observed_at=request.deadline_at,
                    details_schema_ref=None,
                )
            )
        try:
            provider = self._model.invoke(request)
        except ValueError as error:
            return Rejected(
                PortError(
                    code="invalid_model_outcome",
                    category="provider",
                    retryability="never",
                    certainty="not_executed",
                    message_ref=None,
                    provider_error_ref=str(error),
                    observed_at=request.deadline_at,
                    details_schema_ref=None,
                )
            )

        decision = StructuredDecision(
            structured_decision_id=new_object_id("decision"),
            run_id=request.run_id,
            turn_id=self._turn_id_from(request),
            kind=provider.kind,
            schema_ref=_DECISION_SCHEMA_REF,
            validation_result_ref=f"validation:{sha256_hex(provider.content)[:16]}",
            source_model_result_ref=f"model-result:{request.model_invocation_id}",
        )
        return Success(decision)

    @staticmethod
    def _turn_id_from(request: ModelInvocation) -> str:
        # ModelInvocation carries no turn_id in the core SPI; derive deterministically.
        return f"turn:{request.run_id}:{sha256_hex(request.prompt_contract_ref)[:8]}"
