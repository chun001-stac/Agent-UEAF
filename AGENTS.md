# AGENTS.md — UEAF V1 Codex 开发约束

本仓库当前代码、实施和验收默认只针对 **UEAF V1 — Unified Agent Runtime + Controlled Evolution Kernel**。

## 1. 开工前必读

Codex 在修改代码前必须先读取：

```text
README.md
docs/00-总览/06-UEAF架构代际与实施范围.md
docs/01-核心规范/01-统一术语与对象模型.md
docs/01-核心规范/02-状态机与终态规范.md
docs/01-核心规范/03-跨模块契约与事件规范.md
docs/01-核心规范/04-端口与适配器规范.md
docs/01-核心规范/05-受控演化与递归自改规范.md
docs/01-核心规范/07-V1最小Evidence采集规范.md
docs/01-核心规范/08-V1问题诊断与最小修复规范.md
docs/01-核心规范/09-V1可变操作面演化目标与策略契约.md
docs/05-实施规范/README.md
```

然后再读取当前任务对应的功能模块、ADR 和参考架构。

## 2. 文档优先级

冲突时：

```text
核心规范
> 总体设计
> ADR
> 功能模块
> 实施规范
> 参考架构
```

V2/V3 Future/Research 文档不得覆盖 V1 Current。

## 3. V1 严格范围

V1 Evolution Canonical Object 只有：

```text
EvolutionTrigger
EvolutionRun
GenomeManifest
MutationProposal
EvolutionAuthorityPolicy
```

不得新增或恢复：

```text
AgentGenome
CandidateRelease
EvolutionBudget
FitnessRecord
GeneSpace
RepairPlan
DiagnosisResult
RepairHistory authority
LineageGraph authority
Species
Gene Pool
Ecosystem Fitness
Meta Evolution
```

除非先更新规范/ADR。

## 4. 不变量

- 每种权威事实只有一个 Semantic Owner。
- `RunPhase` 与 `CompletionDisposition` 正交。
- Runtime Adapter 不能绕过 UEAF Model/Tool/Context/Telemetry Port。
- 所有企业副作用经过 Tool Gateway。
- Tool timeout/unknown 必须先 reconciliation，不得盲目 retry。
- 当前 `ReleaseManifest` 不得原地自改。
- Subject/Builder/Judge/Release Authority 逻辑隔离。
- Governance Kernel 不进入同一自动递归链。
- Mutation 必须通过 Subject Profile 和 Effective Mutation Surface 机器校验。
- Candidate/Eval/Budget/Release 复用既有 UEAF 语义。
- 正常 Evidence Collection/Aggregation/Trigger Candidate 路径目标为 0 LLM Token。

## 5. 开发顺序

每个规范行为必须按以下顺序：

```text
read normative docs
-> identify Test IDs
-> define/update machine Schema
-> define Port/Event contract
-> add failing test
-> implement minimum behavior
-> run targeted tests
-> run relevant contract/integration/conformance tests
```

禁止先大量写实现再回头改变规范以适配代码。

## 6. Codex 可自主决定

允许：

- 私有函数、类、文件拆分；
- 不改变公共语义的内部重构；
- 测试 fixture 组织；
- 局部算法与性能优化；
- 实现细节命名，只要不改变规范对象/字段/事件。

## 7. Codex 不得自主决定

不得：

- 新增 Canonical Object；
- 新增未登记 public Event/Decision；
- 修改状态机语义；
- 放宽 Security/Governance/Release Gate；
- 把 Projection 变成第二 authority；
- 扩大 Evolution mutable surface；
- 实现 V2/V3 为 Current；
- 让 Runtime/Adapter 直连企业副作用；
- 删除或放宽 normative acceptance tests；
- 通过新增 retry 掩盖 `outcome_unknown`。

遇到上述需求，停止扩大代码并先回文档/ADR。

## 8. PR / Task Definition of Done

每个任务必须明确：

```text
Scope
Normative docs
Relevant Schema
Relevant Test IDs
Allowed modules/files
Non-goals
Definition of Done
```

完成时报告：

```text
Tests passed
Schema changes
DB migration changes
Port/Event changes
Security impact
Known gaps
Whether any normative semantics changed
```

若规范语义发生变化，不能仅提交代码，必须同步文档/ADR。
