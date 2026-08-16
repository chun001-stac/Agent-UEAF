"""候选评审流（功能模块 04 §7 多租户与安全）。

候选提交后进入待评审（``pending_review``），评审给出 ``approved/rejected/needs_review``。
团队/租户级（``scope_requested`` 为 ``team/tenant``）记忆使用更高审查阈值：低置信度的
``approved`` 会被强制降级为 ``needs_review``（§7）。``needs_review`` 状态可观察、绝不
直接晋升（CTX-001 记忆语义 / CTX-007：04 只在授权评审通过后重建/晋升）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ueaf.common.identifiers import utcnow
from ueaf.memory.objects import MemoryCandidate
from ueaf.memory.resolution import REASON_SCOPE_REQUIRES_REVIEW

ReviewDecision = Literal["approved", "rejected", "needs_review"]
ReviewStatus = Literal["pending_review", "approved", "rejected", "needs_review"]

TEAM_SCOPES = ("team", "tenant")


@dataclass(frozen=True, slots=True)
class CandidateReview:
    """一次候选评审的当前状态（模块内部派生对象，非持久化规范对象）。"""

    candidate_ref: str
    status: ReviewStatus
    reviewed_by: str
    reviewed_at: datetime
    reason_codes: tuple[str, ...] = ()
    note: str | None = None


class CandidateReviewGate:
    """候选评审流：``submit_candidate`` -> ``review_candidate``。

    团队/租户级记忆强制更高审查阈值：即使评审方选择 ``approved``，只要候选置信度低于
    对应阈值，结果仍为 ``needs_review``（§7）。只有 ``approved`` 的候选可被晋升
    （``approved_candidate``），``needs_review`` 可观察但绝不直接晋升。
    """

    def __init__(
        self,
        *,
        approval_threshold: float = 0.8,
        team_review_threshold: float = 0.95,
        tenant_review_threshold: float = 0.95,
    ) -> None:
        if not (0.0 <= approval_threshold <= 1.0):
            raise ValueError("approval_threshold must be within [0, 1]")
        if not (0.0 <= team_review_threshold <= 1.0):
            raise ValueError("team_review_threshold must be within [0, 1]")
        if not (0.0 <= tenant_review_threshold <= 1.0):
            raise ValueError("tenant_review_threshold must be within [0, 1]")
        self._approval_threshold = approval_threshold
        self._team_threshold = team_review_threshold
        self._tenant_threshold = tenant_review_threshold
        self._reviews: dict[str, CandidateReview] = {}
        self._candidates: dict[str, MemoryCandidate] = {}

    def submit_candidate(
        self,
        candidate: MemoryCandidate,
        *,
        reviewed_by: str,
        moment: datetime | None = None,
    ) -> CandidateReview:
        """登记一个候选进入待评审；重复提交被拒绝。"""
        if candidate.candidate_id in self._reviews:
            raise ValueError(f"candidate {candidate.candidate_id} already submitted")
        review = CandidateReview(
            candidate_ref=candidate.candidate_id,
            status="pending_review",
            reviewed_by=reviewed_by,
            reviewed_at=moment or utcnow(),
        )
        self._reviews[candidate.candidate_id] = review
        self._candidates[candidate.candidate_id] = candidate
        return review

    def review_candidate(
        self,
        candidate_ref: str,
        *,
        decision: ReviewDecision,
        reviewed_by: str,
        note: str = "",
        moment: datetime | None = None,
    ) -> CandidateReview:
        """给出评审决定；团队/租户级低置信度 approved 会被强制降级为 needs_review。"""
        current = self._reviews.get(candidate_ref)
        if current is None:
            raise ValueError(f"unknown candidate {candidate_ref!r} in review gate")
        candidate = self._candidates[candidate_ref]
        moment = moment or utcnow()

        status: ReviewStatus = decision
        reason_codes: list[str] = []
        if decision == "approved":
            threshold = self._threshold_for(candidate)
            if candidate.confidence < threshold:
                # 团队/租户级记忆需要更高审查阈值（§7）：低置信度不可直接批准。
                status = "needs_review"
                reason_codes.append(REASON_SCOPE_REQUIRES_REVIEW)

        review = CandidateReview(
            candidate_ref=candidate_ref,
            status=status,
            reviewed_by=reviewed_by,
            reviewed_at=moment,
            reason_codes=tuple(reason_codes),
            note=note or None,
        )
        self._reviews[candidate_ref] = review
        return review

    def status(self, candidate_ref: str) -> CandidateReview | None:
        """评审状态可观察（含 needs_review），供治理与告警使用。"""
        return self._reviews.get(candidate_ref)

    def approved_candidate(self, candidate_ref: str) -> MemoryCandidate | None:
        """仅返回已 approved 的候选；needs_review/rejected/pending 均返回 None。"""
        review = self._reviews.get(candidate_ref)
        if review is None or review.status != "approved":
            return None
        return self._candidates[candidate_ref]

    def _threshold_for(self, candidate: MemoryCandidate) -> float:
        scope = candidate.scope_requested or candidate.purpose
        if scope == "tenant":
            return self._tenant_threshold
        if scope == "team":
            return self._team_threshold
        return self._approval_threshold


__all__ = [
    "CandidateReview",
    "CandidateReviewGate",
    "ReviewDecision",
    "ReviewStatus",
    "TEAM_SCOPES",
]
