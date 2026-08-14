# ADR-003：所有企业副作用经过统一 Tool Gateway

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

模型、Agent SDK、本地工具、MCP Server 和远程 Agent 都可能触发业务副作用。如果每种接入方式分别处理授权、重试和幂等，将产生越权、重复动作和不可追责结果。

## 决策

所有企业副作用必须转换为 UEAF `ToolIntent`，并由 Tool Gateway 管理唯一 `ActionRecord`（内部实现可采用 DDD Aggregate）：

```text
ToolIntent
  → PolicyDecision
  → ApprovalRequest（可选）
  → Reservation
  → ExecutionAttempt
  → ActionReceipt | outcome_unknown
  → ActionReceipt（对账确认） | unresolved
```

MCP、A2A、普通 API 和本地函数只是 Adapter，不拥有第二套 action_key 或全局动作真相。

## 后果

- 授权、审批、幂等、凭据和审计行为统一；
- Tool 响应超时可以进入对账而非盲目重试；
- 增加一次受控调用路径和状态存储成本；
- 对不提供幂等和查询能力的业务系统，需要企业适配层或禁止高风险写入。

## 例外

纯本地、无副作用、无敏感数据的确定性函数可在 Runtime 内执行，但必须由能力策略明确标记为 `pure`，并保留用量和错误观测。

## 重审条件

仅在能力可证明为纯函数、无外部状态、无权限提升和无敏感数据出站时评估旁路。
