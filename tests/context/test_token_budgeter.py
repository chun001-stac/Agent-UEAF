"""Token Budgeter 测试：槽位裁剪与预算失败（CTX-002/003/005）。"""

from __future__ import annotations

import pytest

from ueaf.context.compression import CompressionLineage
from ueaf.context.token_budgeter import BudgetResult, Slot, SlotItem, TokenBudgeter


@pytest.mark.test_id("CTX-002")
def test_slot_trimming_respects_tier_priority() -> None:
    budgeter = TokenBudgeter(critical_reserve_tokens=64)
    slots = (
        Slot(
            slot_ref="tier0",
            tier=0,
            max_tokens=10_000,
            items=(SlotItem(ref="required:1", tokens=50),),
            is_critical=True,
        ),
        Slot(
            slot_ref="tier3",
            tier=3,
            max_tokens=10_000,
            items=(SlotItem(ref="history:1", tokens=40), SlotItem(ref="history:2", tokens=40)),
        ),
    )
    result = budgeter.budget(slots, max_total_tokens=200)
    # CTX-002：Tier 0 关键条件完整；低层先被裁剪。
    assert result.status == "ok"
    assert [outcome.slot_ref for outcome in result.fitted] == ["tier0", "tier3"]
    tier0 = result.fitted[0]
    assert "required:1" in tier0.kept
    assert "history:2" in result.omissions
    assert result.budget_after < result.budget_before


@pytest.mark.test_id("CTX-003")
def test_critical_negation_not_silently_truncated() -> None:
    budgeter = TokenBudgeter(critical_reserve_tokens=64)
    slots = (
        Slot(
            slot_ref="tier0",
            tier=0,
            max_tokens=10_000,
            items=(SlotItem(ref="required:1", tokens=50),),
            is_critical=True,
        ),
        Slot(
            slot_ref="tier4",
            tier=4,
            max_tokens=10_000,
            items=(SlotItem(ref="negation:1", tokens=200, critical_negation=True),),
        ),
    )
    result = budgeter.budget(slots, max_total_tokens=200)
    # CTX-003：关键否定绝不会被静默截断——返回确定性失败，而不是看似完整的上下文。
    assert result.status == "budget_failure"
    assert result.failure is not None
    assert result.failure.code == "context_budget_exceeded"
    assert result.failure.details_schema_ref == "schema://context-budget-failure/1.0.0"


@pytest.mark.test_id("CTX-003")
def test_budget_failure_is_deterministic() -> None:
    budgeter = TokenBudgeter(critical_reserve_tokens=16)
    slots = (
        Slot(
            slot_ref="tier0",
            tier=0,
            max_tokens=64,
            items=(SlotItem(ref="required:1", tokens=200),),
            is_critical=True,
        ),
    )
    first = budgeter.budget(slots, max_total_tokens=64)
    second = budgeter.budget(slots, max_total_tokens=64)
    # CTX-003：相同输入 -> 相同的确定性 budget failure。
    assert first.status == "budget_failure"
    assert second.status == "budget_failure"
    assert first.failure == second.failure
    assert first.failure is not None
    assert first.failure.code == "context_budget_exceeded"
    assert isinstance(first, BudgetResult)


@pytest.mark.test_id("CTX-002")
def test_dedupe_across_slots() -> None:
    budgeter = TokenBudgeter(critical_reserve_tokens=64)
    slots = (
        Slot(
            slot_ref="tier0",
            tier=0,
            max_tokens=10_000,
            items=(SlotItem(ref="source:1", tokens=20),),
            is_critical=True,
        ),
        Slot(
            slot_ref="tier1",
            tier=1,
            max_tokens=10_000,
            items=(SlotItem(ref="source:1", tokens=20),),
        ),
    )
    result = budgeter.budget(slots, max_total_tokens=500)
    # CTX-002：先去重——同一 ref 只保留一次（Tier 优先级最高者）。
    assert result.status == "ok"
    assert sum(len(outcome.kept) for outcome in result.fitted) == 1


@pytest.mark.test_id("CTX-005")
def test_compression_records_are_traceable_via_lineage() -> None:
    lineage = CompressionLineage(max_depth=2)
    budgeter = TokenBudgeter(lineage=lineage)
    slot = Slot(
        slot_ref="tier3",
        tier=3,
        max_tokens=10_000,
        items=(
            SlotItem(ref="history:1", tokens=100),
            SlotItem(ref="history:2", tokens=100),
        ),
    )
    compressed = budgeter.compress(
        slot, input_refs=("history:1", "history:2"), output_ref="summary:history", loss=20
    )
    # CTX-005：压缩记录可追溯（输入/输出/规则版本/损失）。
    assert len(lineage.records) == 1
    record = lineage.records[0]
    assert record.input_refs == ("history:1", "history:2")
    assert record.output_ref == "summary:history"
    assert record.rule_version == "1.0.0"
    assert record.loss == 20
    assert record.lineage_digest
    # 压缩后的槽位只保留摘要项，且能继续参与预算。
    assert len(compressed.items) == 1
    assert compressed.items[0].ref == "summary:history"
    result = budgeter.budget((compressed,), max_total_tokens=10_000)
    assert result.status == "ok"
    # 超过参考深度后，从权威输入重建而不是继续“摘要的摘要”（CTX-005）。
    budgeter.compress(
        compressed, input_refs=("summary:history",), output_ref="summary:history2", loss=5
    )
    assert lineage.needs_rebuild() is True
    budgeter.compress(
        compressed, input_refs=("history:1", "history:2"), output_ref="summary:rebuilt", loss=0
    )
    assert lineage.records[0].input_refs == ("history:1", "history:2")
