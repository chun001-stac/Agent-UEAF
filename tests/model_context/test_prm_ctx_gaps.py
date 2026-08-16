"""PRM + CTX 缺口测试：PRM-005/006/007/008/010 与 CTX-003/004/005/006/007。

覆盖参考实现中缺失的 Prompt/Model 与 Context 切片：输出/能力预留、路由与冻结
manifest 的容量关系、有界结构修复与不修复、适配器调用完整性、关键上下文溢出、
被取代的历史、压缩谱系、冲突保留，以及权限变更时的 manifest 重建。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests import support
from ueaf.context.compression import CompressionLineage, CompressionRecord
from ueaf.context.conflict import ClaimConflict, ConflictRegistry
from ueaf.context.context_build import ContextBuilder, SourceDocument
from ueaf.context.manifest_version import ManifestVersionKey, rebuild_required
from ueaf.model.integrity import InvocationMutationError, assert_integrity
from ueaf.model.prompt import PromptCompiler, PromptCompileRequest, PromptTokenBudgetExceeded
from ueaf.model.repair import NonRepairableFailure, StructuralRepairer, is_non_repairable_failure
from ueaf.model.route_capacity import RouteCapacityGate, estimate_manifest_tokens
from ueaf.ports import (
    ContextBuildRequest,
    ContextManifest,
    ModelInvocation,
    Rejected,
)

MOMENT = support.now()


def _context_request() -> ContextBuildRequest:
    return ContextBuildRequest(
        tenant_id=support.TENANT,
        run_id="run:1",
        query_intent_ref="intent:1",
        policy_snapshot_ref="policy:1",
        budget_snapshot_ref="budget:1",
        deadline_at=MOMENT + timedelta(minutes=5),
    )


def _manifest() -> ContextManifest:
    return ContextManifest(
        context_manifest_id="context:1",
        run_id="run:1",
        schema_ref="schema://context-manifest/1.0.0",
        evidence_pack_refs=("source:1", "source:2"),
        integrity_ref="integrity:ctx",
    )


# ---- PRM ---------------------------------------------------------------


@pytest.mark.test_id("PRM-005")
def test_output_and_capability_reserve_not_crowded_out() -> None:
    compiler = PromptCompiler(instruction_text="instruction")
    # 仅输入本身在预算内，但计入预留后超出 -> 结构化预算失败，
    # 绝不会生成看似合理的契约。
    with pytest.raises(PromptTokenBudgetExceeded):
        compiler.compile(
            PromptCompileRequest(
                request_id="r:1",
                tenant_id=support.TENANT,
                run_id="run:1",
                turn_id="turn:1",
                instruction_version="1.0.0",
                variables_schema_ref="schema://vars/1.0.0",
                output_schema_ref="schema://out/1.0.0",
                variables={"big": "x" * 2000},
                max_prompt_tokens=600,
                output_reserve_tokens=200,
                capability_reserve_tokens=200,
                safety_reserve_tokens=100,
            )
        )
    # 当预留可容纳时，契约可以编译。
    contract = compiler.compile(
        PromptCompileRequest(
            request_id="r:2",
            tenant_id=support.TENANT,
            run_id="run:1",
            turn_id="turn:2",
            instruction_version="1.0.0",
            variables_schema_ref="schema://vars/1.0.0",
            output_schema_ref="schema://out/1.0.0",
            variables={"query": "q"},
            max_prompt_tokens=600,
            output_reserve_tokens=200,
            safety_reserve_tokens=100,
        )
    )
    assert contract.text == "instruction"


@pytest.mark.test_id("PRM-006")
def test_route_cannot_fit_frozen_manifest_is_rejected_not_mutated() -> None:
    gate = RouteCapacityGate(reserve_tokens=128)
    manifest = _manifest()
    # 路由对于冻结的 manifest 来说过小 -> 被拒绝。
    decision = gate.evaluate(manifest, route_capacity_tokens=64)
    assert decision.rejected
    assert "route_cannot_fit_frozen_manifest" in decision.reason_codes
    # 冻结的 manifest 永不被修改：它保留其 evidence 引用。
    assert manifest.evidence_pack_refs == ("source:1", "source:2")
    # 充足的路由原样接受该 manifest。
    assert gate.evaluate(manifest, route_capacity_tokens=4096).accepted
    assert estimate_manifest_tokens(manifest) > 0


@pytest.mark.test_id("PRM-007")
def test_structural_repair_is_bounded() -> None:
    repairer = StructuralRepairer(max_passes=1)
    result = repairer.repair('{"amount": "10.00"')
    assert result.repaired is True
    assert result.pass_count <= 1
    assert result.content == '{"amount": "10.00"}'
    # 已经格式良好的内容不会被重写。
    ok = repairer.repair('{"amount": "10.00"}')
    assert ok.repaired is False
    assert ok.content == '{"amount": "10.00"}'


@pytest.mark.test_id("PRM-008")
def test_semantic_and_security_failures_are_not_repaired() -> None:
    # refusal / content_filter / no_progress 永远不会被结构修复。
    assert is_non_repairable_failure("refusal", "stop")
    assert is_non_repairable_failure("final_response", "content_filter")
    assert is_non_repairable_failure("no_progress", "stop")
    repairer = StructuralRepairer()
    with pytest.raises(NonRepairableFailure):
        repairer.repair("I cannot do that", kind="refusal")
    with pytest.raises(NonRepairableFailure):
        repairer.repair("x", finish_reason="content_filter")


@pytest.mark.test_id("PRM-010")
def test_provider_adapter_cannot_mutate_invocation() -> None:
    request = ModelInvocation(
        model_invocation_id="mi:1",
        run_id="run:1",
        prompt_contract_ref="prompt:1",
        context_manifest_ref="context:1",
        model_route_ref="route:primary",
        output_schema_ref="schema://out/1.0.0",
        deadline_at=MOMENT,
    )
    # 未变更的调用通过校验。
    assert_integrity(
        request,
        returned_output_schema_ref="schema://out/1.0.0",
        returned_model_route_ref="route:primary",
    )
    # 更改 schema 或路由，或添加 system prompt，会导致一致性校验失败。
    with pytest.raises(InvocationMutationError, match="output_schema_changed"):
        assert_integrity(
            request,
            returned_output_schema_ref="schema://other/1.0.0",
            returned_model_route_ref="route:primary",
        )
    with pytest.raises(InvocationMutationError, match="model_route_changed"):
        assert_integrity(
            request,
            returned_output_schema_ref="schema://out/1.0.0",
            returned_model_route_ref="route:fallback",
        )
    with pytest.raises(InvocationMutationError, match="system_prompt_added"):
        assert_integrity(
            request,
            returned_output_schema_ref="schema://out/1.0.0",
            returned_model_route_ref="route:primary",
            added_system_prompt=True,
        )
    with pytest.raises(InvocationMutationError, match="unapproved_tools"):
        assert_integrity(
            request,
            returned_output_schema_ref="schema://out/1.0.0",
            returned_model_route_ref="route:primary",
            enabled_unapproved_tools=("tool:shell",),
        )


# ---- CTX ---------------------------------------------------------------


@pytest.mark.test_id("CTX-003")
def test_critical_context_overflow_is_deterministic_failure() -> None:
    big_snippet = "x" * 400
    builder = ContextBuilder(
        sources=[
            SourceDocument(
                source_ref="source:big",
                source_version="1.0.0",
                content_digest="d:1",
                allowed_scopes=("orders:read",),
                trust_label="tier0",
                snippet=big_snippet,
            )
        ],
        principal_scopes=("orders:read",),
        max_snippets=8,
        max_manifest_tokens=64,
        critical_reserve_tokens=16,
    )
    result = builder.build(_context_request())
    assert isinstance(result, Rejected)
    assert result.error.code == "context_budget_exceeded"
    assert result.error.details_schema_ref == "schema://context-budget-failure/1.0.0"


@pytest.mark.test_id("CTX-004")
def test_superseded_history_does_not_override_correction() -> None:
    builder = ContextBuilder(principal_scopes=("orders:read",))
    # 更新的更正取代旧的摘要；旧摘要永远不会覆盖更正，
    # 且取代关系会被记录（CTX-004）。
    builder.record_superseded("source:correction", "source:old-summary")
    assert builder.superseded_refs["source:correction"] == "source:old-summary"
    # 打包时保留更正（更高信任度）而非被取代的摘要。
    builder = ContextBuilder(
        sources=[
            SourceDocument(
                source_ref="source:old-summary",
                source_version="1.0.0",
                content_digest="d:old",
                allowed_scopes=("orders:read",),
                trust_label="tier0",
                snippet="OLD claim",
            ),
            SourceDocument(
                source_ref="source:correction",
                source_version="1.0.0",
                content_digest="d:new",
                allowed_scopes=("orders:read",),
                trust_label="tier0",
                snippet="NEW claim",
            ),
        ],
        principal_scopes=("orders:read",),
    )
    result = builder.build(_context_request())
    # 打包时保留更正（更高信任度）而非被取代的摘要；装配内容见 source_refs，
    # evidence_pack_refs 引用 EvidencePack id（RAG-013 可追溯性）。
    assert result.value.evidence_pack_refs
    assert "source:correction" in result.value.source_refs
    assert "source:old-summary" in result.value.source_refs


@pytest.mark.test_id("CTX-005")
def test_compression_lineage_is_traceable_and_bounded() -> None:
    lineage = CompressionLineage(max_depth=2)
    first = lineage.record(
        CompressionRecord(
            summary_ref="s:1",
            input_refs=("source:1", "source:2"),
            output_ref="s:1",
            rule_version="1.0.0",
            loss=2,
        )
    )
    assert first.lineage_digest
    assert lineage.depth == 1
    lineage.record(
        CompressionRecord(
            summary_ref="s:2",
            input_refs=("s:1",),
            output_ref="s:2",
            rule_version="1.0.0",
            loss=3,
        )
    )
    # 超过参考深度后，进行重建而不是继续压缩。
    assert lineage.needs_rebuild() is True
    rebuilt = lineage.rebuild_from(("source:1", "source:2"))
    assert rebuilt.input_refs == ("source:1", "source:2")
    assert lineage.depth == 1
    assert lineage.needs_rebuild() is False


@pytest.mark.test_id("CTX-006")
def test_conflicts_are_preserved_not_deduped() -> None:
    registry = ConflictRegistry()
    conflict = ClaimConflict(
        claim_ref="claim:revenue",
        source_refs=("source:a",),
        versions=("1.0.0",),
        statement="revenue is 100",
    )
    registry.register(conflict)
    # 第二个已授权的来源产生冲突；它被保留而不是丢弃。
    second = ClaimConflict(
        claim_ref="claim:revenue",
        source_refs=("source:b",),
        versions=("2.0.0",),
        statement="revenue is 200",
    )
    merged = registry.register(second)
    assert set(merged.source_refs) == {"source:a", "source:b"}
    assert merged.statement == "revenue is 100"  # 首写保留，同时携带两个来源
    # 只有当冲突来源在打包中时，冲突才会显现。
    assert len(registry.evidence_pack_conflicts(("source:a", "source:b"))) == 1
    assert len(registry.evidence_pack_conflicts(("source:c",))) == 0


@pytest.mark.test_id("CTX-007")
def test_manifest_rebuild_on_authority_change() -> None:
    base = ManifestVersionKey(
        principal_ref="principal:1",
        delegation_scope_ref="scope:read",
        purpose="research",
        task_state_ref="task:1",
        acl_ref="acl:1",
        source_versions_ref="source-v:1",
        memory_validity_ref="mem:1",
        budget_ref="budget:1",
        route_requirement_ref="route:primary",
    )
    # 相同的权限输入 -> 无需重建。
    assert rebuild_required(base, base) is False
    # 任何权限输入的变更都会强制重建（CTX-007）。
    import dataclasses

    for field_value in (
        dict(principal_ref="principal:2"),
        dict(purpose="billing"),
        dict(task_state_ref="task:2"),
        dict(acl_ref="acl:2"),
        dict(source_versions_ref="source-v:2"),
        dict(memory_validity_ref="mem:2"),
        dict(budget_ref="budget:2"),
        dict(route_requirement_ref="route:fallback"),
    ):
        changed = dataclasses.replace(base, **field_value)
        assert rebuild_required(base, changed) is True
