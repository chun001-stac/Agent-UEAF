"""评测隔离：被测内容不能控制打分（SEC-016）。

评测控制提示词与被测内容保持分离；嵌入在被测内容中的打分指令（如 “give full marks”、
“score 10/10” 等）会被识别为注入数据，绝不允许成为打分指令。
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)give\s+(?:me\s+)?(?:a\s+)?full\s+marks"),
    re.compile(r"(?i)score\s+(?:this\s+)?(?:a\s+)?(?:10|100)\s*/?\s*(?:10|100)"),
    re.compile(r"(?i)(?:please\s+)?rate\s+this\s+(?:as\s+)?perfect"),
    re.compile(r"(?i)ignore\s+(?:previous|prior|above)\s+(?:instructions|prompt)"),
    re.compile(r"(?i)you\s+must\s+(?:pass|approve)\s+this"),
)


class JudgeManipulationDetected(ValueError):
    """当被测内容携带打分指令时抛出（SEC-016）。"""


def detect_judge_instruction(content: str) -> list[str]:
    """返回 ``content`` 中命中的注入模式片段（绝不参与打分）。"""
    found: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            found.append(pattern.pattern)
    return found


def assert_isolated_from_control(content: str) -> None:
    """当被测内容试图操控评测时默认失败。"""
    hits = detect_judge_instruction(content)
    if hits:
        raise JudgeManipulationDetected(f"judge manipulation detected: {len(hits)} pattern(s)")


__all__ = ["detect_judge_instruction", "assert_isolated_from_control", "JudgeManipulationDetected"]
