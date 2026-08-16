"""提示词合约编译（功能模块 03，P0-SCH-002）。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ueaf.common.meta import ContractMeta


@dataclass(frozen=True, slots=True)
class PromptContract:
    """指令版本 + 变量/输出模式 + 证据/拒答规则。

    指令文本与模式必须可共同复现。
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
    """为特定 run/turn 编译提示词的请求（调用前冻结）。"""

    request_id: str
    tenant_id: str
    run_id: str
    turn_id: str
    instruction_version: str
    variables_schema_ref: str
    output_schema_ref: str
    variables: Mapping[str, Any] = field(default_factory=dict)
    max_prompt_tokens: int = 8192
    # 输入绝不可挤占的预留（PRM-005）：输出、能力、提供方包装与安全预留
    # 留给后续阶段使用。
    output_reserve_tokens: int = 0
    capability_reserve_tokens: int = 0
    provider_wrapper_reserve_tokens: int = 0
    safety_reserve_tokens: int = 0
    submitted_at: datetime | None = None


class PromptTokenBudgetExceeded(RuntimeError):
    code = "prompt_token_budget_exceeded"


def _estimate_tokens(variables: Mapping[str, Any]) -> int:
    """确定性 CI 估算器：序列化变量长度 / 4 + 固定开销。"""
    serialized = json.dumps(variables, sort_keys=True, ensure_ascii=False)
    return len(serialized) // 4 + 32


class PromptCompiler:
    """编译提示词，强制执行指令/数据隔离与 token 预算。"""

    def __init__(self, *, instruction_text: str, producer_version: str = "0.1.0") -> None:
        self._instruction_text = instruction_text
        self._producer_version = producer_version

    def compile(self, request: PromptCompileRequest) -> PromptContract:
        if request.max_prompt_tokens <= 0:
            raise PromptTokenBudgetExceeded("max_prompt_tokens must be > 0")
        estimated = _estimate_tokens(request.variables)
        total_reserve = (
            request.output_reserve_tokens
            + request.capability_reserve_tokens
            + request.provider_wrapper_reserve_tokens
            + request.safety_reserve_tokens
        )
        # PRM-005：输入绝不可挤占输出/能力/安全预留。
        if estimated + total_reserve > request.max_prompt_tokens:
            raise PromptTokenBudgetExceeded(
                "estimated {estimated + total_reserve} tokens (incl. reserves) "
                f"exceeds budget {request.max_prompt_tokens}"
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
