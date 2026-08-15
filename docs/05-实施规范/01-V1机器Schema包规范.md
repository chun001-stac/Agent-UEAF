# UEAF V1 机器 Schema 包规范

版本：`0.2.0-draft`  
规范状态：Draft  
Architecture Generation: `V1`  
Maturity: `Required for Implementation`  
Implementation: `Current`

## 1. 目的

本文把 V1 已定义的 Canonical Object、跨模块契约、Profile、Event 和 Projection 约束转换为可被代码生成、静态校验、契约测试和 Codex 直接消费的机器 Schema 规则。

本文不新增领域对象。Schema 只是既有语义的机器表达，不成为第二真相源。

## 2. Schema 包结构

参考实现 SHOULD 维护独立 `schemas/` 目录：

```text
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
```

每个 Schema 文件 MUST：

- 有稳定、可由 Registry 解析的逻辑 `$id`；不得从文件路径临时推导；
- 在文件顶层有独立 `x-ueaf-schema-version`，值为 SemVer；不得用领域对象内部的 `schema_version` 代替；
- 明确 required/optional/nullability；
- 禁止未声明字段，除非规范明确要求扩展点；
- 对 enum、长度、范围、pattern、数组大小和对象结构做机器限制；
- 不把实现内部数据库字段混入公共语义 Schema。

## 3. 公共 Schema 继承规则

### 3.1 `ContractMeta` 是公共基类语义

`01-统一术语与对象模型.md` 规定：所有跨模块持久化对象 MUST 包含 `meta: ContractMeta`。后续核心规范、功能模块和 ADR 中只列出的领域字段，均视为在公共 `ContractMeta` 之外的增量字段，不表示可以省略 `meta`。

因此机器 Schema MUST：

```text
cross-module persistent object
  = ContractMeta
  + domain-specific fields
```

至少包括：

```text
contract_name
contract_version
object_id
tenant_id
created_at
producer
producer_version
classification
purpose
provenance
integrity_ref when required
expires_at when applicable
extensions
```

对象自身的规范 ID（例如 `run_id`、`action_id`、`evolution_trigger_id`）与 `meta.object_id` MUST 在应用层/validator 中保持一致；JSON Schema 无法表达跨字段相等时，必须由生成的 validator/contract test 补充校验。

### 3.2 公共交互/错误 Schema

必须机器化并复用核心规范中的：

```text
ContractMeta
CommandEnvelope
EventEnvelope
ProblemDetail
PortResult<T>
PortError
```

V1 不新建 `ErrorEnvelope` 公共 Schema。早期 ADR 中该名称按 ADR-002 的术语收敛说明解释。

## 4. V1 必须机器化的对象

### 4.1 基础运行对象

至少包括：

```text
PrincipalContext
RequestEnvelope
TaskEnvelope
TaskState
BudgetEnvelope
RunRecord
RunAdmissionResult
Checkpoint
ContextManifest
PromptContract
ModelInvocation
ModelRunResult
StructuredDecision
ToolIntent
PolicyDecision
ApprovalRequest
ActionRecord
ActionReceipt
ToolResult
HandoffEnvelope
AuditEvent / AuditRecord where the owning module defines it
```

`PrincipalContext` Machine Schema MUST 同时 require `meta` 与顶层 `tenant_id`。顶层 `tenant_id` MUST 等于 `meta.tenant_id`；JSON Schema 无法表达该跨字段相等约束时，生成的 validator 和 CON-008 contract test MUST 强制校验，不能把顶层字段降格为 optional mirror。

状态值对象至少包括：

```text
RunPhase
WaitReason
CompletionDisposition
ActionPhase
ActionDisposition
```

### 4.2 Eval / Release

至少包括：

```text
ReleaseCandidate
EvalCase
EvalDataset
EvalConfig
EvalRun
EvalResult
QualityGateDecision
SecurityGateDecision
OperationalReadinessDecision
ReleaseDecision
ReleaseManifest
```

`ReleaseManifest` MUST 使用核心对象模型定义的“版本集合”语义；实现不得从下层示例推导出另一套单组件清单。

### 4.3 Evolution V1 五个 Canonical Object

必须包括：

```text
EvolutionTrigger
EvolutionRun
GenomeManifest
MutationProposal
EvolutionAuthorityPolicy
```

V1 不创建：

```text
FitnessRecord
GeneSpace
RepairPlan
DiagnosisResult
RepairHistory
CandidateRelease
EvolutionBudget
LineageGraph
```

这些概念继续按核心规范作为 Profile、Projection、metadata、existing object 或 internal detail 表达。

### 4.4 `RepairLevel` 机器编码

大写 `R0`–`R5` 只用于文档中的概念标签。Machine Schema、wire、持久化 enum 和 config MUST 使用：

```text
r0 | r1 | r2 | r3 | r4 | r5
```

适用边界：

- Diagnosis/Router/Policy metadata MAY 使用 `r0`–`r5`；
- `MutationProposal.repair_level` 的 enum MUST 严格为 `r1 | r2 | r3 | r4`；
- `r0` 不产生长期 Mutation；
- `r5` 只形成 `ROUTE_GOVERNANCE`，不得生成 `MutationProposal`；
- Schema MUST 拒绝大写 `R0`–`R5` 作为 wire 值。

## 5. Profile Schema

### 5.1 Subject Profile

`GenomeManifest.profile_ref` 指向的 Subject Profile MUST 有机器 Schema，至少支持：

```yaml
profile_id: string
subject_type: agent | skill | tool | workflow | strategy
schema_version: string
mutable_fields: []
replace_only_fields: []
bounded_fields: []
conditional_fields: []
frozen_fields: []
cross_field_constraints: []
mutation_limits: object
```

每个可变字段至少包含：

```yaml
path: string
type: string
operations: [replace | add | remove]
required_repair_levels: [r1 | r2 | r3 | r4]
risk_class: string
```

并按类型补充：

```text
number/integer -> min/max/step
string -> enum/pattern/minLength/maxLength
ref -> allowed_registry / compatibility_profile_ref
array -> item type / minItems / maxItems / uniqueness
object -> nested schema ref
```

### 5.2 Evolution Objective Profile

必须可机器校验：

```text
primary_objectives
hard_constraints
guardrails
business_metric_mapping
minimum evidence confidence
selection method
tie breakers
```

禁止只有一个无分项来源的 `fitness_score`。

### 5.3 Strategy Profile

至少包含：

```text
strategy_id
strategy_type
max_candidates
max_fields_per_candidate
max_components_per_candidate
max_scopes_per_candidate
allow_mixed_repair_levels
require_single_hypothesis
novelty policy
budget refs/limits
```

## 6. MutationPatch Schema

`MutationProposal.change_summary` 继续用于人类摘要；机器执行 MUST 使用结构化 `changes[]`。

推荐最小结构：

```yaml
changes:
  - target_ref: string
    path: string
    operation: replace | add | remove
    before: any
    after: any
    constraint_profile_ref: string
```

Validator MUST 验证：

```text
path exists in profile mutation surface
operation allowed
value type valid
range/enum/ref valid
repair level compatible
frozen fields untouched
cross-field constraints remain valid
path belongs to effective mutation surface
```

任何校验失败 MUST 在 `GenomeManifest` candidate materialization / Candidate Build 前失败。

## 7. Command / Event Schema

### 7.1 `CommandEnvelope`

跨进程 Command MUST 直接使用核心规范 03 的字段和枚举。实施层不得删减为另一套 envelope。

### 7.2 `EventEnvelope`

所有跨模块权威事件 MUST 直接复用核心规范 03 的完整 `EventEnvelope`：

```text
event_id
event_name
event_version
occurred_at
recorded_at
tenant_id
aggregate_type
aggregate_id
aggregate_version
sequence
producer
producer_version
correlation_id
causation_id
trace_id
principal_ref
release_id
payload_schema_ref
payload
classification
purpose
integrity_ref when required
```

不得另建 `event_type/aggregate_ref/revision/correlation_refs` 形式的第二套事件 Envelope。

事件名称 MUST 使用：

```text
ueaf.<domain>.<past_tense_fact>
```

而不是 PascalCase 类型名。

### 7.3 Machine Event Catalog

`schemas/events/event-catalog.json` 是核心规范 03 公共事件目录的机器化注册索引，不是第二语义真相源。核心规范 03 仍拥有 public event 集合与命名语义；Contract/Schema Registry 是该机器 catalog 的唯一 State Writer，各事件的领域 Semantic Owner 负责其 payload 语义。

每个 catalog registration 使用唯一键：

```text
(event_name, event_version)
  -> exactly one payload_schema_ref
```

完整校验 tuple 为：

```text
(event_name, event_version, payload_schema_ref)
```

规则：

- 同一 `(event_name, event_version)` 重复登记 MUST 失败；
- 同一键映射到不同 `payload_schema_ref` MUST 作为契约冲突失败；
- `payload_schema_ref` MUST 解析到本地/发布 Registry 中已登记且版本固定的 Schema `$id`；
- EventEnvelope 的 `event_name`、`event_version`、`payload_schema_ref` MUST 与 catalog tuple 完全一致，payload 再由该 Schema 校验；
- `catalog_version` 与 catalog 顶层 `x-ueaf-schema-version` 均为 SemVer；已发布相同版本内容不可改写；
- 新增或修改 public event 必须先更新核心规范 03/必要 ADR，再由 catalog owner 编译登记，模块不得自行写入。

## 8. ID、Ref 与 Version 规范

公共 Schema 中引用 SHOULD 使用显式 `<name>_ref` 或 `<name>_refs`，禁止仅用模糊 `id` 表达不同领域含义。

建议：

```text
*_id       = 当前对象自身标识
*_ref      = 指向其他领域对象/Artifact/Profile 的稳定引用
*_version  = Schema/Policy/Artifact 语义版本
integrity_ref = 内容完整性/签名引用
```

Schema version 与对象业务版本必须分离。

### 8.1 Schema Registry identity 与不可变版本

Machine Schema 的注册身份由以下 tuple 表达：

```text
($id, x-ueaf-schema-version)
```

- `$id` 是稳定逻辑标识和 `$ref` 解析键；Registry/consumer MUST NOT 通过文件路径或从 `$id` 文本猜测版本；
- `x-ueaf-schema-version` 是该 Schema 文件的规范 SemVer；每个 `*.schema.json` 顶层 MUST 存在；
- 当前发布包中 `$id` MUST 唯一；重复 `$id` 即使版本不同也必须失败，避免 active resolution 歧义；
- Registry MUST 校验 `$id` 非空且唯一、`x-ueaf-schema-version` 为合法 SemVer、所有本地 `$ref` 可解析；
- 已发布的同一 `($id, x-ueaf-schema-version)` MUST 映射到同一规范内容/摘要，禁止原地改写；任何文件内容或机器约束变化都必须产生新的 SemVer；
- Release/ContractBundle/Event Catalog 引用 Schema 时 MUST 冻结可解析到该 tuple 的引用，不得静默漂移到“latest”；
- 领域 payload 内名为 `schema_version` 的业务字段不替代文件级 `x-ueaf-schema-version`，两者生命周期分离。

## 9. 时间与金额

- timestamp MUST 使用带时区 RFC3339；
- duration SHOULD 使用显式毫秒整数或命名清晰的 duration 字段；
- 金额不得使用二进制浮点表达权威账本值；
- currency 必须显式；
- Token、计数、重试次数使用非负整数。

## 10. Enum 与扩展

核心 enum 新增值属于契约演进，不允许实现端私自接受任意自由字符串。

若需要供应商扩展字段，必须放入显式 namespaced extension，例如：

```yaml
extensions:
  vendor.example: {...}
```

Extension 不得覆盖 UEAF 规范字段语义。

## 11. Schema Compatibility

V1 推荐：

```text
PATCH: 文档/约束澄清，不改变兼容机器结构
MINOR: 新增向后兼容 optional 字段/enum 兼容扩展
MAJOR: required 字段、语义或不兼容枚举变化
```

上表描述新版本号的兼容含义，不允许在原版本上覆盖内容。即使只是 Schema 文件内的澄清，只要发布内容发生变化，也必须至少递增 PATCH 并保留旧 tuple 的不可变解析。

长运行 Run 绑定启动时兼容的 Schema/Release 版本，不因控制面升级而静默改变。

## 12. Code Generation

参考实现 SHOULD 从 Schema 生成或校验：

```text
Python models
API request/response models
Event payload models
JSON Schema validation
contract test fixtures
example payload validation
```

生成代码不得反向成为规范真相源；规范 Schema 才是接口结构来源。

## 13. 示例与 Fixtures

每个 MUST 实现的 Schema 至少提供：

```text
1 valid minimal example
1 valid full example
>=2 invalid examples
```

关键对象额外提供边界用例：

- unknown enum；
- missing required field；
- invalid ref；
- range overflow；
- frozen Mutation；
- incompatible repair level；
- invalid terminal state combination；
- missing/invalid `ContractMeta`；
- malformed `EventEnvelope`；
- object-specific id 与 `meta.object_id` 不一致。

## 14. Codex 实施规则

Codex 开发时 MUST：

1. 先生成/完善 Schema，再写对应 handler/service；
2. 不自行新增公共字段解决实现方便问题；
3. 不把数据库 ORM model 当作 API/Event Schema；
4. 遇到规范缺口先新增 failing contract test 和文档 TODO，不自行创造第二套语义；
5. 公共对象命名严格使用当前 README/核心规范名称；
6. 禁止恢复 `AgentGenome`、`CandidateRelease`、`EvolutionBudget`、`ErrorEnvelope` 等已被收敛的旧名；
7. 领域示例遗漏公共 `meta` 时，按核心对象规范补入，而不是把遗漏解释为 optional。

## 15. 完成定义

Machine Schema Package 完成至少满足：

- V1 主链关键对象均有机器 Schema；
- `ContractMeta` / Command / Event / ProblemDetail / PortError 有唯一机器定义；
- 五个 Evolution Canonical Object 均可独立校验；
- Subject/Objective/Strategy Profiles 可校验；
- Mutation `changes[]` 可拒绝越权/越界修改；
- 示例 payload 全部自动验证；
- Schema compatibility 测试进入 CI；
- Registry 强制 stable `$id`、文件级 `x-ueaf-schema-version`、唯一 active `$id`、可解析 `$ref` 和同版本不可变；
- machine event catalog 以 `(event_name, event_version)` 唯一登记并固定一个 `payload_schema_ref`；
- Codex 不需要通过 Markdown 自行猜字段类型、nullability、公共 meta 和枚举。
