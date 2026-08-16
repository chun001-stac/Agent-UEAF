"""记忆治理规则（功能模块 04 §5.3 / §7 / §8，核心规范 01 §10.2）。

去重与冲突检测绝不以后写覆盖：重复候选被拒绝（RAG-011），冲突候选被隔离为
``needs_review`` 或记录并列观点（CTX-006 / RAG-012），最后写入绝不可能静默覆盖已确认
记录。更正链（``correct``）创建新版本并使旧记录 ``superseded``（§5.3 / CTX-004 /
CTX-005 谱系）。保留期由 ``retention_hint`` 经 ``RetentionPolicy`` 映射为
``expires_at``；同意撤销使受影响记录失效（RAG-007）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ueaf.memory.objects import MemoryCandidate, MemoryRecord

_HINT_PATTERN = re.compile(r"^(\d+)(d|h)$")
_CJK_RANGE = "\u4e00-\u9fff"


@dataclass(frozen=True, slots=True)
class RetentionDecision:
    """一次保留期决定（模块内部派生对象，非持久化规范对象）。

    ``persist`` 为 False 表示会话级记忆不持久化（§11：默认 session 或不持久化）。
    """

    persist: bool
    days: int | None
    hint: str

    def expires_at(self, valid_from: datetime) -> datetime | None:
        """由保留期决定计算过期时刻；不持久化或无期限时返回 None。"""
        if not self.persist or not self.days or self.days <= 0:
            return None
        return valid_from + timedelta(days=self.days)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """分类/提示到保留期限的映射（模块内部配置对象，非规范对象）。

    ``default_days`` 为未命中任何分类/提示时的默认保留天数（默认 90，最小化可删除）；
    ``by_sensitivity``/``by_hint`` 提供更精确的映射；``session_hint_means_no_persist``
    表示 ``session`` 提示不持久化。
    """

    default_days: int = 90
    by_sensitivity: dict[str, int] = field(default_factory=dict)
    by_hint: dict[str, int] = field(default_factory=dict)
    session_hint_means_no_persist: bool = True

    def decide(self, candidate: MemoryCandidate) -> RetentionDecision:
        hint = candidate.retention_hint.strip().lower()
        if hint == "session":
            if self.session_hint_means_no_persist:
                return RetentionDecision(persist=False, days=None, hint=hint)
            return RetentionDecision(persist=True, days=1, hint=hint)
        if hint:
            match = _HINT_PATTERN.match(hint)
            if match:
                number = int(match.group(1))
                unit = match.group(2)
                days = number if unit == "d" else max(1, number // 24)
                return RetentionDecision(persist=True, days=days, hint=hint)
            if hint in self.by_hint:
                return RetentionDecision(persist=True, days=self.by_hint[hint], hint=hint)
        if candidate.sensitivity in self.by_sensitivity:
            return RetentionDecision(
                persist=True,
                days=self.by_sensitivity[candidate.sensitivity],
                hint=candidate.sensitivity,
            )
        default = self.default_days if self.default_days > 0 else None
        return RetentionDecision(persist=True, days=default, hint="")


def _normalize(text: str) -> str:
    """规范化 statement：小写、折叠空白、仅保留字母数字与 CJK。"""
    return " ".join(re.findall(rf"[a-z0-9_{_CJK_RANGE}]+", text.lower()))


def _tokenize(text: str) -> set[str]:
    """轻量 token 化：ASCII 词 + CJK 二元组，用于冲突的确定性相似度启发式。"""
    tokens = set(re.findall(r"[A-Za-z0-9_]+", text))
    cjk = re.sub(rf"[^{_CJK_RANGE}]", "", text)
    tokens.update(cjk[i : i + 2] for i in range(len(cjk) - 1))
    return tokens


class MemoryGovernanceRules:
    """去重/冲突/保留期治理规则（纯规则，不写 Store）。"""

    def __init__(self, *, retention: RetentionPolicy | None = None) -> None:
        self._retention = retention or RetentionPolicy()

    @property
    def retention(self) -> RetentionPolicy:
        return self._retention

    def retention_decide(self, candidate: MemoryCandidate) -> RetentionDecision:
        """按候选的 retention_hint/分类计算保留期决定。"""
        return self._retention.decide(candidate)

    def detect_duplicate(
        self, candidate: MemoryCandidate, records: tuple[MemoryRecord, ...]
    ) -> tuple[str, ...]:
        """同 subject 且规范化 statement 一致的 active 记录 -> 重复（RAG-011）。"""
        normalized = _normalize(candidate.statement)
        return tuple(
            record.record_id
            for record in records
            if record.status == "active"
            and record.subject_ref == candidate.subject_ref
            and _normalize(record.statement) == normalized
        )

    def detect_conflict(
        self,
        candidate: MemoryCandidate,
        records: tuple[MemoryRecord, ...],
        *,
        min_overlap_ratio: float = 0.5,
    ) -> tuple[str, ...]:
        """同 subject/scope、statement 分歧且高重叠 -> 冲突（CTX-006 / RAG-012）。

        冲突绝不以后写覆盖：返回与候选冲突的 active 记录 refs，由调用方隔离为
        needs_review 或记录并列观点。重复（相同 statement）不算冲突。
        """
        cand_tokens = _tokenize(candidate.statement)
        if not cand_tokens:
            return ()
        scope = candidate.scope_requested or candidate.purpose
        normalized = _normalize(candidate.statement)
        conflicts: list[str] = []
        for record in records:
            if record.status != "active":
                continue
            if record.subject_ref != candidate.subject_ref:
                continue
            if (record.scope or "") != scope:
                continue
            if _normalize(record.statement) == normalized:
                continue
            other_tokens = _tokenize(record.statement)
            if not other_tokens:
                continue
            overlap = len(cand_tokens & other_tokens)
            ratio = overlap / min(len(cand_tokens), len(other_tokens))
            if ratio >= min_overlap_ratio:
                conflicts.append(record.record_id)
        return tuple(conflicts)


__all__ = ["MemoryGovernanceRules", "RetentionDecision", "RetentionPolicy"]
