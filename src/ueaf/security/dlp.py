"""DLP 结果最小化（SEC-015）。

工具/RAG 输出可能包含超出请求目的范围的敏感字段。``DLPResultMinimizer`` 会裁剪或阻止
这些字段；提示词或评测永远不能覆盖最小化决策。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DLPDecision:
    allowed: bool
    reason_codes: tuple[str, ...] = ()
    trimmed_keys: tuple[str, ...] = ()


# 敏感级别：internal/confidential/restricted 字段需要目的说明。
_PURPOSE_SENSITIVE: frozenset[str] = frozenset(
    {
        "ssn",
        "passport",
        "bank_account",
        "card_number",
        "medical",
        "salary",
        "personal_email",
        "phone",
        "internal_id",
        "staff_id",
    }
)


class DLPResultMinimizer:
    """从工具/RAG 结果中裁剪超出目的范围的敏感字段（SEC-015）。"""

    def __init__(self, *, sensitive_keys: frozenset[str] | None = None) -> None:
        self._sensitive = (
            frozenset(sensitive_keys) if sensitive_keys is not None else _PURPOSE_SENSITIVE
        )

    def minimize(
        self, result: Mapping[str, Any], *, purpose: str, allowed_sensitive: tuple[str, ...] = ()
    ) -> DLPDecision:
        allowed = set(allowed_sensitive)
        trimmed: list[str] = []
        for key in result:
            if str(key).lower() in self._sensitive and str(key) not in allowed:
                trimmed.append(str(key))
        if trimmed:
            return DLPDecision(False, ("sensitive_fields_outside_purpose",), tuple(trimmed))
        return DLPDecision(True, ("allowed",))

    def trim(
        self, result: Mapping[str, Any], *, purpose: str, allowed_sensitive: tuple[str, ...] = ()
    ) -> tuple[dict[str, Any], DLPDecision]:
        """返回最小化后的载荷（丢弃敏感字段）。"""
        allowed = set(allowed_sensitive)
        minimized: dict[str, Any] = {}
        trimmed: list[str] = []
        for key, value in result.items():
            if str(key).lower() in self._sensitive and str(key) not in allowed:
                trimmed.append(str(key))
                continue
            minimized[str(key)] = value
        decision = DLPDecision(
            False if trimmed else True,
            ("sensitive_fields_outside_purpose",) if trimmed else ("allowed",),
            tuple(trimmed),
        )
        return minimized, decision


__all__ = ["DLPResultMinimizer", "DLPDecision"]
