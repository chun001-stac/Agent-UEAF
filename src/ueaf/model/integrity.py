"""调用完整性：Provider Adapter 绝不变异冻结的调用（PRM-010）。

Adapter 不得添加系统提示、启用未批准的工具、更改响应模式或静默切换路由。
``verify_invocation_integrity`` 在观察到任何此类变异时判定一致性检查失败；任何降级
都必须形成新的冻结调用，而不是变异当前调用。
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.ports import ModelInvocation


class InvocationMutationError(ValueError):
    """当 Provider Adapter 变异冻结的调用时抛出（PRM-010）。"""


@dataclass(frozen=True, slots=True)
class InvocationIntegrityResult:
    conformant: bool
    reason_codes: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return not self.conformant


def verify_invocation_integrity(
    request: ModelInvocation,
    *,
    returned_output_schema_ref: str,
    returned_model_route_ref: str,
    added_system_prompt: bool = False,
    enabled_unapproved_tools: tuple[str, ...] = (),
) -> InvocationIntegrityResult:
    """验证 adapter 未变异冻结的调用表面。"""
    reasons: list[str] = []
    if returned_output_schema_ref != request.output_schema_ref:
        reasons.append("output_schema_changed")
    if returned_model_route_ref != request.model_route_ref:
        reasons.append("model_route_changed")
    if added_system_prompt:
        reasons.append("system_prompt_added")
    if enabled_unapproved_tools:
        reasons.append(f"unapproved_tools:{','.join(enabled_unapproved_tools)}")
    return InvocationIntegrityResult(not reasons, tuple(reasons))


def assert_integrity(
    request: ModelInvocation,
    *,
    returned_output_schema_ref: str,
    returned_model_route_ref: str,
    added_system_prompt: bool = False,
    enabled_unapproved_tools: tuple[str, ...] = (),
) -> None:
    """当 adapter 变异调用时抛出 ``InvocationMutationError``。"""
    result = verify_invocation_integrity(
        request,
        returned_output_schema_ref=returned_output_schema_ref,
        returned_model_route_ref=returned_model_route_ref,
        added_system_prompt=added_system_prompt,
        enabled_unapproved_tools=enabled_unapproved_tools,
    )
    if result.failed:
        raise InvocationMutationError(
            f"adapter mutated invocation: {', '.join(result.reason_codes)}"
        )


__all__ = [
    "InvocationMutationError",
    "InvocationIntegrityResult",
    "verify_invocation_integrity",
    "assert_integrity",
]
