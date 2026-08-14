# UEAF 架构代际与实施范围

架构代际：`V1 / V2 / V3`  
文档状态：Normative Scope Guide  
当前实现目标：`V1`

## 1. 目的

本文把 UEAF 的长期设计拆成三个架构代际，避免未来能力被误解为当前实现要求。

- **V1**：Unified Agent Runtime + Controlled Evolution Kernel。当前实现目标。
- **V2**：Adaptive Agent Ecosystem。未来计划架构。
- **V3**：Recursive Adaptive Ecosystem。研究与远期架构。

V1/V2/V3 表达产品与架构能力代际，不替代对象、API、事件和 Schema 自身的 SemVer。

## 2. 成熟度标记

涉及演化能力的规范与参考文档 SHOULD 标记：

```text
Architecture Generation: V1 | V2 | V3
Maturity: Required | Planned | Research
Implementation: Current | Future | Not Required
```

| 标记 | 含义 |
|---|---|
| `V1 / Required / Current` | 当前实现与验收范围 |
| `V2 / Planned / Future` | 保留正式设计，但不得作为 V1 验收要求 |
| `V3 / Research / Not Required` | 远期研究方向，不得驱动当前实现复杂度 |

## 3. V1：Unified Agent + Controlled Evolution Kernel

### 3.1 目标

V1 首先证明：

1. 不同 Agent Runtime 可以通过 Runtime Adapter 进入统一 UEAF 企业契约；
2. 一个 Agent 或其局部能力可以依据真实生产证据，安全地产生、评测并发布改进候选；
3. 严重生产问题可以先通过现有运行/安全/发布机制止血，而不是等待自我进化；
4. 普通噪声、暂态故障和低价值机会不会频繁触发 EvolutionRun。

V1 不以构建完整 Agent 生态、Population 或 Meta Evolution 为目标。

### 3.2 V1 Evolution Canonical Object

V1 Evolution Kernel 只新增以下一等规范对象：

| 对象 | 独立语义 |
|---|---|
| `EvolutionTrigger` | 通过 Trigger Gate 后，为什么现在值得启动一次演化 |
| `EvolutionRun` | 一次有预算、可停止的演化生命周期 |
| `GenomeManifest` | 被演化对象的不可变版本化能力描述 |
| `MutationProposal` | 改什么、为什么改、允许改变哪些范围 |
| `EvolutionAuthorityPolicy` | AI 对不同目标的 Observe/Propose/Experiment/Promote 权限 |

其他能力优先复用现有 UEAF 语义：

| 演化需求 | V1 复用对象/模块 |
|---|---|
| 候选构建 | 模块 10 `ReleaseCandidate` |
| 评测 | 模块 08 `EvalConfig` / `EvalRun` / `EvalResult` / Gate |
| 预算 | 现有 `BudgetEnvelope` / Budget Ledger，附演化用途与上限 |
| 发布 | `ReleaseDecision` / `ReleaseManifest` |
| 工件存储 | Artifact / Registry |
| Trace、Metric、Cost、Action | 原始权威域，只以引用进入 Evolution |
| 即时止血 | Runtime / Module 07 / Module 09 / Release Control / Tool Gateway |

### 3.3 V1 非 Canonical 概念

以下概念可以存在于实现、投影或分析层，但 V1 不要求成为新的跨模块 Canonical Object：

- Experience / Lesson：内部结构化记录或分析投影；
- Fitness：EvalResult 的比较视图或选择维度；
- LineageGraph：由 parent/provenance/event refs 构建的 Projection；
- Trigger Policy / P0-P3 / cooldown / novelty / expected-value：Policy/Config；
- Gene Pool：V1 仅保留兼容元数据，不建设独立 GenePool Domain；
- Species：V1 可用标签或 Registry metadata 表达；
- Diversity：V1 可作为 Eval/Policy 维度，不建设独立生命周期。

### 3.4 V1 `GenomeManifest`

V1 统一使用一个 Genome 生命周期，不分别建立 AgentGenome、SkillGenome、ToolGenome、WorkflowGenome 的基础状态机。

```yaml
genome_id: string
subject_type: agent | skill | tool | workflow | strategy
subject_ref: string
profile_ref: string
component_refs: [string]
parent_refs: [string]
provenance_refs: [string]
created_from_mutation_ref: string | null
integrity_ref: string
```

不同 `subject_type` 通过 `profile_ref` 约束必需组件和兼容规则。

### 3.5 V1 两条反馈链

V1 明确分离：

```text
Operational Response
  解决“现在怎么办”
  rollback / fallback / isolate / degrade / kill

Evolution Response
  解决“以后是否要改变自己”
  Trigger Gate -> EvolutionTrigger -> EvolutionRun
```

异常、告警或单次失败不是 `EvolutionTrigger`。P0/P1 严重问题可以先止血，再把证据和 mitigation 引用送入 Trigger Gate。

### 3.6 V1 Trigger Gate

除 P0 快速路径外，默认检查：

```text
evidence_sufficient
  -> still_relevant
  -> mutable_surface_match
  -> existing_mitigation_insufficient
  -> novelty_sufficient
  -> expected_value_positive
  -> cooldown_satisfied
  -> EvolutionTrigger
```

Trigger Gate 应优先使用规则、统计、Projection、索引和确定性查询；只有难以确定根因/价值时才升级到模型。

V1 同时支持：

- `reactive` Trigger：失败、质量/成本/延迟退化、安全回归；
- `opportunistic` Trigger：新模型、新 Tool、新 Provider、新业务能力或成本优化机会。

因此系统无故障也可以进化；同时 Trigger 也不代表必须发生 Mutation。

### 3.7 V1 运行闭环

```text
Production Evidence / Opportunity
  -> Operational Response if urgent
  -> deterministic aggregation / dedup / statistics
  -> Trigger Gate
  -> EvolutionTrigger
  -> EvolutionRun
  -> sparse MutationProposal when justified
  -> GenomeManifest candidate
  -> Module 10 ReleaseCandidate
  -> cheap/local Eval funnel
  -> Module 08 full Eval + 07/09 gates
  -> ReleaseDecision / ReleaseManifest
  -> Production Feedback
```

EvolutionRun MAY 正常结束为 `no_evolution_needed`。没有有效 `EvolutionTrigger` 时，不得为了持续自我反思对每个生产任务追加演化模型调用。

### 3.8 V1 权限默认值

对 V1 支持的 mutable targets：

```text
Observe     allow
Propose     allow
Experiment  allow
Promote     risk-based
```

实验自治与生产晋升必须分离。Governance Kernel 不属于 mutable target。

### 3.9 V1 首个闭环建议

首个可运行版本 SHOULD 优先证明：

```text
1 Trigger
  -> 1 EvolutionRun
  -> 1 MutationProposal
  -> 1 GenomeManifest candidate
  -> 1 ReleaseCandidate
  -> Eval
  -> Accept / Reject
```

先证明 Single-Candidate Evolution，再扩展有限多 Candidate；Population/Tournament 不属于 V1 首个实现要求。

## 4. V2：Adaptive Agent Ecosystem

### 4.1 定位

V2 从“单 Agent/局部能力的受控进化”升级到“整个 Agent 生态共同进化”。

V2 Planned 能力包括：

- Species / Population / Elite；
- 受治理 Gene Pool；
- 跨 Agent/Species Capability Transfer；
- Local Fitness + Ecosystem Fitness；
- Diversity / Monoculture Risk；
- Specialist 与多个 Elite 并存；
- Funnel Evaluation 后的生态级评测；
- 生态级资源归因、共享依赖和外部性分析。

V2 可以把 V1 中的标签、Projection 或 Registry metadata 升级为独立领域对象，但必须有实际规模、独立生命周期或跨模块需求作为证据。

### 4.2 V2 不反向约束 V1

V1 实现不得为了“未来可能存在 Species/Gene Pool”提前建设独立 Species Service、GenePool DB、Population Scheduler 或 Ecosystem Fitness Service。

V1 只需保证：版本化引用、provenance、兼容元数据和 Adapter 边界不会堵死 V2。

## 5. V3：Recursive Adaptive Ecosystem

V3 是研究和远期架构，关注“怎么进化”本身也进入受控优化范围。

V3 Research 能力包括：

- Meta Evolution；
- Evolution Strategy Evolution；
- Dynamic Species Creation；
- Dynamic Niche Discovery；
- Ecosystem Topology Evolution；
- Population / Pareto Frontier Search；
- Systemic Risk / Evolution Debt 建模；
- ModelEvolutionPort，对接外部 Fine-tuning、RL、Distillation、Synthetic Data 等训练系统。

V3 仍不得把 Governance Kernel 变成同一递归链可自主修改的目标。

## 6. Minimum Semantic Surface

UEAF 采用 **Minimum Semantic Surface（最小语义表面积）** 原则。

新增一个 Canonical Object 前，提案必须回答：

1. 是否存在独立生命周期？
2. 是否需要独立 Semantic Owner？
3. 是否存在独立状态迁移或并发控制？
4. 是否必须跨模块作为稳定契约传输？
5. 现有对象 + `ref`、Projection、Registry metadata 或 Eval dimension 是否不足以表达？

若不能证明前四项中的实质独立性，且第 5 项答案为“可以表达”，则 MUST NOT 新增 Canonical Object。

推荐降级顺序：

```text
new Canonical Object
  -> existing object + ref
  -> Projection
  -> Registry metadata
  -> Eval dimension
  -> internal implementation detail
```

## 7. V1/V2/V3 能力矩阵

| 能力 | V1 | V2 | V3 |
|---|---|---|---|
| Runtime Adapter / Tool Gateway / State / Eval / Release | Required | Required | Required |
| Operational Response 与 Evolution Response 分离 | Required | Required | Required |
| P0-P3 Trigger Priority | Required | Extended | Extended |
| Trigger Gate | Required | Extended | Extended |
| Reactive + Opportunistic Trigger | Required | Required | Required |
| Event-driven Evolution | Required | Required | Required |
| Sparse Mutation | Required | Required | Required |
| Single-Candidate First | Recommended | Optional | Optional |
| `GenomeManifest` | Required | Required | Required |
| EvolutionAuthorityPolicy | Required | Required | Required |
| Active Working Set 有界 | Required | Required | Required |
| Species | metadata only | Planned | Required/extended |
| Gene Pool | registry-compatible only | Planned | Extended |
| Capability Transfer | mutation-compatible only | Planned | Extended |
| Population / Elite | Not Required | Planned | Extended |
| Ecosystem Fitness | Not Required | Planned | Required |
| DiversityPolicy | Eval/policy dimension only | Planned | Required |
| Niche | Not Required | Optional | Research |
| Pareto Frontier | Not Required | Optional | Research |
| Meta Evolution | Not Required | Not Required | Research |
| Dynamic Species / Ecosystem Topology | Not Required | Not Required | Research |
| ModelEvolutionPort | Not Required | Optional design | Research |

## 8. 实施规则

1. 当前代码、任务和验收默认只针对 V1。
2. V2/V3 文档可以继续细化，但必须标记 `Future` 或 `Research`。
3. V1 不为未被实际需求证明的 V2/V3 对象预建数据库、服务、状态机或消息主题。
4. V1 的物理实现继续遵守 ADR-004：模块化单体优先，按证据拆分。
5. P0/P1 的即时保护必须复用现有安全/运行/发布能力，不新建第二套 Evolution Incident 系统。
6. 任何 V2/V3 能力进入 Current 实施范围前，必须通过 ADR 更新其代际状态和最小实现边界。
