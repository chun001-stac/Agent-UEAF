"""有界结构修复 vs 语义/安全不修复（PRM-007/008）。

可恢复的 JSON/类型化输出结构错误可以通过有界的轮次进行修复（PRM-007）。语义或安全
失败——证据缺失、安全硬失败、超出范围的 ToolIntent、业务语义冲突、未知提供方或模型
拒答——绝不允许通过修复提示词“修复掉”（PRM-008）。
"""

from __future__ import annotations

from dataclasses import dataclass

_NON_REPAIRABLE_KINDS: frozenset[str] = frozenset({"refusal", "no_progress", "need_input"})
_NON_REPAIRABLE_FINISH_REASONS: frozenset[str] = frozenset({"content_filter", "tool_calls"})


class NonRepairableFailure(ValueError):
    """不得修复的语义/安全失败（PRM-008）。"""


@dataclass(frozen=True, slots=True)
class RepairResult:
    content: str
    repaired: bool
    pass_count: int
    reason_codes: tuple[str, ...] = ()


def is_non_repairable_failure(kind: str, finish_reason: str) -> bool:
    """语义/安全失败绝不进行结构修复（PRM-008）。"""
    return kind in _NON_REPAIRABLE_KINDS or finish_reason in _NON_REPAIRABLE_FINISH_REASONS


class StructuralRepairer:
    """仅修复可恢复的结构错误，并带有硬性轮次上限。"""

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
    """闭合未闭合的 JSON 结构定界符（可恢复的截断）。"""
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
