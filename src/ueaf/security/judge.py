"""Judge isolation: measured content cannot control scoring (SEC-016).

Judge control prompts and the measured content are kept separate; scoring
instructions embedded in the measured content ("give full marks", "score 10/10",
...) are detected as injection data and must never become scoring directives.
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
    """Raised when measured content carries scoring instructions (SEC-016)."""


def detect_judge_instruction(content: str) -> list[str]:
    """Return matched injection pattern fragments in ``content`` (never scored)."""
    found: list[str] = []
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(content):
            found.append(pattern.pattern)
    return found


def assert_isolated_from_control(content: str) -> None:
    """Fail closed when the measured content tries to steer the judge."""
    hits = detect_judge_instruction(content)
    if hits:
        raise JudgeManipulationDetected(f"judge manipulation detected: {len(hits)} pattern(s)")


__all__ = ["detect_judge_instruction", "assert_isolated_from_control", "JudgeManipulationDetected"]
