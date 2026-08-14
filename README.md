# UEAF：统一企业 Agent 框架

UEAF（Unified Enterprise Agent Framework）是一套面向企业 Agent 系统的供应商无关架构、运行契约和治理规范。它通过稳定对象、唯一状态所有者、受控动作协议和可替换运行时适配器，把模型、Prompt、上下文、RAG、记忆、工具、MCP、多 Agent、评测、安全、生产运营以及受控自我进化纳入同一条可审计生命周期。

UEAF 不重复实现每一种 Agent Loop。LangGraph、Microsoft Agent Framework、OpenAI Agents SDK、Google ADK、CrewAI 等框架通过 Runtime Adapter 接入；企业身份、任务状态、工具授权、副作用收据、审计、发布治理和 Evolution Governance 仍由 UEAF 统一管理。

## 文档层级

| 层级 | 约束力 | 内容 |
|---|---|---|
| 总体设计 | 规范性 | 产品边界、架构原则、模块职责、唯一所有权 |
| 核心规范 | 规范性 | 对象、状态、事件、端口、兼容规则和受控演化边界 |
| 功能模块 | 规范性 | 每个模块的组件、流程、接口、故障与验收条件 |
| 参考架构 | 参考性 | 端到端时序、部署拓扑、存储、演化闭环和实施路径 |
| ADR | 规范性 | 已接受的关键架构决策及重审条件 |

发生冲突时，优先级依次为：核心规范、总体设计、ADR、功能模块、参考架构。任何实现不得以底层 SDK 的对象或默认行为覆盖 UEAF 的身份、租户、状态、授权、动作、发布和演化治理语义。

## 文档入口

### 总览

- [产品定义](docs/00-总览/01-UEAF产品定义.md)
- [总体设计](docs/00-总览/02-总体设计.md)
- [总体架构](docs/00-总览/03-总体架构.md)
- [功能模块全景](docs/00-总览/04-功能模块全景.md)
- [外部 Agent 框架整合策略](docs/00-总览/05-外部Agent框架整合策略.md)

### 核心规范

- [统一术语与对象模型](docs/01-核心规范/01-统一术语与对象模型.md)
- [状态机与终态规范](docs/01-核心规范/02-状态机与终态规范.md)
- [跨模块契约与事件规范](docs/01-核心规范/03-跨模块契约与事件规范.md)
- [端口与适配器规范](docs/01-核心规范/04-端口与适配器规范.md)
- [受控演化与递归自改规范](docs/01-核心规范/05-受控演化与递归自改规范.md)

### 功能模块

1. [接入与准入](docs/02-功能模块/01-接入与准入.md)
2. [Agent 运行时与状态](docs/02-功能模块/02-Agent运行时与状态.md)
3. [模型、Prompt 与结构化输出](docs/02-功能模块/03-模型Prompt与结构化输出.md)
4. [上下文、RAG 与记忆](docs/02-功能模块/04-上下文RAG与记忆.md)
5. [工具、MCP 与动作执行](docs/02-功能模块/05-工具MCP与动作执行.md)
6. [工作流与多 Agent](docs/02-功能模块/06-工作流与多Agent.md)
7. [身份、权限与安全治理](docs/02-功能模块/07-身份权限与安全治理.md)
8. [评测与发布治理](docs/02-功能模块/08-评测与发布治理.md)
9. [生产运行与可观测性](docs/02-功能模块/09-生产运行与可观测性.md)
10. [开发者平台与框架适配](docs/02-功能模块/10-开发者平台与框架适配.md)
11. [经验记忆与受控递归进化](docs/02-功能模块/11-经验记忆与受控递归进化.md)

### 参考架构

- [端到端时序](docs/03-参考架构/01-端到端时序.md)
- [部署拓扑与多租户](docs/03-参考架构/02-部署拓扑与多租户.md)
- [数据存储与一致性](docs/03-参考架构/03-数据存储与一致性.md)
- [90 天 MVP 实施路线](docs/03-参考架构/04-90天MVP实施路线.md)
- [演化闭环与成本控制](docs/03-参考架构/05-演化闭环与成本控制.md)

### 架构决策记录

- [ADR-001：采用 Runtime Adapter 而非重建全部运行时](docs/04-决策记录/ADR-001-采用Runtime-Adapter而非重建全部运行时.md)
- [ADR-002：统一语义所有权与状态模型](docs/04-决策记录/ADR-002-统一语义所有权与状态模型.md)
- [ADR-003：所有企业副作用经过统一 Tool Gateway](docs/04-决策记录/ADR-003-所有企业副作用经过统一Tool-Gateway.md)
- [ADR-004：模块化单体优先，按证据拆分](docs/04-决策记录/ADR-004-模块化单体优先按证据拆分.md)
- [ADR-005：采用独立 Evolution Plane 与候选式自改](docs/04-决策记录/ADR-005-采用独立Evolution-Plane与候选式自改.md)
- [ADR-006：治理内核不可递归修改，Subject 与 Judge 隔离](docs/04-决策记录/ADR-006-治理内核不可递归修改且Subject与Judge隔离.md)
- [ADR-007：事件驱动稀疏演化与成本感知 Fitness](docs/04-决策记录/ADR-007-事件驱动稀疏演化与成本感知Fitness.md)
- [ADR-008：演化记忆分层压缩与有界活跃集](docs/04-决策记录/ADR-008-演化记忆分层压缩与有界活跃集.md)

## 核心运行主链

```text
RequestEnvelope + PrincipalContext
  → Edge Pre-validation + TaskEnvelope
  → TaskState / RunRecord(queued → admitting)
  → RunAdmissionResult
    ↳ admitted → running；deferred → waiting；rejected → terminal/rejected
  → ContextManifest
  → PromptContract
  → ModelInvocation / ModelRunResult
  → StructuredDecision
  → ToolIntent（如需动作）
  → PolicyDecision / ApprovalRequest
  → ActionRecord / ActionReceipt
  → CompletionDisposition
  → AuditEvent / EvalResult / Release Evidence
```

## 受控演化主链

```text
Production Evidence
  → Dedup / Statistics / Clustering
  → EvolutionTrigger（只有值得进化时）
  → EvolutionExperience / EvolutionLesson
  → EvolutionStrategy
  → MutationProposal
  → AgentGenome / CandidateRelease
  → Deterministic / Statistical / Model / Human Eval
  → FitnessRecord
  → Quality / Security / Operational Gates
  → ReleaseDecision / ReleaseManifest
  → Production Feedback
```

遗传算法只是 `EvolutionStrategy` 的一种实现。UEAF 同时允许 LLM-guided sparse mutation、Bayesian Optimization、RL、Population Search、Workflow/Tool/Topology Search 和 Human-guided Evolution。

## 框架级不变量

1. 模型只能提出候选决定，不能生成身份、授权、审批或业务事实。
2. 每一种权威状态只有一个语义所有者；缓存、投影和物理存储不得成为第二真相源。
3. `RunPhase` 与 `CompletionDisposition` 相互独立，等待态和业务终态不得混为一个枚举。
4. 所有有副作用动作都经过 Tool Gateway，并可追溯到主体、策略、审批、幂等身份和收据。
5. 工具超时不表示动作未发生；结果不确定时必须进入对账，不得盲目重试。
6. 权限过滤先于 RAG、记忆和能力相关性排序。
7. Trace、Log、Metric、Audit 和 Eval 各自独立治理。
8. 长运行任务绑定不可变 `ReleaseManifest`；升级、恢复和迁移不得静默改变语义。
9. Runtime Adapter 只转换运行时能力，不得丢弃租户、安全、来源、预算或版本字段。
10. 不支持的底层框架能力必须显式拒绝，不能静默降级。
11. 任何 Agent 不得直接修改自身当前 `ReleaseManifest`；所有自改必须产生新的 Candidate。
12. Candidate 不得修改用于评估自身的 EvaluationSuite、阈值根、保留集答案、Release Authority 或 EvolutionBudget Enforcement。
13. Evolution Subject、Proposer/Builder、Evaluator/Judge 和 Release Authority 必须逻辑隔离。
14. 所有 EvolutionRun 必须有预算、停止条件和明确终态；不存在无限代、无限 Token 的规范模式。
15. 能力提升不能单独构成晋升理由；Token、费用、延迟、复杂度、回归和安全必须同时评估。
16. 历史 Experience 可以增长，但 Active Evolution Working Set 必须有界；已固化为 Tool/Policy/Workflow/Skill 的知识应退出活跃文本记忆。
17. 没有有效 `EvolutionTrigger` 时，稳定生产不得为了持续自我反思而追加强模型调用。
18. 同一递归链不得自主修改 Governance Kernel，包括 Identity、Permission、Tool Gateway enforcement、Audit root、Evaluator root、Release Authority、Budget Enforcement、Secrets、删除与 kill switch。
