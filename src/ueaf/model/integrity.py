"""Invocation integrity: a Provider Adapter never mutates the frozen invocation (PRM-010).

An adapter may not add a system prompt, enable unapproved tools, change the
response schema or silently switch routes. ``verify_invocation_integrity`` fails
the conformance check when any such mutation is observed; any fallback must form
a new frozen invocation rather than mutate the current one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ueaf.ports import ModelInvocation


class InvocationMutationError(ValueError):
    """Raised when a Provider Adapter mutates the frozen invocation (PRM-010)."""


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
    """Verify an adapter did not mutate the frozen invocation surface."""
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
    """Raise ``InvocationMutationError`` when the adapter mutates the invocation."""
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
