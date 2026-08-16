"""Token Budgeter：按 PromptContract 槽位/分区裁剪、压缩、去重（CTX-002/003/005）。

槽位按层级（Tier 0 优先）装配；先去重，再压缩，再删低层（CTX-002 五层打包
优先级）。Tier 0 关键条件与关键否定绝不静默截断——超预算返回确定性的 budget
failure（CTX-003），而不是看似完整的上下文，模型绝不会被调用。压缩经由
``CompressionLineage`` 记录并可追溯；超过参考深度后重建而非无限“摘要的摘要”
（CTX-005）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ueaf.context.compression import CompressionLineage, CompressionRecord

DEFAULT_BASE_OVERHEAD_TOKENS = 64
DEFAULT_CRITICAL_RESERVE_TOKENS = 512
DEFAULT_BUDGET_FAILURE_SCHEMA = "schema://context-budget-failure/1.0.0"


@dataclass(frozen=True, slots=True)
class SlotItem:
    """槽位内的一个内容项（模块内部派生对象，非持久化规范对象）。"""

    ref: str
    tokens: int
    critical_negation: bool = False


@dataclass(frozen=True, slots=True)
class Slot:
    """PromptContract 的一个槽位/分区。"""

    slot_ref: str
    tier: int
    max_tokens: int
    items: tuple[SlotItem, ...] = ()
    is_critical: bool = False


@dataclass(frozen=True, slots=True)
class BudgetFailure:
    """确定性的预算失败（CTX-003）：绝不产生看似完整的上下文。"""

    code: str = "context_budget_exceeded"
    details_schema_ref: str = DEFAULT_BUDGET_FAILURE_SCHEMA
    reason: str = "critical_slots_exceed_budget"


@dataclass(frozen=True, slots=True)
class SlotOutcome:
    """单个槽位的装配结果（模块内部派生对象，非持久化规范对象）。"""

    slot_ref: str
    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    tokens: int


@dataclass(frozen=True, slots=True)
class BudgetResult:
    """Token Budgeter 的装配结果。"""

    status: Literal["ok", "budget_failure"]
    fitted: tuple[SlotOutcome, ...]
    omissions: tuple[str, ...]
    budget_before: int
    budget_after: int
    failure: BudgetFailure | None = None
    compression_records: tuple[CompressionRecord, ...] = ()


def estimate_item_tokens(text: str) -> int:
    """与 ContextBuilder 一致的确定性 token 估计（24 + 字符数）。"""
    return 24 + len(text)


class TokenBudgeter:
    """按槽位裁剪、压缩、去重；关键否定不得静默截断（CTX-002/003/005）。"""

    def __init__(
        self,
        *,
        critical_reserve_tokens: int = DEFAULT_CRITICAL_RESERVE_TOKENS,
        base_overhead_tokens: int = DEFAULT_BASE_OVERHEAD_TOKENS,
        rule_version: str = "1.0.0",
        lineage: CompressionLineage | None = None,
    ) -> None:
        if critical_reserve_tokens < 0:
            raise ValueError("critical_reserve_tokens must be >= 0")
        if base_overhead_tokens < 0:
            raise ValueError("base_overhead_tokens must be >= 0")
        self._critical_reserve_tokens = critical_reserve_tokens
        self._base_overhead_tokens = base_overhead_tokens
        self._rule_version = rule_version
        self._lineage = lineage or CompressionLineage()

    @property
    def lineage(self) -> CompressionLineage:
        return self._lineage

    def budget(self, slots: tuple[Slot, ...], *, max_total_tokens: int) -> BudgetResult:
        # CTX-002：先去重，再排序，再删低层；Tier 0 关键条件完整。
        ordered = self._order_slots(slots)
        budget_before = self._estimate(ordered)
        available = (
            max_total_tokens - self._critical_reserve_tokens - self._base_overhead_tokens
        )

        # CTX-003：关键槽位（Tier 0 / is_critical）绝不可裁剪。
        critical_tokens = sum(
            item.tokens
            for slot in ordered
            if slot.is_critical or slot.tier == 0
            for item in slot.items
        )
        if critical_tokens > available:
            return BudgetResult(
                status="budget_failure",
                fitted=(),
                omissions=(),
                budget_before=budget_before,
                budget_after=0,
                failure=BudgetFailure(reason="critical_slots_exceed_budget"),
            )

        outcomes: list[SlotOutcome] = []
        omissions: list[str] = []
        used = 0
        for slot in ordered:
            critical = slot.is_critical or slot.tier == 0
            kept: list[str] = []
            dropped: list[str] = []
            slot_tokens = 0
            for item in slot.items:
                if critical:
                    kept.append(item.ref)
                    slot_tokens += item.tokens
                    continue
                if (
                    used + slot_tokens + item.tokens > available
                    or slot_tokens + item.tokens > slot.max_tokens
                ):
                    # 关键否定绝不能被静默截断：宁可确定性失败（CTX-003）。
                    if item.critical_negation:
                        return BudgetResult(
                            status="budget_failure",
                            fitted=(),
                            omissions=(),
                            budget_before=budget_before,
                            budget_after=used + self._base_overhead_tokens,
                            failure=BudgetFailure(reason="critical_negation_would_be_truncated"),
                        )
                    dropped.append(item.ref)
                    continue
                kept.append(item.ref)
                slot_tokens += item.tokens
            used += slot_tokens
            outcomes.append(
                SlotOutcome(
                    slot_ref=slot.slot_ref,
                    kept=tuple(kept),
                    dropped=tuple(dropped),
                    tokens=slot_tokens,
                )
            )
            omissions.extend(dropped)
        return BudgetResult(
            status="ok",
            fitted=tuple(outcomes),
            omissions=tuple(omissions),
            budget_before=budget_before,
            budget_after=used + self._base_overhead_tokens,
            compression_records=tuple(self._lineage.records),
        )

    def compress(
        self,
        slot: Slot,
        *,
        input_refs: tuple[str, ...],
        output_ref: str,
        loss: int,
    ) -> Slot:
        """压缩槽位并记录到 CompressionLineage（CTX-005）。

        超过参考深度后，从权威输入重建而不是继续压缩（“摘要的摘要”绝非无界）。
        返回只保留摘要项的压缩后槽位。
        """
        if loss < 0:
            raise ValueError("loss must be >= 0")
        if self._lineage.needs_rebuild():
            self._lineage.rebuild_from(input_refs)
        record = CompressionRecord(
            summary_ref=slot.slot_ref,
            input_refs=input_refs,
            output_ref=output_ref,
            rule_version=self._rule_version,
            loss=loss,
        )
        self._lineage.record(record)
        summary_item = SlotItem(ref=output_ref, tokens=loss + 8, critical_negation=False)
        return Slot(
            slot_ref=slot.slot_ref,
            tier=slot.tier,
            max_tokens=slot.max_tokens,
            items=(summary_item,),
            is_critical=slot.is_critical,
        )

    def _order_slots(self, slots: tuple[Slot, ...]) -> tuple[Slot, ...]:
        """先去重（同 ref 只保留 Tier 优先级最高的一次），再按 Tier 排序。"""
        seen: set[str] = set()
        deduped: list[Slot] = []
        for slot in sorted(slots, key=lambda s: (s.tier, s.slot_ref)):
            items: list[SlotItem] = []
            for item in slot.items:
                if item.ref in seen:
                    continue
                seen.add(item.ref)
                items.append(item)
            if items:
                deduped.append(
                    Slot(
                        slot_ref=slot.slot_ref,
                        tier=slot.tier,
                        max_tokens=slot.max_tokens,
                        items=tuple(items),
                        is_critical=slot.is_critical,
                    )
                )
        return tuple(deduped)

    def _estimate(self, slots: tuple[Slot, ...]) -> int:
        return self._base_overhead_tokens + sum(
            item.tokens for slot in slots for item in slot.items
        )


__all__ = [
    "SlotItem",
    "Slot",
    "BudgetFailure",
    "SlotOutcome",
    "BudgetResult",
    "TokenBudgeter",
    "estimate_item_tokens",
]
