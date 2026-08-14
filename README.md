# UEAF：统一企业 Agent 框架

UEAF（Unified Enterprise Agent Framework）是一套面向企业 Agent 系统的供应商无关架构、运行契约和治理规范。它通过稳定对象、唯一状态所有者、受控动作协议和可替换运行时适配器，把模型、Prompt、上下文、RAG、记忆、工具、MCP、多 Agent、评测、安全、生产运营以及受控自我进化纳入同一条可审计生命周期。

UEAF 不重复实现每一种 Agent Loop。LangGraph、Microsoft Agent Framework、OpenAI Agents SDK、Google ADK、CrewAI 等框架通过 Runtime Adapter 接入；企业身份、任务状态、工具授权、副作用收据、审计、发布治理和 Evolution Governance 仍由 UEAF 统一管理。

## 当前架构代际

```text
V3  Recursive Adaptive Ecosystem      Research
        ▲
V2  Adaptive Agent Ecosystem          Planned / Future
        ▲
V1  Unified Agent + Evolution Kernel  Current
        ▲
External Agent Runtimes
```

**当前代码、实施和验收默认只针对 V1。** V2/V3 设计继续保留，但不得被解释为 V1 当前必须实现的服务、数据库、状态机或对象。

- V1：统一 Agent Runtime + 小型受控演化内核；
- V2：Species、Gene Pool、Capability Transfer、Ecosystem Fitness；
- V3：Meta Evolution、Dynamic Niche/Species、Ecosystem Topology、ModelEvolutionPort 等研究方向。

详见：[UEAF 架构代际与实施范围](docs/00-总览/06-UEAF架构代际与实施范围.md)。

## 文档层级

| 层级 | 约束力 | 内容 |
|---|---|---|
| 总体设计 | 规范性 | 产品边界、架构原则、模块职责、唯一所有权 |
| 核心规范 | 规范性 | 对象、状态、事件、端口、兼容规则和演化边界 |
| 功能模块 | 规范性 | 每个模块的组件、流程、接口、故障与验收条件 |
| 参考架构 | 参考性 | 端到端时序、部署拓扑、存储、演化闭环和实施路径 |
| ADR | 规范性 | 已接受的关键架构决策及重审条件 |

发生冲突时，优先级依次为：核心规范、总体设计、ADR、功能模块、参考架构。V2/V3 文档的 Future/Research 内容不覆盖 V1 Current 范围。

## 文档入口

### 总览

- [产品定义](docs/00-总览/01-UEAF产品定义.md)
- [总体设计](docs/00-总览/02-总体设计.md)
- [总体架构](docs/00-总览/03-总体架构.md)
- [功能模块全景](docs/00-总览/04-功能模块全景.md)
- [外部 Agent 框架整合策略](docs/00-总览/05-外部Agent框架整合策略.md)
- [V1/V2/V3 架构代际与实施范围](docs/00-总览/06-UEAF架构代际与实施范围.md)
- [V1 问题诊断与修复机制](docs/00-总览/07-V1问题诊断与修复机制.md)

### 核心规范

- [统一术语与对象模型](docs/01-核心规范/01-统一术语与对象模型.md)
- [状态机与终态规范](docs/01-核心规范/02-状态机与终态规范.md)
- [跨模块契约与事件规范](docs/01-核心规范/03-跨模块契约与事件规范.md)
- [端口与适配器规范](docs/01-核心规范/04-端口与适配器规范.md)
- [V1 受控演化与递归自改规范](docs/01-核心规范/05-受控演化与递归自改规范.md)
- [V2 生态共同进化与演化授权规范](docs/01-核心规范/06-生态共同进化与演化授权规范.md)
- [V1 最小 Evidence 采集规范](docs/01-核心规范/07-V1最小Evidence采集规范.md)
- [V1 问题诊断与最小修复规范](docs/01-核心规范/08-V1问题诊断与最小修复规范.md)

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
11. [V1 经验记忆与受控递归进化](docs/02-功能模块/11-经验记忆与受控递归进化.md)

### 参考架构

- [端到端时序](docs/03-参考架构/01-端到端时序.md)
- [部署拓扑与多租户](docs/03-参考架构/02-部署拓扑与多租户.md)
- [数据存储与一致性](docs/03-参考架构/03-数据存储与一致性.md)
- [90 天 MVP 实施路线](docs/03-参考架构/04-90天MVP实施路线.md)
- [V1 演化闭环与成本控制](docs/03-参考架构/05-演化闭环与成本控制.md)
- [V2 生态共同进化与基因池](docs/03-参考架构/06-生态共同进化与基因池.md)
- [V1 Evidence 采集与 Trigger 数据流](docs/03-参考架构/07-V1证据采集与触发数据流.md)
- [V1 问题诊断与修复路由](docs/03-参考架构/08-V1问题诊断与修复路由.md)

### 架构决策记录

- [ADR-001：采用 Runtime Adapter 而非重建全部运行时](docs/04-决策记录/ADR-001-采用Runtime-Adapter而非重建全部运行时.md)
- [ADR-002：统一语义所有权与状态模型](docs/04-决策记录/ADR-002-统一语义所有权与状态模型.md)
- [ADR-003：所有企业副作用经过统一 Tool Gateway](docs/04-决策记录/ADR-003-所有企业副作用经过统一Tool-Gateway.md)
- [ADR-004：模块化单体优先，按证据拆分](docs/04-决策记录/ADR-004-模块化单体优先按证据拆分.md)
- [ADR-005：采用独立 Evolution Plane 与候选式自改](docs/04-决策记录/ADR-005-采用独立Evolution-Plane与候选式自改.md)
- [ADR-006：治理内核不可递归修改，Subject 与 Judge 隔离](docs/04-决策记录/ADR-006-治理内核不可递归修改且Subject与Judge隔离.md)
- [ADR-007：事件驱动稀疏演化与成本感知 Fitness](docs/04-决策记录/ADR-007-事件驱动稀疏演化与成本感知Fitness.md)
- [ADR-008：演化记忆分层压缩与有界活跃集](docs/04-决策记录/ADR-008-演化记忆分层压缩与有界活跃集.md)
- [ADR-009：采用生态共同进化与共享 Gene Pool](docs/04-决策记录/ADR-009-采用生态共同进化与共享Gene-Pool.md)
- [ADR-010：默认开放演化，但分离 Experiment 与 Promote 权限](docs/04-决策记录/ADR-010-默认开放演化但分离Experiment与Promote权限.md)
- [ADR-011：采用 Local 与 Ecosystem 双层 Fitness，并保留多样性](docs/04-决策记录/ADR-011-采用Local与Ecosystem双层Fitness并保留多样性.md)
- [ADR-012：采用 V1/V2/V3 架构代际并限制当前实现范围](docs/04-决策记录/ADR-012-采用V1-V2-V3架构代际并限制当前实现范围.md)
- [ADR-013：分离即时运行响应与 EvolutionTrigger](docs/04-决策记录/ADR-013-分离即时运行响应与EvolutionTrigger.md)
- [ADR-014：采用分层 Evidence 漏斗与按需扩展](docs/04-决策记录/ADR-014-采用分层Evidence漏斗与按需扩展.md)
- [ADR-015：采用分层诊断与最小有效修复路由](docs/04-决策记录/ADR-015-采用分层诊断与最小有效修复路由.md)

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

## V1 两条反馈链

```text
Observed Signal / Opportunity
  ├─ P0/P1 urgent
  │    → Operational Response
  │    → rollback / fallback / isolate / degrade / kill
  │
  └─ Trigger Gate
       → evidence sufficient?
       → still relevant?
       → mutable surface match?
       → existing mitigation insufficient?
       → novelty sufficient?
       → expected value positive?
       → cooldown satisfied?
       → EvolutionTrigger
```

**异常 ≠ EvolutionTrigger；EvolutionTrigger ≠ 必须修改。**

- Operational Response 解决“现在怎么办”；
- Evolution Response 解决“以后是否值得改变自己”。

## V1 Evidence 采集主链

```text
Module 02..08 domain facts
  → non-blocking TelemetryPort
  → Module 09 sampling / aggregation / retention
  → Run Summary / rolling windows / Error Fingerprint
  → Trigger Candidate Detector
  → Trigger Gate
       ↳ enough evidence → decide
       ↳ unclear → bounded Evidence Expansion
  → EvolutionTrigger or no_trigger
```

Evidence 使用三级漏斗：

```text
L0 Always-on Minimal Evidence
  → L1 Conditionally Sampled Evidence
  → L2 On-demand Evidence Expansion
```

**AI 不持续监控 AI。** 正常采集、Fingerprint、聚合和 Trigger Candidate 检测目标为 `0 LLM Token`；只有确定性证据不足时才升级到 Cheap/Strong Model。模块 11 不复制 Trace/Log/Metric/Eval/Action 成为第二数据平台。

## V1 问题诊断与修复主链

```text
EvolutionTrigger
  → bounded Evidence Expansion
  → Diagnosis
  → Repair Router
       ↳ NO_EVOLUTION / OPERATIONAL_ONLY
       ↳ R5 → Independent Governance
       ↳ R1 Parameter / Config
       ↳ R2 Component / Routing
       ↳ R3 Workflow / Composition
       ↳ R4 Artifact / Code
  → MutationProposal
  → GenomeManifest Candidate
  → ReleaseCandidate
  → Eval / Gates
  → Release / Production Feedback
```

V1 采用 **Smallest Effective Repair**：能用更小修复范围解决时，不无证据扩大修改面。`observed_problem_scope`、`likely_root_cause_scope` 与 `repair_target_scope` 允许不同；RAG/Tool/Workflow 等基层模块只负责发现事实和即时止血，不拥有长期原地自改权。

Repair Router、Diagnosis、RepairLevel 和 RepairHistory 都是内部策略/Projection/metadata，不新增第六个 Evolution Canonical Object。

## V1 受控演化主链

```text
Production Evidence / Opportunity
  → Operational Response if urgent
  → Dedup / Statistics / Clustering
  → Trigger Gate
  → EvolutionTrigger
  → bounded EvolutionRun
  → Diagnosis / Repair Router
  → sparse MutationProposal when justified
  → GenomeManifest Candidate
  → Module 10 ReleaseCandidate
  → Module 08 Eval + 07/09 Gates
  → ReleaseDecision / ReleaseManifest
  → Production Feedback
```

V1 Evolution Kernel 只新增五个核心 Canonical Object：

```text
EvolutionTrigger
EvolutionRun
GenomeManifest
MutationProposal
EvolutionAuthorityPolicy
```

Candidate、Eval、Budget、Release、Artifact 均复用现有 UEAF 语义。Experience/Lesson、Fitness、Lineage、P0-P3、cooldown、novelty、RunSummary、ErrorFingerprint、AggregateWindow、TriggerCandidate、Diagnosis、RepairLevel 等默认作为内部记录、Projection、Policy/Config 或 Eval dimension，而不是新的权威对象。

Trigger 支持两类：

```text
Reactive      failure / drift / regression
Opportunistic new model / tool / provider / cost / business opportunity
```

EvolutionRun MAY 正常结束为 `no_evolution_needed`，例如问题来自已恢复的 Provider 暂态、用户数据、不可修改范围，或已有 mitigation 已足够。

## V2 / V3

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
Dynamic Niche / Species
Ecosystem Topology Evolution
Pareto Frontier
Evolution Debt / Systemic Risk
ModelEvolutionPort
```

V2/V3 设计可以继续完善，但不属于 V1 Current 实现要求。

## 框架级不变量

1. 模型只能提出候选决定，不能生成身份、授权、审批或业务事实。
2. 每一种权威状态只有一个语义所有者；缓存、投影和物理存储不得成为第二真相源。
3. `RunPhase` 与 `CompletionDisposition` 相互独立。
4. 所有有副作用动作都经过 Tool Gateway。
5. 工具结果不确定时必须进入对账，不得盲目重试。
6. 权限过滤先于 RAG、记忆和能力相关性排序。
7. Trace、Log、Metric、Audit 和 Eval 各自独立治理。
8. 长运行任务绑定不可变 `ReleaseManifest`。
9. Runtime Adapter 只转换运行时能力，不得覆盖 UEAF 企业语义。
10. 不支持的底层框架能力必须显式拒绝。
11. 任何 Agent 不得直接修改自身当前 `ReleaseManifest`。
12. Candidate 不得修改自身 Eval root、保留集答案、Release Authority 或 Budget Enforcement。
13. Evolution Subject、Builder、Judge 和 Release Authority 必须逻辑隔离。
14. 所有 EvolutionRun 必须有预算、停止条件和明确终态。
15. 能力提升必须同时考虑 Token、费用、延迟、复杂度、回归和安全。
16. 历史可以增长，但 Active Evolution Working Set 必须有界。
17. 没有有效 `EvolutionTrigger` 时，不进行持续强模型自我反思。
18. Governance Kernel 不进入同一递归链。
19. mutable targets 默认 `Observe/Propose/Experiment=allow`；`Promote` 单独按风险授权。
20. V1 使用统一 `GenomeManifest`，不默认建立多种 Genome 基础生命周期。
21. V1 Candidate/Eval/Budget/Release 必须复用既有 UEAF 语义，不建立第二套真相源。
22. **Minimum Semantic Surface**：能通过 existing object + ref、Projection、Registry metadata 或 Eval dimension 表达时，不新增 Canonical Object。
23. V2/V3 Future/Research 能力不得驱动 V1 预建服务、数据库、状态机或消息主题。
24. 任何 V2/V3 能力进入 Current 实施范围前，必须通过 ADR 更新其代际状态和最小实现边界。
25. P0/P1 严重问题的即时保护不得等待 EvolutionRun；Evolution Plane 不替代 Safety/SRE/Release Control。
26. `EvolutionTrigger` 只能由 Trigger Gate 形成；普通异常、告警和单次失败不是 Trigger 的同义词。
27. `EvolutionTrigger` 只表示“值得受控分析”，不要求必须产生 Mutation；`no_evolution_needed` 是合法终态。
28. Trigger Gate 默认优先确定性规则/统计，模型只用于无法可靠分类的根因或价值判断。
29. V1 Evidence 采用“L0 全量小指标、L1 条件采样、L2 按需扩展”；不得默认全量复制大 Payload。
30. 模块 02–08 在事实产生位置输出结构化观测；模块 09 负责采集/采样/聚合；模块 11 只消费 Projection 与按需引用。
31. 正常 Evidence Collection / Aggregation / Trigger Candidate 路径目标为 0 LLM Token。
32. `run_id`、`trace_id`、用户/文档/Prompt 等高基数字段不得作为常规 Metric label。
33. Error Fingerprint 优先确定性去重；只有无法归类的剩余错误才进入 semantic clustering。
34. Telemetry 背压时优先保留 Audit/Security/ActionReceipt/P0-P1 和最小 Run Summary，优先降低 success trace 与 verbose debug。
35. Evidence gap 必须可观测；禁止把“没有采到数据”解释为“系统正常”。
36. 基层 RAG/Model/Tool/Workflow/Memory/Runtime 模块可以检测与止血，但不得因检测到问题原地修改长期 Genome 或当前 Release。
37. V1 长期修复必须通过 Diagnosis/Repair Router 选择修复目标，再形成 R1–R4 `MutationProposal`；问题发生层不等于修复层。
38. 修复默认遵循 Smallest Effective Repair；修复失败不能自动成为扩大 mutable scope 的理由。
39. Tool timeout/unknown 必须先遵守 reconciliation/outcome certainty 语义，不能机械演化为更多 retry。
40. R5 Governance Boundary 不允许同一递归链自动修复；“权限不足”不能被转换成自动提升权限。
41. Repair Router、Diagnosis、RepairLevel、RepairHistory 不新增 Canonical Object；V1 Evolution Canonical Object 总数保持五个。
