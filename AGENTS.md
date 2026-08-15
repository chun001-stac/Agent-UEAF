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

然后再读当前任务对应功能模块、V1 ADR、实施规范和必要参考架构。V2/V3 文档只用于确认边界，不用于推导 Current 实现。

## 2. 文档优先级

```text
核心规范
> 总体设计
> ADR
> 功能模块
> 实施规范
> 参考架构
```

实施规范只机器化上层语义，不能覆盖它。

## 3. V1 Evolution 严格范围

只有五个 Evolution Canonical Object：

```text
EvolutionTrigger
EvolutionRun
GenomeManifest
MutationProposal
EvolutionAuthorityPolicy
```

不得新增/恢复：

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

## 4. 审计后强制收敛规则

### 4.1 Canonical Meta

所有跨模块持久化对象继承核心 `ContractMeta`。功能文档只列领域字段时视为增量字段，不可省略 `meta`。

### 4.2 Event

只有一套公共 `EventEnvelope`，字段和命名来自核心规范 03：

```text
ueaf.<domain>.<past_tense_fact>
```

不得创建简化 Event Envelope 或未登记 public `ueaf.*` event。当前 Evolution lifecycle event 未注册时只能是 Module 11 internal metadata/event。

### 4.3 Error

```text
API / cross-process -> ProblemDetail
Port               -> PortResult<T> / PortError
```

不得新建公共 `ErrorEnvelope`。

### 4.4 Port

公共最小 SPI 以核心规范 04 为唯一来源。特别是：

```text
RuntimeAdapter:
DescribeRuntime / StartRun / AdvanceRun / SuspendRun / ResumeRun / CancelRun / InspectRun

RuntimeExecutionContext:
ContextBuildPort / ModelStepPort / ToolIntentPort / HandoffPort / TelemetryPort

TelemetryPort:
EmitTrace / EmitMetric / EmitLog / EmitAudit
```

convenience method 只能是可选私有扩展。

### 4.5 PrincipalContext

只使用核心字段。顶层 `tenant_id` 是 MUST，并且 MUST 与 `meta.tenant_id` 相同；它不是可选镜像。不得再造 `subject_id/identity_provider/assurance_level/...` 版第二 `PrincipalContext`。

### 4.6 Risk type

```text
TaskEnvelope.risk_class:
compute_only | read_only | reversible_write | high_risk_write

Evolution RepairLevel:
概念标签：R0 | R1 | R2 | R3 | R4 | R5
wire / Schema / config：r0 | r1 | r2 | r3 | r4 | r5
MutationProposal.repair_level：r1 | r2 | r3 | r4
```

不得混用 Task risk 与 RepairLevel，也不得把大写概念标签写入 wire enum。`R0/r0` 只表达运行处置，不产生长期 Mutation；`R5/r5` 只路由独立治理，不产生 `MutationProposal`。

### 4.7 ReleaseManifest

线级版本字段使用 plural version-set 语义：

```text
agent_versions / prompt_versions / schema_versions / model_route_versions /
capability_versions / adapter_versions / knowledge_index_versions /
memory_policy_versions / policy_versions
```

### 4.8 Evolution build chain

```text
MutationProposal
-> machine validation
-> GenomeManifest candidate
-> ReleaseCandidate
-> Eval / Gates / Release
```

不得跳过 Genome candidate。

## 5. 通用不变量

- 每种权威事实只有一个 Semantic Owner；
- `RunPhase` 与 `CompletionDisposition` 正交；
- 精确 `RuntimeAdapter`/CapabilityBinding 在创建 Run 前选择，`runtime_adapter_ref` 在创建时冻结；admission 后不得重选或静默切换；
- Runtime Adapter 不绕过 Model/Tool/Context/Telemetry；
- 权威状态与公共事件通过 transactional outbox、同一事务日志或可证明等价机制原子关联；
- 所有企业副作用经过 Tool Gateway；
- action identity 在 Policy 前稳定，side effect 在 Policy/Approval/Reservation 后执行；
- Tool timeout/unknown 先 reconciliation；
- 当前 `ReleaseManifest` 不原地自改；
- Subject/Builder/Judge/Release Authority 隔离；
- Governance Kernel 不进入同一自动递归链；
- Mutation 通过 Subject Profile + Effective Mutation Surface 校验；
- Candidate/Eval/Budget/Release 复用既有语义；
- 正常 Evidence Collection/Aggregation/Trigger Candidate 目标 0 LLM Token。

## 6. 开发顺序

```text
read normative docs
-> identify CON-* + domain Test IDs
-> define/update canonical machine Schema
-> define core Port/Event mapping
-> add failing tests
-> implement minimum behavior
-> run targeted tests
-> run contract/integration/conformance tests
```

每个涉及公共契约的 PR 必须运行相关 `CON-*`。

`docs/05-实施规范/04-V1验收与一致性测试规范.md` 是 Test ID 前缀注册表，也是 `P0-SCH-*` / `P0-PORT-*` 的唯一具体 ID 与 expected-semantics Owner；实施规范 08 对这两类只能补充 fixture/执行说明。

## 7. Codex MAY 自主决定

- 私有函数/类/文件拆分；
- 不改变公共语义的内部重构；
- fixture 组织；
- 局部算法和性能优化；
- 私有 convenience method。

## 8. Codex MUST NOT 自主决定

- 新 Canonical Object；
- 新未登记 public Event/Decision；
- 第二套同义 Schema/Port/Event/Error；
- 状态机语义改变；
- Security/Governance/Release Gate 放宽；
- Projection 升格 authority；
- Evolution mutable surface 扩大；
- V2/V3 变 Current；
- Runtime/Adapter 直连企业副作用；
- 删除/放宽 normative tests；
- 用更多 retry 掩盖 unknown；
- 用参考架构旧示例覆盖更高优先级契约。

遇到以上需求，停止扩大代码，先回文档/ADR。

## 9. Reference Implementation Default

首版默认：

```text
Python 3.12+
FastAPI
Pydantic v2 + canonical JSON Schema
PostgreSQL 16+
SQLAlchemy 2.x + Alembic
NATS JetStream
OpenTelemetry
S3-compatible / local MinIO
LangGraph Adapter #1
OpenAI Agents SDK read-only Adapter #2
deterministic fake/recorded model in CI
pytest + Ruff + mypy + GitHub Actions
```

这是 Reference Profile，不是 UEAF 供应商绑定。

## 10. Task / PR Definition of Done

任务必须明确：

```text
Scope
Normative docs
Relevant Schema
Relevant CON-* / domain Test IDs
Allowed modules/files
Non-goals
Definition of Done
```

完成报告：

```text
Tests passed
Schema changes
DB migration changes
Port/Event changes
Security impact
Known gaps
Whether normative semantics changed
```

若规范语义发生变化，代码和文档/ADR 必须同步。
