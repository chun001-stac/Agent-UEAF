"""候选评审流（功能模块 04 §7，CTX-001/CTX-007）。

submit_candidate 进入待评审（pending_review）→ review_candidate 给出
approved/rejected/needs_review。团队/租户级记忆强制更高审查阈值（低置信度 approved
被降级为 needs_review）；needs_review 可观察、绝不直接晋升。
"""

from __future__ import annotations

import pytest

from tests.memory.helpers import MOMENT, candidate
from ueaf.memory.review import CandidateReviewGate
from ueaf.memory.service import MemoryService


@pytest.mark.test_id("CTX-001")
def test_review_flow_submit_to_approved_then_promote() -> None:
    gate = CandidateReviewGate()
    cand = candidate("cand:1", confidence=0.9)
    submitted = gate.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    assert submitted.status == "pending_review"
    approved = gate.review_candidate(
        "cand:1", decision="approved", reviewed_by="reviewer:1", moment=MOMENT
    )
    assert approved.status == "approved"
    assert gate.approved_candidate("cand:1") is cand

    # 服务端评审后从 approved 候选晋升。
    service = MemoryService()
    service.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate("cand:1", decision="approved", reviewed_by="reviewer:1", moment=MOMENT)
    resolution = service.promote_from_review("cand:1", moment=MOMENT)
    assert resolution.outcome == "promoted"
    assert resolution.record_ref is not None


@pytest.mark.test_id("CTX-001")
def test_review_rejected_is_not_promotable() -> None:
    gate = CandidateReviewGate()
    cand = candidate("cand:2", confidence=0.9)
    gate.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    rejected = gate.review_candidate(
        "cand:2", decision="rejected", reviewed_by="reviewer:1", moment=MOMENT
    )
    assert rejected.status == "rejected"
    assert gate.approved_candidate("cand:2") is None

    service = MemoryService()
    service.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate("cand:2", decision="rejected", reviewed_by="reviewer:1", moment=MOMENT)
    resolution = service.promote_from_review("cand:2", moment=MOMENT)
    assert resolution.outcome == "needs_review"
    assert "not_approved" in resolution.reason_codes


@pytest.mark.test_id("CTX-007")
def test_review_team_tenant_low_confidence_forced_needs_review() -> None:
    gate = CandidateReviewGate(
        approval_threshold=0.8, team_review_threshold=0.95, tenant_review_threshold=0.95
    )
    # 团队级低置信度：即使评审方选择 approved 也会被强制 needs_review（§7）。
    team_low = candidate("cand:3", confidence=0.9, scope_requested="team")
    gate.submit_candidate(team_low, reviewed_by="reviewer:1", moment=MOMENT)
    review = gate.review_candidate(
        "cand:3", decision="approved", reviewed_by="reviewer:1", moment=MOMENT
    )
    assert review.status == "needs_review"
    assert "scope_requires_review" in review.reason_codes
    assert gate.approved_candidate("cand:3") is None

    # 团队级高置信度可通过（更高阈值之上）。
    team_high = candidate("cand:4", confidence=0.97, scope_requested="team")
    gate.submit_candidate(team_high, reviewed_by="reviewer:1", moment=MOMENT)
    review2 = gate.review_candidate(
        "cand:4", decision="approved", reviewed_by="reviewer:1", moment=MOMENT
    )
    assert review2.status == "approved"
    assert gate.approved_candidate("cand:4") is team_high


@pytest.mark.test_id("CTX-007")
def test_review_needs_review_state_observable_and_not_promotable() -> None:
    service = MemoryService()
    cand = candidate("cand:5", confidence=0.9, scope_requested="tenant")
    service.submit_candidate(cand, reviewed_by="reviewer:1", moment=MOMENT)
    service.review_candidate(
        "cand:5", decision="needs_review", reviewed_by="reviewer:1", moment=MOMENT
    )
    status = service.review_status("cand:5")
    assert status is not None
    assert status.status == "needs_review"
    # needs_review 可观察但绝不直接晋升。
    resolution = service.promote_from_review("cand:5", moment=MOMENT)
    assert resolution.outcome == "needs_review"
    assert "not_approved" in resolution.reason_codes
