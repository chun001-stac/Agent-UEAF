"""生成代码沙箱：默认失败的执行边界（SEC-018）。

R4 生成的代码可能尝试文件逃逸、外联网络、读取密钥或进程逃逸。``GeneratedCodeSandbox``
对受检操作进行建模并默认失败：任何不允许的操作都会产生一条 Security 证据引用和一次
硬性 SecurityGate 失败。
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
    """生成代码的默认失败沙箱策略（SEC-018）。"""

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
        """任一沙箱检查被拒绝时硬性失败（默认失败）。"""
        return "fail" if any(not c.allowed for c in checks) else "pass"


__all__ = ["GeneratedCodeSandbox", "SandboxCheck"]
