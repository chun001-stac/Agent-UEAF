"""Query Planner：将目标转为一个或多个 QueryIntent（CTX-007/RAG-014/RAG-015）。

Query Planner 把 ``ContextBuildRequest`` 连同 goal/query_hints 推导为一个或多个
``QueryIntent``；每个意图固定授权策略快照 ref。相同输入幂等：相同规范化查询哈希
（叠加授权策略快照与期限）返回相同的意图序列（稳定 id），绝不为相同内容生成漂移
计划（CTX-007：权限输入不变即输出稳定）。Query Planner 只读取权限输入来溯源，
绝不改变 TaskState（其不接收、不写入任何 TaskState 对象）。
RAG-014 约束保留：改写/拆分绝不能丢失 tenant/purpose/region/source/freshness/
citation 约束；RAG-015 有界多查询：多意图扩展受 ``max_intents`` 上限约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ueaf.common.identifiers import new_object_id, sha256_hex
from ueaf.ports import ContextBuildRequest

DEFAULT_MAX_INTENTS = 4


@dataclass(frozen=True, slots=True)
class QueryIntent:
    """一次受控证据查询的派生意图（模块内部派生对象，非持久化规范对象）。

    自然语言查询只表达信息需求，不能扩大授权范围；意图固定引用授权策略快照与
    来源约束，绝不携带主体未获准的检索边界。
    """

    query_intent_id: str
    run_id: str
    principal_context_ref: str
    query: str
    purpose: str
    source_constraints: tuple[str, ...]
    authorization_scope_ref: str
    freshness_requirement: str
    citation_requirement: bool
    budget_slice: str
    normalized_query_hash: str
    policy_snapshot_ref: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """一次计划的派生结果（模块内部派生对象，非持久化规范对象）。

    ``task_state_ref`` 是只读溯源引用：计划只是读取它，绝不改写。
    """

    normalized_query_hash: str
    policy_snapshot_ref: str
    intents: tuple[QueryIntent, ...]
    task_state_ref: str | None = None


def normalize_query(*, goal: str, query_hints: tuple[str, ...]) -> str:
    """规范化自然语言查询（大小写/空白折叠），用于稳定哈希与幂等。"""
    return " ".join(" ".join((goal, *query_hints)).split()).lower()


class QueryPlanner:
    """把目标转为一个或多个 QueryIntent；相同输入幂等，不改变 TaskState。

    计划是纯派生：除自身的幂等缓存外没有任何写入。相同规范化内容 + 相同授权
    策略快照 + 相同期限 -> 相同的意图序列（稳定 id）。
    """

    def __init__(
        self,
        *,
        max_intents: int = DEFAULT_MAX_INTENTS,
        producer_version: str = "0.1.0",
    ) -> None:
        if max_intents < 1:
            raise ValueError("max_intents must be >= 1")
        self._max_intents = max_intents
        self._producer_version = producer_version
        # 幂等缓存：相同输入 -> 相同的意图序列（稳定 id）。
        self._plan_cache: dict[str, QueryPlan] = {}

    def plan(
        self,
        request: ContextBuildRequest,
        *,
        goal: str,
        principal_context_ref: str,
        purpose: str,
        authorization_scope_ref: str,
        query_hints: tuple[str, ...] = (),
        source_constraints: tuple[str, ...] = (),
        freshness_requirement: str = "",
        citation_requirement: bool = False,
        budget_slice: str = "",
        task_state_ref: str | None = None,
    ) -> QueryPlan:
        normalized = normalize_query(goal=goal, query_hints=query_hints)
        # 语义查询摘要：主体/用途/范围/约束/查询内容（下游缓存复用）。
        normalized_query_hash = sha256_hex(
            "|".join(
                [
                    principal_context_ref,
                    purpose,
                    authorization_scope_ref,
                    ",".join(source_constraints),
                    normalized,
                ]
            )
        )
        # 幂等键：内容 + 授权策略快照 + 期限都参与，保证相同输入 -> 相同意图。
        idempotency_key = sha256_hex(
            "|".join(
                [
                    normalized_query_hash,
                    request.policy_snapshot_ref,
                    str(request.deadline_at.timestamp()),
                ]
            )
        )
        cached = self._plan_cache.get(idempotency_key)
        if cached is not None:
            return cached

        # RAG-015：有界多意图扩展，绝不超过 max_intents，绝不扩大授权范围。
        queries = self._derive_queries(goal, query_hints)
        intents = tuple(
            self._make_intent(
                request,
                query=query,
                principal_context_ref=principal_context_ref,
                purpose=purpose,
                authorization_scope_ref=authorization_scope_ref,
                source_constraints=source_constraints,
                freshness_requirement=freshness_requirement,
                citation_requirement=citation_requirement,
                budget_slice=budget_slice,
                normalized_query_hash=sha256_hex(
                    "|".join(
                        [
                            principal_context_ref,
                            purpose,
                            authorization_scope_ref,
                            ",".join(source_constraints),
                            normalize_query(goal=query, query_hints=()),
                        ]
                    )
                ),
            )
            for query in queries
        )
        plan = QueryPlan(
            normalized_query_hash=normalized_query_hash,
            policy_snapshot_ref=request.policy_snapshot_ref,
            intents=intents,
            task_state_ref=task_state_ref,
        )
        self._plan_cache[idempotency_key] = plan
        return plan

    def _derive_queries(self, goal: str, query_hints: tuple[str, ...]) -> tuple[str, ...]:
        """确定性派生：有提示时 base + 提示（有界），无提示时仅 base。"""
        if not query_hints:
            return (goal,)
        queries = [goal, *query_hints]
        return tuple(queries[: self._max_intents])

    def _make_intent(
        self,
        request: ContextBuildRequest,
        *,
        query: str,
        principal_context_ref: str,
        purpose: str,
        authorization_scope_ref: str,
        source_constraints: tuple[str, ...],
        freshness_requirement: str,
        citation_requirement: bool,
        budget_slice: str,
        normalized_query_hash: str,
    ) -> QueryIntent:
        return QueryIntent(
            query_intent_id=new_object_id("query-intent"),
            run_id=request.run_id,
            principal_context_ref=principal_context_ref,
            query=query,
            purpose=purpose,
            source_constraints=source_constraints,
            authorization_scope_ref=authorization_scope_ref,
            freshness_requirement=freshness_requirement,
            citation_requirement=citation_requirement,
            budget_slice=budget_slice,
            normalized_query_hash=normalized_query_hash,
            policy_snapshot_ref=request.policy_snapshot_ref,
            expires_at=request.deadline_at,
        )


__all__ = ["QueryIntent", "QueryPlan", "QueryPlanner", "normalize_query", "DEFAULT_MAX_INTENTS"]
