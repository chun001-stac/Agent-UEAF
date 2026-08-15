"""Prompt contract compilation (functional module 03, P0-SCH-002)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ueaf.common.meta import ContractMeta


@dataclass(frozen=True, slots=True)
class PromptContract:
    """Instruction version + variable/output schemas + evidence/refusal rules.

    The instruction text and schemas must be jointly reproducible.
    """

    meta: ContractMeta
    prompt_contract_id: str
    instruction_version: str
    variables_schema_ref: str
    output_schema_ref: str
    evidence_rule_ref: str
    refusal_rule_ref: str
    trust_partition_ref: str
    text: str
    default_variables: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.prompt_contract_id != self.meta.object_id:
            raise ValueError("PromptContract.meta.object_id must equal prompt_contract_id")
        if not self.text:
            raise ValueError("PromptContract.text must not be empty")
        if not self.instruction_version:
            raise ValueError("PromptContract.instruction_version must not be empty")


@dataclass(frozen=True, slots=True)
class PromptCompileRequest:
    """Request to compile a prompt for a specific run/turn (frozen before invoke)."""

    request_id: str
    tenant_id: str
    run_id: str
    turn_id: str
    instruction_version: str
    variables_schema_ref: str
    output_schema_ref: str
    variables: Mapping[str, Any] = field(default_factory=dict)
    max_prompt_tokens: int = 8192
    submitted_at: datetime | None = None


class PromptTokenBudgetExceeded(RuntimeError):
    code = "prompt_token_budget_exceeded"


def _estimate_tokens(variables: Mapping[str, Any]) -> int:
    """Deterministic CI estimator: serialized variables / 4 + fixed overhead."""
    serialized = json.dumps(variables, sort_keys=True, ensure_ascii=False)
    return len(serialized) // 4 + 32


class PromptCompiler:
    """Compiles a prompt, enforcing instruction/data isolation and token budget."""

    def __init__(
        self, *, instruction_text: str, producer_version: str = "0.1.0"
    ) -> None:
        self._instruction_text = instruction_text
        self._producer_version = producer_version

    def compile(self, request: PromptCompileRequest) -> PromptContract:
        if request.max_prompt_tokens <= 0:
            raise PromptTokenBudgetExceeded("max_prompt_tokens must be > 0")
        estimated = _estimate_tokens(request.variables)
        if estimated > request.max_prompt_tokens:
            raise PromptTokenBudgetExceeded(
                f"estimated {estimated} tokens exceeds budget {request.max_prompt_tokens}"
            )
        contract_id = f"prompt:{request.run_id}:{request.turn_id}"
        return PromptContract(
            meta=ContractMeta(
                contract_name="PromptContract",
                contract_version="1.0.0",
                object_id=contract_id,
                tenant_id=request.tenant_id,
                created_at=request.submitted_at or datetime.now(UTC),
                producer="ueaf-prompt",
                producer_version=self._producer_version,
                run_id=request.run_id,
                turn_id=request.turn_id,
            ),
            prompt_contract_id=contract_id,
            instruction_version=request.instruction_version,
            variables_schema_ref=request.variables_schema_ref,
            output_schema_ref=request.output_schema_ref,
            evidence_rule_ref="evidence-rule:1",
            refusal_rule_ref="refusal-rule:1",
            trust_partition_ref="trust-partition:1",
            text=self._instruction_text,
            default_variables=dict(request.variables),
        )

