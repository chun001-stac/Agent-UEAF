"""Query Planner 测试：幂等、授权快照固定、多意图、不改变 TaskState（CTX-007/RAG-014/RAG-015）。"""

from __future__ import annotations

import pytest

from tests import support
from ueaf.context.query_planner import QueryIntent, QueryPlan, QueryPlanner
from ueaf.ports import ContextBuildRequest


def _request(
    run_id: str = "run:1",
    *,
    policy_snapshot_ref: str | None = None,
) -> ContextBuildRequest:
    return ContextBuildRequest(
        tenant_id=support.TENANT,
        run_id=run_id,
        query_intent_ref=f"query:{run_id}",
        policy_snapshot_ref=policy_snapshot_ref or f"policy:{run_id}",
        budget_snapshot_ref=f"budget:{run_id}",
        deadline_at=support.now(),
    )


def _plan(
    planner: QueryPlanner,
    request: ContextBuildRequest,
    *,
    goal: str = "Summarize the quarterly orders",
    query_hints: tuple[str, ...] = ("EU region",),
) -> QueryPlan:
    return planner.plan(
        request,
        goal=goal,
        principal_context_ref="principal:1",
        purpose="research",
        authorization_scope_ref="scope:orders:read",
        query_hints=query_hints,
        source_constraints=("orders:read",),
        freshness_requirement="max_age_seconds=3600",
        citation_requirement=True,
        budget_slice="token:4000",
        task_state_ref="task-state:1",
    )


@pytest.mark.test_id("CTX-007")
def test_plan_is_idempotent_for_same_input() -> None:
    planner = QueryPlanner()
    request = _request()
    first = _plan(planner, request)
    second = _plan(planner, request)
    # CTX-007：权限输入不变 -> 输出稳定，绝不产生漂移计划。
    assert first.normalized_query_hash == second.normalized_query_hash
    assert [i.query_intent_id for i in first.intents] == [
        i.query_intent_id for i in second.intents
    ]
    assert first.policy_snapshot_ref == request.policy_snapshot_ref
    assert all(i.policy_snapshot_ref == request.policy_snapshot_ref for i in first.intents)


@pytest.mark.test_id("RAG-014")
def test_policy_snapshot_and_constraints_are_fixed_per_plan() -> None:
    planner = QueryPlanner()
    plan_a = _plan(planner, _request(run_id="run:a"))
    plan_b = _plan(planner, _request(run_id="run:b", policy_snapshot_ref="policy:changed"))
    # 每个意图固定引用其请求的授权策略快照，绝不复用旧快照（RAG-014 约束保留）。
    assert all(i.policy_snapshot_ref == "policy:run:a" for i in plan_a.intents)
    assert all(i.policy_snapshot_ref == "policy:changed" for i in plan_b.intents)
    assert all("orders:read" in i.source_constraints for i in plan_a.intents)
    assert all(i.authorization_scope_ref == "scope:orders:read" for i in plan_a.intents)
    # 授权策略快照变化 -> 生成新计划（CTX-007：权限输入变化即重建）。
    assert plan_a.policy_snapshot_ref != plan_b.policy_snapshot_ref
    assert [i.query_intent_id for i in plan_a.intents] != [
        i.query_intent_id for i in plan_b.intents
    ]


@pytest.mark.test_id("RAG-015")
def test_multi_intent_is_bounded() -> None:
    planner = QueryPlanner(max_intents=3)
    request = _request()
    hints = ("entity:A", "entity:B", "entity:C", "entity:D")
    plan = planner.plan(
        request,
        goal="compare entities",
        principal_context_ref="principal:1",
        purpose="research",
        authorization_scope_ref="scope:orders:read",
        query_hints=hints,
    )
    # RAG-015：有界多意图扩展，绝不超过 max_intents，绝无无限扇出。
    assert len(plan.intents) == 3
    # 每个意图都是已授权的受控查询，不扩大授权范围。
    assert all(i.authorization_scope_ref == "scope:orders:read" for i in plan.intents)
    assert all(i.policy_snapshot_ref == request.policy_snapshot_ref for i in plan.intents)
    assert all(isinstance(i, QueryIntent) for i in plan.intents)


@pytest.mark.test_id("CTX-007")
def test_planning_does_not_mutate_task_state() -> None:
    planner = QueryPlanner()
    request = _request()
    # TaskState 只以只读引用参与溯源；计划绝不改写它。
    plan = _plan(planner, request)
    assert plan.task_state_ref == "task-state:1"
    again = _plan(planner, request)
    assert again.task_state_ref == "task-state:1"
    # 多次规划不产生 TaskState 写入：所有输出都是派生的只读对象。
    assert [i.query_intent_id for i in plan.intents] == [
        i.query_intent_id for i in again.intents
    ]
