"""MemoryResolution 三态 + 理由码 + record 引用（功能模块 04 §4.5，CTX-001/CTX-007）。

``MemoryResolution`` 是模块内部派生对象，不是 Run 终态决定：它只表达一次候选治理的
结果（promoted/rejected/needs_review），绝不改变 Run 终态。
"""

from __future__ import annotations

import pytest

from ueaf.memory.resolution import (
    REASON_CONFLICT,
    REASON_CONSENT_REQUIRED,
    REASON_DUPLICATE,
    MemoryResolution,
)


@pytest.mark.test_id("CTX-001")
def test_resolution_promoted_carries_record_ref() -> None:
    resolution = MemoryResolution(
        outcome="promoted", reason_codes=(), record_ref="memory:1", candidate_ref="cand:1"
    )
    assert resolution.outcome == "promoted"
    assert resolution.reason_codes == ()
    assert resolution.record_ref == "memory:1"
    assert resolution.candidate_ref == "cand:1"


@pytest.mark.test_id("CTX-001")
def test_resolution_rejected_carries_reason_codes() -> None:
    resolution = MemoryResolution(
        outcome="rejected", reason_codes=(REASON_CONSENT_REQUIRED,), candidate_ref="cand:1"
    )
    assert resolution.outcome == "rejected"
    assert REASON_CONSENT_REQUIRED in resolution.reason_codes
    assert resolution.record_ref is None


@pytest.mark.test_id("CTX-007")
def test_resolution_needs_review_is_observable_not_terminal() -> None:
    resolution = MemoryResolution(
        outcome="needs_review",
        reason_codes=(REASON_CONFLICT, REASON_DUPLICATE),
        candidate_ref="cand:1",
    )
    assert resolution.outcome == "needs_review"
    assert set(resolution.reason_codes) == {REASON_CONFLICT, REASON_DUPLICATE}
    assert resolution.record_ref is None
    # 不是 Run 终态决定：outcome 与 Run 终态正交（§4.5）。
    assert resolution.outcome in ("promoted", "rejected", "needs_review")
