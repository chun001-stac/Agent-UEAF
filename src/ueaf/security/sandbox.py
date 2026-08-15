"""Generated code sandbox: fail-closed execution boundary (SEC-018).

R4 generated code may attempt file escapes, outbound network, secret reads or
process escape. ``GeneratedCodeSandbox`` models the checked operations and
fails closed: any disallowed operation produces a Security evidence ref and a
hard SecurityGate failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ueaf.eval.eval import GateOutcome


@dataclass(frozen=True, slots=True)
class SandboxCheck:
    allowed: bool
    operation: str
    detail: str = ""
    security_evidence_ref: str | None = None


@dataclass(slots=True)
class GeneratedCodeSandbox:
    """Fail-closed sandbox policy for generated code (SEC-018)."""

    allowed_operations: frozenset[str] = field(
        default_factory=lambda: frozenset({"pure_compute", "append_output"})
    )
    evidence_ref_prefix: str = "evidence:sandbox"

    def check(self, operation: str, *, detail: str = "") -> SandboxCheck:
        if operation not in self.allowed_operations:
            return SandboxCheck(
                allowed=False,
                operation=operation,
                detail=detail,
                security_evidence_ref=f"{self.evidence_ref_prefix}:{operation}",
            )
        return SandboxCheck(allowed=True, operation=operation)

    def security_gate_outcome(self, checks: list[SandboxCheck]) -> GateOutcome:
        """Hard fail when any sandbox check is denied (fail closed)."""
        return "fail" if any(not c.allowed for c in checks) else "pass"


__all__ = ["GeneratedCodeSandbox", "SandboxCheck"]
