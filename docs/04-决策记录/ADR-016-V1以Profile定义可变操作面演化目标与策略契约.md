# ADR-016：V1 以 Profile 定义可变操作面、演化目标与策略契约

- 状态：Accepted
- 决策日期：2026-08-14
- Architecture Generation：V1
- Maturity：Required
- Implementation：Current

## 背景

UEAF V1 已定义 `GenomeManifest`、`MutationProposal`、`EvolutionAuthorityPolicy`、`EvolutionRun`、Eval/Release 复用和 Smallest Effective Repair，但仍存在三个实现层缺口：

1. `mutable_scope` 只约束到模块/能力范围，尚不足以机器确定某个字段能否修改、取值范围和跨字段约束；
2. Eval/Gate 能判断候选是否可接受，但缺少版本化、多目标的候选选择规则来表达“怎样算比 baseline 更好”；
3. Strategy 只定义为可替换搜索算法，尚缺最小输入、输出、Candidate/field/component/scope 上限和 novelty 等稳定约束。

若分别为 GeneSpace、Fitness、ExperimentDesign 新增领域对象，会违反 ADR-012 的 Minimum Semantic Surface，并显著扩大 V1 语义表面积。

## 决策

### 1. 不新增 GeneSpace Canonical Object

V1 使用 `GenomeManifest.profile_ref` 指向的版本化 Subject Profile 定义 Mutation Surface Contract，包括：

```text
mutable
bounded
replace-only
conditional
frozen
cross-field constraints
mutation limits
risk/review metadata
```

`MutationProposal.change_summary` 继续用于人类摘要，但机器执行必须基于结构化 `changes[]` 校验。

真正允许修改的 Effective Mutation Surface 必须是：

```text
Subject Profile
∩ EvolutionAuthorityPolicy
∩ EvolutionRun.mutable_scope
∩ Repair Router.repair_target_scope
∩ environment/risk Profile
```

的交集。

### 2. Agent 负责组合，组件负责自身细节

V1 `subject_type=agent` 默认主要拥有：

```text
prompt_ref
model_route_ref
context_policy_ref
memory_policy_ref
workflow_ref
skill/capability refs
task routing ref
少量 bounded behavior
```

具体 Prompt 文本、Model 参数、RAG 参数、Tool timeout、Workflow topology 不重复成为 Agent-level 字段；它们由对应版本化 Profile/Artifact 自身承担。

因此 V1 优先采用：

```text
new component/profile version
-> replace ref
-> new GenomeManifest
```

而不是原地修改 Agent 内的大块嵌套配置。

### 3. 五类 Subject 使用不同 Mutation Surface

V1 当前五类 `subject_type` 的边界为：

```text
agent
  composition refs + bounded runtime behavior

skill
  instruction/schema/dependency refs + bounded behavior + R4 implementation artifact

tool
  timeout/polling/backoff/provider/adapter refs + R4 implementation，副作用边界严格冻结

workflow
  R1 bounded routing/stop parameters
  R2 component replacement
  R3 topology/composition

strategy
  R1 bounded parameters
  R2 implementation/component replacement
  R4 executable artifact
```

Strategy 不得修改 Mutation Surface root、EvolutionAuthority、Eval root、Budget Enforcement 或 Release Authority。

Prompt、Context Policy、Memory Policy、Model Route 继续作为版本化 Profile/Artifact 表达；V1 不因此新增 `subject_type`。

### 4. Sparse Mutation 默认采用单一假设

V1 首个实现 SHOULD 默认：

```text
1 Candidate
1 Repair Target
1 Hypothesis
1 Component
1~2 Mutable Fields
1 Repair Level
```

闭环稳定后 MAY 扩展到 2~5 Candidate，但扩大范围仍必须由 Budget、novelty 和诊断证据约束。

Candidate 不应无证据同时修改 Prompt、Model、RAG、Tool 与 Workflow 等不相关区域。

### 5. 不新增 FitnessRecord 真相源

V1 使用版本化 Evolution Objective / Fitness Profile 解释现有：

```text
EvalResult
business KPI evidence
cost/token
latency/SLO
complexity/fan-out
security/regression
```

Profile 必须区分：

```text
primary objectives
hard constraints
guardrails / acceptable degradation
evidence confidence
tie-break rules
```

安全、治理和关键回归硬失败不得被权重或业务收益抵消。

### 6. 定义 EvolutionStrategy Contract

V1 Strategy 的稳定输入至少包括：

```text
EvolutionTrigger
baseline GenomeManifest
Subject Profile / Effective Mutation Surface
EvolutionAuthorityPolicy
bounded Working Set
Diagnosis / repair metadata
previous attempt refs
Evolution Objective Profile
Budget slice
```

输出为 `0..N` 个 Proposal Draft，规范化后形成既有 `MutationProposal`。

首个 `llm_guided_sparse_mutation` 实现必须有 Candidate 数、修改字段数、修改组件数、修改 scope 数、novelty、重复提案和预算硬上限。

Strategy 可以输出 0 Candidate，也不能拥有发布权。

### 7. Workflow 与 Tool 的强制安全约束不可被优化掉

Tool 的权限要求、凭据范围、Tool Gateway enforcement、approval root、action outcome-certainty/idempotency semantic root 均不可自动修改。

Workflow 中被安全、业务或监管 Profile 声明 mandatory 的 approval/security/audit/Tool-Gateway/reconciliation/tenant-boundary 节点不得因为延迟、成本或成功率而自动删除。

Tool timeout/unknown 必须继续先 reconciliation，不能机械进化为更多 retry。

### 8. V1 允许资产化复用，不建设 V2 Gene Pool

成功 Mutation 可以沉淀为版本化 Artifact/Profile/Policy/Skill/Tool/Workflow，并携带 provenance 与 compatibility metadata。其他 Agent 可在自己的 EvolutionRun 中通过普通 `MutationProposal(mutation_type=transfer)` 引用并重新评测。

V1 不实现自动跨 Agent 传播、Species、Population、Gene Pool 生命周期或 Ecosystem Fitness。

### 9. 人类审查使用 Projection，不新增审批对象

从现有 Trigger、Diagnosis、Mutation、Eval、Release 和 Evidence refs 生成 Human-readable Mutation Review Projection，至少表达：

```text
Problem / Evidence / Diagnosis
Proposed Change / Unchanged Boundaries
Why this RepairLevel
Expected Benefit / Expected Cost / Known Risks
Evaluation Plan / Canary Conditions / Rollback
Previous Attempts / Approval Requirement
```

生产晋升仍使用既有 Release Governance；本 ADR 不新增新的 Release Authority。

### 10. Evolution 攻击面纳入既有安全/可观测体系

V1 必须覆盖 Evidence poisoning、延迟 Prompt Injection、Trigger flooding、Eval/Repair-history poisoning、R4 artifact supply chain、Judge manipulation、Budget exhaustion 和伪装成修复的自提权。

Evolution Kernel 自身健康通过模块 09 的普通结构化 meta-metrics 观察，不建设递归“AI 监控 AI”系统。

## 后果

正面影响：

- Sparse Mutation 从原则变成机器可执行约束；
- “AI 到底能改自己什么”可以由 Profile + Authority + Repair Scope 精确计算；
- Agent 不再因承担所有底层参数而形成大而不可审计的 Mutation 面；
- Candidate 可以用单一假设做更可靠的因果归因和失败复用；
- Tool/Workflow 的安全强制边界不会被性能优化误删；
- Candidate 可在多目标条件下相对 baseline 做可解释选择；
- Strategy 可替换但不再是无契约自由实现；
- 成功经验可资产化复用，同时不把 V2 Gene Pool 提前带入 V1；
- 企业 Owner 可以理解和审查 Mutation。

代价：

- Subject/Profile/Objective/Strategy Profile 需要版本治理和兼容测试；
- Candidate Build 前增加 Mutation schema、constraint 和 Effective Surface 校验；
- 组件版本数量会增加，需要 Registry 做 supersession/retention；
- 多目标权衡需要业务 Owner 明确 KPI 与可接受退化区间；
- R3/R4 的评测和供应链成本高于简单参数修改。

## 被否决方案

### 新增 GeneSpace / FitnessRecord / ExperimentPlan Canonical Object

否决。现有 Profile、Registry metadata、Eval 和 Budget 语义足以表达 V1 所需约束。

### 把所有可变参数直接放进 Agent Genome

否决。会使 Agent 成为大杂烩配置，扩大 Mutation blast radius，并破坏 Smallest Effective Repair。

### 让 LLM 直接解释自由 `change_summary` 并执行

否决。无法稳定做类型、范围、权限、frozen field 和跨字段机器校验。

### 默认一次修改多个不相关组件

否决。会降低因果归因能力、增加 Eval 成本和回归定位难度。

### 用单一 Fitness Score 覆盖所有维度

否决。会隐藏安全硬失败、业务/成本 trade-off 和证据不确定性。

### 在 V1 建设自动跨 Agent Gene Pool 传播

否决。该能力属于 V2；V1 只保留 Artifact 化和目标侧重新评测的复用桥梁。

## 重审条件

- Profile 无法表达真实 Subject 的可变生命周期；
- Prompt/Context/ModelRoute/MemoryPolicy 被证明具有必须独立管理的一等生命周期；
- 多目标选择需要独立并发、状态迁移或跨模块稳定契约，现有 Eval/Profile 无法承载；
- V2 正式进入 Current，需要 Gene Pool/Capability Transfer 独立生命周期；
- Strategy 数量和团队边界扩大到需要独立服务部署，且有容量/信任域证据支持。
