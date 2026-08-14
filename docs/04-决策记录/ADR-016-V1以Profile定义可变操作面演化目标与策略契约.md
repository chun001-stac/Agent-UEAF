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
3. Strategy 只定义为可替换搜索算法，尚缺最小输入、输出、候选数、字段数和 novelty 等稳定约束。

若分别为 GeneSpace、Fitness、ExperimentDesign 新增领域对象，会违反 ADR-012 的 Minimum Semantic Surface，并显著扩大 V1 语义表面积。

## 决策

### 1. 不新增 GeneSpace Canonical Object

V1 使用 `GenomeManifest.profile_ref` 指向的版本化 Subject Profile 定义 Mutation Surface Contract，包括：

```text
mutable fields
allowed operations
value type/range/enum/registry constraints
frozen fields
cross-field constraints
mutation limits
risk/review metadata
```

`MutationProposal` 的自由 `change_summary` 继续用于摘要，但机器执行必须基于结构化 `changes[]` 校验。

### 2. 不新增 FitnessRecord 真相源

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

### 3. 定义 EvolutionStrategy Contract

V1 Strategy 的稳定输入至少包括：

```text
EvolutionTrigger
baseline GenomeManifest
Subject Profile / mutation surface
EvolutionAuthorityPolicy
bounded Working Set
Diagnosis / repair metadata
previous attempt refs
Evolution Objective Profile
Budget slice
```

输出为 `0..N` 个 Proposal Draft，规范化后形成既有 `MutationProposal`。

首个 `llm_guided_sparse_mutation` 实现必须有候选数、修改字段数、修改组件数、novelty、重复提案和预算硬上限。

### 4. V1 允许资产化复用，不建设 V2 Gene Pool

成功 Mutation 可以沉淀为版本化 Artifact/Profile/Policy/Skill/Tool/Workflow，并携带 provenance 与 compatibility metadata。其他 Agent 可在自己的 EvolutionRun 中通过普通 `MutationProposal(mutation_type=transfer)` 引用并重新评测。

V1 不实现自动跨 Agent 传播、Species、Population、Gene Pool 生命周期或 Ecosystem Fitness。

### 5. 人类审查使用 Projection，不新增审批对象

从现有 Trigger、Diagnosis、Mutation、Eval、Release 和 Evidence refs 生成 Human-readable Mutation Review Projection，表达：问题、证据、根因、改动、未改边界、收益、风险、评测、回滚和审批要求。

生产晋升仍使用既有 Release Governance；本 ADR 不新增新的 Release Authority。

### 6. Evolution 攻击面纳入既有安全/可观测体系

V1 必须覆盖 Evidence poisoning、延迟 Prompt Injection、Trigger flooding、Eval/Repair-history poisoning、R4 artifact supply chain、Judge manipulation、Budget exhaustion 和伪装成修复的自提权。

Evolution Kernel 自身健康通过模块 09 的普通结构化 meta-metrics 观察，不建设递归“AI 监控 AI”系统。

## 后果

正面影响：

- Sparse Mutation 从原则变成机器可执行约束；
- Candidate 可在多目标条件下相对 baseline 做可解释选择；
- Strategy 可替换但不再是无契约的自由实现；
- 成功经验可被资产化复用，同时不把 V2 Gene Pool 提前带入 V1；
- 企业 Owner 可以理解和审查 Mutation；
- Evolution 链自身的攻击面进入安全与 SRE 范围。

代价：

- Subject Profile、Objective Profile 与 Strategy Profile 需要版本治理和兼容测试；
- Candidate Build 前增加一层 Mutation schema/constraint 校验；
- 多目标权衡需要业务 Owner 明确 KPI 和可接受退化区间；
- R4 Candidate 的安全和供应链评测成本更高。

## 被否决方案

### 新增 GeneSpace / FitnessRecord / ExperimentPlan Canonical Object

否决。现有 Profile、Registry metadata、Eval 和 Budget 语义足以表达 V1 所需约束，新增对象会扩大语义表面积。

### 让 LLM 直接解释自由 `change_summary` 并执行

否决。无法稳定做类型、范围、权限、frozen field 和跨字段机器校验。

### 用单一 Fitness Score 覆盖所有维度

否决。会隐藏安全硬失败、业务/成本 trade-off 和证据不确定性。

### 在 V1 建设自动跨 Agent Gene Pool 传播

否决。该能力属于 V2；V1 只保留 Artifact 化和目标侧重新评测的复用桥梁。

## 重审条件

- Profile 无法表达真实 Subject 的可变生命周期；
- 多目标选择需要独立并发、状态迁移或跨模块稳定契约，现有 Eval/Profile 无法承载；
- V2 正式进入 Current，需要 Gene Pool/Capability Transfer 独立生命周期；
- Strategy 数量和团队边界扩大到需要独立服务部署，且有容量/信任域证据支持。
