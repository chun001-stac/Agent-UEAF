"""证据领域（阶段 5）：L0 观测 -> L1 聚合 -> L2 触发。

常规的证据收集/聚合/触发候选检测以 0 个 LLM token 为目标（EVD-001）。摘要/聚合/指纹
对象都是投影，绝不接受权威写入。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.common.meta import ContractMeta
from ueaf.infrastructure.telemetry.collector import InMemoryTelemetryCollector

EvidenceLevel = Literal["L0", "L1", "L2"]


@dataclass(frozen=True, slots=True)
class EvidencePack:
    """查询意图的已授权材料；排序前先进行权限过滤。"""

    meta: ContractMeta
    evidence_pack_id: str
    query_intent_ref: str
    principal_context_ref: str
    items: tuple[str, ...] = ()
    source_versions: tuple[str, ...] = ()
    coverage: Mapping[str, object] = field(default_factory=dict)
    conflicts: tuple[str, ...] = ()
    expires_at: datetime | None = None
    selection_policy_ref: str | None = None

    def __post_init__(self) -> None:
        if self.evidence_pack_id != self.meta.object_id:
            raise ValueError("EvidencePack.meta.object_id must equal evidence_pack_id")


@dataclass(frozen=True, slots=True)
class L0Observation:
    """从遥测映射的最小化结构化观测（无 LLM）。"""

    observation_id: str
    run_id: str
    source: str
    result_class: str
    error_code: str | None
    occurred_at: datetime
    tenant_id: str


@dataclass(frozen=True, slots=True)
class RunSummary:
    """确定性的每次运行投影（L1）；绝不是权威。"""

    run_id: str
    result_class_counts: Mapping[str, int]
    error_codes: tuple[str, ...]
    observation_count: int
    freshness_label: Literal["current", "stale"] = "current"


@dataclass(frozen=True, slots=True)
class RollingWindow:
    """聚合指标的有界窗口（L1）。"""

    window_id: str
    period_millis: int
    total_observations: int
    error_count: int
    error_rate: float


@dataclass(frozen=True, slots=True)
class ErrorFingerprint:
    """用于聚类的稳定归一化错误签名（L2）。"""

    fingerprint_id: str
    error_code: str
    normalized_message: str
    component: str
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime

    @classmethod
    def build(cls, code: str, message: str, component: str) -> str:
        # 转小写、去除高基数数字 ID -> 稳定签名。
        normalized = re.sub(r"\d+", "#", " ".join(message.lower().split()))
        return sha256_hex(f"{code}|{normalized}|{component}")


@dataclass(frozen=True, slots=True)
class TriggerCandidate:
    """潜在的进化触发；还不是 EvolutionTrigger（EVO-001/002）。"""

    candidate_id: str
    error_fingerprint_ref: str
    reason_codes: tuple[str, ...]
    window: RollingWindow
    evidence_refs: tuple[str, ...] = ()


class EvidencePipeline:
    """L0 -> L1 -> L2 确定性证据流；零 LLM token（EVD-001）。"""

    def __init__(self, *, tenant_id: str, window_period_millis: int = 300_000) -> None:
        self._tenant = tenant_id
        self._period = window_period_millis
        self._observations: list[L0Observation] = []

    def ingest(self, collector: InMemoryTelemetryCollector) -> list[L0Observation]:
        """将遥测轨迹/日志映射为 L0 观测（无 LLM）。"""
        observed = []
        for trace in collector.traces:
            if trace.tenant_id != self._tenant:
                continue
            observed.append(
                L0Observation(
                    observation_id=new_object_id("obs"),
                    run_id=trace.run_id,
                    source=trace.adapter_ref,
                    result_class=trace.result_class,
                    error_code=None,
                    occurred_at=trace.occurred_at,
                    tenant_id=trace.tenant_id,
                )
            )
        for log in collector.logs:
            observed.append(
                L0Observation(
                    observation_id=new_object_id("obs"),
                    run_id=log.run_id or "system",
                    source="log",
                    result_class="log",
                    error_code=self._error_code_of(log.message_ref),
                    occurred_at=log.occurred_at,
                    tenant_id=log.tenant_id,
                )
            )
        self._observations.extend(observed)
        return observed

    def run_summary(self, run_id: str) -> RunSummary:
        relevant = [o for o in self._observations if o.run_id == run_id]
        counts: dict[str, int] = {}
        errors: list[str] = []
        for obs in relevant:
            counts[obs.result_class] = counts.get(obs.result_class, 0) + 1
            if obs.error_code:
                errors.append(obs.error_code)
        return RunSummary(
            run_id=run_id,
            result_class_counts=counts,
            error_codes=tuple(sorted(set(errors))),
            observation_count=len(relevant),
        )

    def rolling_window(self, *, now: datetime | None = None) -> RollingWindow:
        moment = now or datetime.now(UTC)
        start = moment - timedelta(milliseconds=self._period)
        window_obs = [o for o in self._observations if o.occurred_at >= start]
        errors = sum(1 for o in window_obs if o.error_code is not None)
        rate = errors / len(window_obs) if window_obs else 0.0
        return RollingWindow(
            window_id=new_object_id("window"),
            period_millis=self._period,
            total_observations=len(window_obs),
            error_count=errors,
            error_rate=rate,
        )

    def detect_trigger_candidate(
        self,
        *,
        error_code: str,
        component: str,
        message: str,
        threshold_error_rate: float = 0.6,
        now: datetime | None = None,
    ) -> TriggerCandidate | None:
        """从聚合证据中检测触发候选（L2，EVO-002）。

        单一的异常/告警绝不是触发；该门控要求聚合的错误率证据以及相关性/缓解检查。
        """
        window = self.rolling_window(now=now)
        if window.error_count < 3:
            return None  # 证据不足
        if window.error_rate < threshold_error_rate:
            return None  # 低于证据门控
        fingerprint_id = ErrorFingerprint.build(error_code, message, component)
        return TriggerCandidate(
            candidate_id=new_object_id("trigger-candidate"),
            error_fingerprint_ref=f"fingerprint:{fingerprint_id[:16]}",
            reason_codes=("error_rate_breach",),
            window=window,
            evidence_refs=(fingerprint_id,),
        )

    @staticmethod
    def _error_code_of(message_ref: str | None) -> str | None:
        if not message_ref:
            return None
        if "error" in message_ref.lower() or "fail" in message_ref.lower():
            return "error"
        return None
