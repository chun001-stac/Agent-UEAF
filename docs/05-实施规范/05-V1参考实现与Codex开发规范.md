# UEAF V1 参考实现与 Codex 开发规范

版本：`0.2.0-draft`  
规范状态：Draft  
Architecture Generation: `V1`  
Maturity: `Required for Reference Implementation`  
Implementation: `Current`

## 1. 目的

本文固定 UEAF V1 首个参考实现的技术 Profile、仓库结构、依赖边界、开发顺序和 Codex 工作规则。

它不是 UEAF 产品对外的语言/框架绑定；其他实现可使用不同技术栈，只要通过相同 Schema、Port、Event 和 Conformance Suite。

## 2. 首个 Reference Implementation Profile

首版默认采用：

```text
Language                 Python 3.12+
API                      FastAPI
Data validation          Pydantic v2 + canonical JSON Schema
Persistence              PostgreSQL 16+
ORM                       SQLAlchemy 2.x
Migration                 Alembic
Durable broker            NATS JetStream, hidden behind Queue/Event adapter
Telemetry                 OpenTelemetry
Artifact storage          S3-compatible; local dev default MinIO
Secret provider           adapter abstraction; local dev only uses environment/test secret backend
Runtime Adapter #1        LangGraph
Runtime Adapter #2        OpenAI Agents SDK read-only conformance adapter
Model provider in CI      deterministic fake/recorded adapter; no live provider required for CI correctness
Tests                     pytest + contract/integration/conformance/failure-injection suites
Lint / format             Ruff
Type checking             mypy
CI                        GitHub Actions
Packaging                 pyproject.toml + lock file
```

版本范围在实际初始化代码时冻结到 lock file；文档不要求永久绑定具体 minor version。

上述选择是 **Reference Implementation Default**，不是 UEAF 规范依赖。替换 broker、对象存储、模型 Provider 或第二 Runtime Adapter 不得改变 Port/Event/Schema/状态语义。

## 3. 为什么 Python-first

首个 V1 目标是快速证明 Runtime Adapter、Tool Gateway、Eval 和 Evolution Vertical Slice，而不是建立多语言平台。

Python-first 的理由：

- Agent/LLM 生态成熟；
- LangGraph 与模型 SDK 集成成本低；
- Pydantic/JSON Schema 适合契约驱动；
- pytest 适合 failure injection / contract test；
- 后续仍可通过 HTTP/Event/Schema 增加其他语言实现。

## 4. 推荐仓库结构

```text
AGENTS.md
README.md
pyproject.toml
schemas/
  common/
  admission/
  runtime/
  model/
  context/
  tool/
  workflow/
  security/
  eval/
  release/
  telemetry/
  evolution/
  profiles/
  events/
src/ueaf/
  common/
  admission/
  runtime/
  model/
  context/
  tool/
  workflow/
  security/
  eval/
  operations/
  developer/
  evolution/
  adapters/
    runtimes/
    models/
    tools/
    storage/
    queue/
  infrastructure/
    db/
    queue/
    telemetry/
    artifact/
tests/
  schema/
  unit/
  contract/
  integration/
  conformance/
  failure_injection/
  vertical_slices/
migrations/
docs/
```

模块数量不等于独立服务数量，继续遵守 ADR-004 的模块化单体优先。

## 5. 包依赖规则

业务模块之间通过 Port/Contract 协作，禁止共享数据库模型绕过语义边界。

推荐依赖方向：

```text
canonical schemas / common contracts
        ↑
module domain + application
        ↑
adapters + infrastructure
```

具体禁止：

```text
runtime -> provider SDK directly          forbidden
runtime -> enterprise tool API directly  forbidden
evolution -> release DB writer directly  forbidden
evolution -> raw telemetry tables scan   forbidden
judge -> business tool adapter            forbidden
adapter -> redefine UEAF state enum       forbidden
module -> another module ORM model        forbidden
```

## 6. Domain 与 ORM 分离

公共 Schema / Domain Model 不能直接等价为 ORM Model。

建议：

```text
canonical schema / generated transport model
  -> application/domain object
  -> repository mapping
  -> ORM row
```

ORM 的 `created_at`、internal sequence、DB FK 等实现字段不得无意泄漏进公共契约。反向也一样：核心 `ContractMeta` 不能因为 ORM 不方便而被省略。

## 7. Port-first 开发

每个模块的开发顺序：

```text
Normative docs
-> machine Schema
-> Port interface
-> failing contract tests
-> domain implementation
-> adapter/infrastructure
-> integration tests
```

禁止先写具体 Provider SDK，然后反向定义 UEAF 契约。

公共 Port 名称和方法以 `docs/01-核心规范/04-端口与适配器规范.md` 为唯一最小 SPI。功能模块中的 convenience method 只能是实现扩展，不能替代核心 SPI。

## 8. V1 开发 Phase

### Phase 0 — Repository Skeleton

必须建立：

```text
pyproject / lock
src layout
schemas layout
test layout
DB migration harness
NATS JetStream dev container/fixture
MinIO dev container/fixture
CI
Ruff / mypy / pytest commands
AGENTS.md
```

### Phase 1 — Admission + Run State

交付：

```text
ContractMeta / CommandEnvelope / EventEnvelope / ProblemDetail
RequestEnvelope
TaskState
RunRecord
RunAdmissionResult
state machine
CAS/revision
outbox
RUN-* acceptance tests
```

### Phase 2 — Runtime + Model + Context

交付：

```text
RuntimeAdapter core SPI
LangGraph Adapter
ModelStepPort
ContextBuildPort
PromptContract
read-only vertical slice
OpenAI Agents SDK read-only conformance adapter skeleton
```

CI 的行为正确性使用 deterministic fake/recorded model adapter；live model Provider 只用于显式 integration profile，不成为基础测试前置条件。

### Phase 3 — Tool Gateway / Action

交付：

```text
ToolIntent
PolicyDecision bridge
ActionRecord
ExecutionAttempt
ActionReceipt
reconciliation
approval wait/resume
ACT-* tests
```

### Phase 4 — Eval / Release

交付：

```text
ReleaseCandidate
EvalConfig/Run/Result
Quality/Security/Operational decision refs
ReleaseDecision
ReleaseManifest
rollback
REL/EVAL tests
```

### Phase 5 — Evidence

交付：

```text
L0 structured observation mapping through core TelemetryPort
RunSummary projection
rolling windows
ErrorFingerprint
TriggerCandidate detector
L0/L1/L2 evidence flow
EVD-* tests
```

不得创建与核心 `TelemetryPort` 同名但签名不同的 `emit(TelemetryEvent)` 公共 Port。

### Phase 6 — Evolution V1

交付：

```text
EvolutionTrigger
EvolutionRun
GenomeManifest
MutationProposal
EvolutionAuthorityPolicy
Subject Profile
Mutation Validator
Objective Profile
llm_guided_sparse_mutation Strategy
Evolution Vertical Slice
```

首版 Evolution 只要求 Single-Candidate First，并保持：

```text
MutationProposal
-> GenomeManifest candidate
-> ReleaseCandidate
-> Eval
```

禁止从 Mutation 直接跳过 Genome candidate。

## 9. 不允许 Codex 提前实现

除非文档状态更新，否则不得实现为 Current：

```text
Species Service
Gene Pool DB
Population Scheduler
Ecosystem Fitness Service
Diversity Service
Meta Evolution
Dynamic Niche/Species
ModelEvolutionPort
automatic cross-agent propagation
```

这些属于 V2/V3。

## 10. Codex 每个任务的输入格式

建议给 Codex 的开发任务包含：

```text
Scope
Normative docs
Relevant Schema files
Relevant Test IDs
Allowed modules/files
Non-goals
Definition of Done
```

例如：

```text
Task: Implement Action timeout reconciliation
Normative:
- docs/02-功能模块/05-工具MCP与动作执行.md
- docs/05-实施规范/02-V1-API端口与事件契约.md
- docs/05-实施规范/03-V1持久化与事务映射.md
Tests:
- ACT-002
- ACT-003
Non-goals:
- evolution mutation
- new tool provider abstraction
Done:
- contract/integration tests green
```

## 11. Codex 决策边界

Codex MAY 自主决定：

- 私有函数拆分；
- 局部算法实现；
- 测试 fixture 组织；
- 不改变规范的内部重构；
- 性能优化且行为不变。

Codex MUST NOT 自主决定：

- 新 Canonical Object；
- 新 public event/type；
- 修改状态机语义；
- 修改 Governance Kernel；
- 放宽权限/安全 Gate；
- 增加 V2/V3 Current 范围；
- 把 Projection 提升为 authority；
- 改变 Tool timeout outcome semantics；
- 删除/放宽 normative acceptance tests；
- 建立核心规范已有对象/Port/Event 的同义替代名称。

出现以上需求，必须先回到文档/ADR。

## 12. 文档优先级

Codex 遇到冲突按 README 规定：

```text
核心规范
> 总体设计
> ADR
> 功能模块
> 实施规范
> 参考架构
```

其中实施规范只能把上层规范机器化，不得覆盖核心语义。

若同层文档冲突，优先版本更新且明确 Current/Required 的文档，并记录冲突，不自行混合两种设计。

## 13. Test-first 规则

涉及规范行为的任务：

```text
1 read docs
2 identify Test IDs
3 add/confirm failing test
4 implement minimum behavior
5 run targeted tests
6 run module contract tests
7 run relevant integration/conformance
8 summarize changed semantics = none/new ADR required
```

禁止先大规模生成代码再回头补测试。

## 14. Commit / PR 粒度

每个 PR SHOULD 聚焦一个纵向能力或一个明确模块契约，例如：

```text
admission state skeleton
runtime adapter model gateway bridge
action reconciliation
evolution mutation validator
```

避免一次 PR 同时重构多个语义域。

PR 描述至少列：

```text
Normative docs
Test IDs
Schema changes
DB migrations
New/changed events
Security impact
Known gaps
```

## 15. 禁止旧术语

代码、表名、公共 API 不得重新使用已收敛旧术语：

```text
AgentGenome        -> GenomeManifest
CandidateRelease   -> ReleaseCandidate
EvolutionBudget    -> existing Budget domain / budget_ref
FitnessRecord      -> Eval/Objectives projection
LineageGraph truth -> Projection
ErrorEnvelope      -> ProblemDetail (cross-process) / PortError (Port)
```

## 16. Local Development Profile

本地默认：

```text
PostgreSQL container
NATS JetStream container
MinIO container
deterministic fake model provider
mock external business API
non-production secret backend
```

Mock 不能绕过 Tool Gateway、ActionRecord、Policy、Eval 或 Release 边界。

## 17. Observability in Dev

从第一阶段开始保留：

```text
trace_id/run_id correlation
structured logs
module/stage/error_code
outbox lag
queue lag
DB transaction errors
model/tool usage counters
```

但不得把高基数 ID 变成常规 Metrics label。

## 18. Security Development Rules

- Secrets 不进入 repo/test fixtures；
- 外部写 API 默认使用 mock/test tenant；
- R4 generated code 只进入 sandbox/build pipeline；
- Judge service identity 无业务写权限；
- Evolution test 不允许改变 Governance Kernel；
- security hard-fail tests 永远不能通过普通配置关闭。

## 19. “停止编码，回文档”的条件

Codex/工程师发现以下情况必须停止扩大实现：

1. 一个新事实需要第二 Semantic Owner；
2. 现有 Schema 无法表达且需要新 public object；
3. 状态机出现未定义状态/迁移；
4. Port timeout/outcome 语义冲突；
5. 必须扩大 mutable surface 才能完成任务；
6. 需要放宽 Governance/Security；
7. V2/V3 概念成为实现依赖；
8. 需要新增未注册 `ueaf.*` public event。

此时先形成文档问题或 ADR，而不是代码 workaround。

## 20. V1 Documentation Code-Ready Gate

在“文档可以交给 Codex 开始 Phase 0”之前应满足：

```text
[x] Machine Schema package specification exists
[x] API/Port/Event contract specification exists
[x] Persistence mapping specification exists
[x] Acceptance Test IDs exist
[x] Reference implementation profile fixed
[x] root AGENTS.md points to normative docs
[x] first read-only vertical slice scope is defined by phases/tests
[x] Evolution Vertical Slice fixture is defined in acceptance spec
```

这表示 **文档准备度**，不表示仓库已经存在实际 `schemas/*.json`、迁移、CI 或代码。

## 21. Phase 0 Exit Gate

Codex 完成 Phase 0 后才应满足：

```text
[ ] canonical Machine Schema skeleton exists
[ ] pyproject + lock exists
[ ] migrations harness exists
[ ] GitHub Actions CI exists
[ ] Ruff/mypy/pytest commands green
[ ] NATS/PostgreSQL/MinIO local profile starts
[ ] RUN/ACT/EVO/MUT/REL test file skeleton exists
[ ] first read-only vertical slice task can start
```

## 22. 完成定义

当本文及前四份实施规范落地后，V1 文档应足以让 Codex：

- 创建项目骨架；
- 按阶段实现模块；
- 不自行发明核心对象、错误契约、Port 和状态；
- 通过机器 Schema 和测试发现偏差；
- 在真正遇到规范缺口时明确回到文档，而不是把猜测写进代码。
