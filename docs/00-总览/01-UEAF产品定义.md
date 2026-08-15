# UEAF 产品定义

当前架构代际：`V1`  
长期架构：`V2 / V3`  
代际边界见：[UEAF 架构代际与实施范围](06-UEAF架构代际与实施范围.md)

## 1. 产品定位

UEAF 是企业 Agent 的统一架构与治理底座，由六类能力构成：

1. **规范层**：身份、请求、任务、运行、上下文、动作、证据、发布与演化契约；
2. **运行外壳**：在外部 Agent Runtime 外提供准入、状态、预算、工具执行和恢复控制；
3. **控制面**：Agent、Prompt、模型、能力、策略、评测、发布和版本治理；
4. **治理面**：权限、审计、数据生命周期、评测、SLO 和风险；
5. **开发者面**：SDK、CLI、Sandbox、Schema、Adapter SPI 和 Conformance；
6. **演化面**：V1 把通过 Trigger Gate 的生产问题/机会转换为有预算、可停止、可评测、可回滚的 Candidate；V2/V3 再扩展生态共同进化与 Meta Evolution。

UEAF 不重建 Agent Loop；它统一企业边界和可审计生命周期。

## 2. V1 Current 范围

V1 Reference Implementation 与 V1 文档验收 MUST 覆盖：

- 同步/流式/异步请求；
- `PrincipalContext`、Task/Run、Checkpoint、恢复/取消；
- Prompt、Model、Structured Output；
- Context/RAG/Memory；
- Tool/MCP/企业 API/远程受控能力；
- Policy/Approval/Credential/Tenant Isolation；
- Workflow/Handoff；
- Eval/Security/Operational/Release Governance；
- Runtime Adapter + 至少两个只读 Conformance 路径；
- V1 Controlled Evolution Kernel；
- 一个 Single-Candidate Evolution Vertical Slice。

V1 Evolution Kernel 只新增：

```text
EvolutionTrigger
EvolutionRun
GenomeManifest
MutationProposal
EvolutionAuthorityPolicy
```

Candidate/Eval/Budget/Release/Artifact 均复用既有 UEAF 语义。

## 3. V1 Evolution 的“必实现”与“可启用”分离

这里必须区分：

```text
Reference Implementation capability
  MUST implement V1 Controlled Evolution Kernel

Tenant / Environment deployment policy
  MAY disable or restrict Observe/Propose/Experiment/Promote by EvolutionAuthorityPolicy
```

因此“Evolution Extension Profile”是 **部署启用 Profile**，不是“V1 参考实现可以不开发 Evolution”的含义。

企业可以：

```text
Observe allow
Propose allow/deny
Experiment allow/deny
Promote automatic_after_gates | canary | gated | never
```

但 Governance Kernel 永远不进入自动递归链。

## 4. UEAF 要解决的问题

| 问题 | V1 响应 |
|---|---|
| 不同 SDK Session/Thread/Memory 含义不同 | Canonical Object + Runtime Adapter 显式映射 |
| 模型能提 Tool 但缺企业授权 | `ToolIntent -> stable identity -> ActionRecord(proposed) -> PolicyDecision/Approval -> Reservation -> execution/Receipt` |
| 长任务恢复重复副作用 | CAS/lease/fencing/action_key/receipt/reconciliation |
| Prompt/模型变化难回溯 | 不可变 `ReleaseManifest` 版本集合 |
| Trace 被误当审计 | Trace/Metric/Log/Audit/Eval 分离 |
| 发现异常就自改 | Operational Response 与 Evolution Response 分离 |
| 严重事故不能等 Evolution | P0/P1 先 rollback/fallback/isolate/degrade/kill |
| 系统正常时不能优化 | Opportunistic Trigger |
| 经验只沉淀成日志 | Trigger + EvolutionRun + Mutation + Candidate |
| 演化 Token 线性增长 | L0/L1/L2 Evidence、事件驱动、Budget、有界 Working Set |
| AI 能改什么不清楚 | Subject Profile + Effective Mutation Surface + machine `changes[]` |
| “更好”没有定义 | Objective/Fitness Profile 解释现有 Eval/业务/成本/延迟/安全证据 |
| 架构对象无限增加 | Minimum Semantic Surface |
| 未来生态拖重当前实现 | V1/V2/V3 代际边界 |

## 5. V1 非目标

V1 不负责：

- 承诺模型绝对正确；
- 把所有 Runtime 压成一个 DSL；
- 对无幂等/无查询能力的外部系统承诺 exactly-once；
- 无限自治、多 Agent 网络、无限长期 Memory、无限递归；
- 允许当前 Agent 原地修改 `ReleaseManifest`；
- 允许 Candidate 修改自身 Eval root、Release Authority、Budget Enforcement、权限根；
- 把 GA 固定为唯一 Evolution 算法；
- 预建 Species、Gene Pool、Population、Ecosystem Fitness、Meta Evolution；
- 强制绑定某模型/云/DB/向量库。

## 6. V2/V3

### V2 Planned

```text
Species / Population / Elite
Gene Pool
Capability Transfer
Local + Ecosystem Fitness
Diversity / Monoculture Risk
Ecosystem Funnel Evaluation
```

### V3 Research

```text
Meta Evolution
Evolution Strategy Evolution
Dynamic Niche / Species
Ecosystem Topology Evolution
Pareto Frontier
Evolution Debt / Systemic Risk
ModelEvolutionPort
```

V2/V3 不反向约束 V1 当前实现。

## 7. 目标用户与责任

| 角色 | 主要责任 |
|---|---|
| 平台团队 | Runtime shell、Control/Data Plane、Adapter、Evolution Kernel、SLO |
| Agent 应用团队 | AgentDefinition、Prompt、业务验收、EvalCase、允许 Mutation surface |
| 业务系统团队 | System of Record、动作幂等、查询、补偿、收据 |
| 安全团队 | Identity/Policy/Approval/Credential、Security Gate、Governance Kernel |
| 数据治理团队 | 分类、用途、驻留、保留、删除、证据可用范围 |
| SRE | 容量、告警、Operational Response、恢复、成本/SLO |
| 质量治理团队 | EvalCase、grader calibration、Quality Gate、holdout |
| Evolution Owner | Trigger/Threshold/Cooldown/Novelty/Objective/Strategy/Authority/Stop Policy |

## 8. Profile

### Core

Request/Principal/Task/Run/Prompt/Model/ToolIntent/明确终态/Trace/基础 Eval。

### Durable

Core + 事件、Checkpoint、Queue、Lease、等待恢复、取消、幂等、unknown reconciliation。

### Enterprise

Durable + Multi-tenant、PDP/PEP、Approval、Credential、Audit、RAG ACL、Memory Governance、Release Gate、SLO。

### Regulated

Enterprise + Dedicated Cell、客户密钥、WORM Audit、驻留、职责分离、Legal Hold、强人工门禁。

### V1 Evolution Enablement Profile

覆盖在 Enterprise/Regulated 能力之上，用于配置是否启用/允许自动 Evolution：

```text
five V1 Evolution Canonical Objects
Trigger Gate / Reactive + Opportunistic
Evidence L0/L1/L2
Active Working Set caps
Budget slice
Subject/Builder/Judge/Release Authority separation
Subject/Objective/Strategy Profiles
Mutation Validator
```

该 Profile 可以按租户关闭自动 Experiment/Promote，但 Reference Implementation 仍必须具备这些能力。

## 9. V1 产品原则

1. 确定性控制包围概率性推理；
2. 一个事实只有一个 Semantic Owner；
3. 可见能力不等于执行权限；
4. Context 是临时、可复现的受控视图；
5. Memory 是受治理数据产品；
6. 副作用使用 effectively-once + reconciliation；
7. Release 固定版本、证据、风险和 rollback；
8. 自我进化只产生 Candidate，不原地修改 Production；
9. 异常不等于 Trigger，Trigger 不等于 Mutation；
10. P0/P1 先止血；
11. 无 Trigger 时强模型演化调用接近零；
12. Evaluator 确定性优先；
13. Active Working Set 有界；
14. Strategy 可替换，GA 不是 Evolution 定义；
15. Governance Kernel 是递归链外稳定参照；
16. Minimum Semantic Surface；
17. V1/V2/V3 严格分代。

## 10. V1 成功标准

至少证明：

- 多租户不能跨 DB/cache/index/queue/artifact/telemetry 访问；
- 重复请求/消息不产生重复副作用；
- stale fencing 不能提交权威状态；
- Tool timeout -> unknown/reconciling；
- 恢复重验 identity/policy/release/inflight action；
- 每次模型调用可还原 Prompt/Route/ContextManifest；
- 高风险动作可还原 identity/policy/approval/receipt；
- 不安全/退化 Candidate 被 Gate 阻断；
- Runtime Adapter 替换不改变企业契约；
- 普通单次失败不直接 Trigger；
- Opportunistic Trigger 可在无故障时工作；
- 无 Trigger 不持续自我反思；
- `EvolutionRun` 可正常 `no_evolution_needed`/budget/safety/manual stop；
- Active Working Set 不随历史线性增长；
- V1 Candidate/Eval/Budget/Release 不建第二套；
- 一个 `GenomeManifest` 覆盖 `agent|skill|tool|workflow|strategy`；
- 至少完成一次 `Trigger -> EvolutionRun -> Diagnosis -> Mutation -> Genome -> ReleaseCandidate -> Eval -> Accept/Reject`；
- V1 未预建 V2/V3 生态服务。
