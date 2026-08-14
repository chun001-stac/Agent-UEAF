# UEAF V1 API、Port 与事件契约规范

版本：`0.1.0-draft`  
规范状态：Draft  
Architecture Generation: `V1`  
Maturity: `Required for Implementation`  
Implementation: `Current`

## 1. 目的

本文把现有模块边界转换为可实现的 API、内部 Port 和 Event 契约。目标是让 Codex/工程实现者不需要自行猜测调用方向、错误语义、幂等、超时、重试和事件所有权。

## 2. 契约模板

每个公共 API / Port MUST 明确：

```text
name
semantic owner
caller / callee
input schema
output schema
errors
idempotency
authorization
side-effect class
timeout semantics
retry semantics
ordering/concurrency
telemetry/audit requirements
contract version
```

不得只定义函数名而省略失败和结果不确定语义。

## 3. 外部 API 最小集合

V1 Reference API SHOULD 至少支持：

```text
POST /v1/tasks                 接收 RequestEnvelope
GET  /v1/tasks/{task_id}       查询 TaskState projection
GET  /v1/runs/{run_id}         查询 RunRecord
POST /v1/runs/{run_id}/cancel  请求取消
POST /v1/runs/{run_id}/resume  合法等待场景恢复
GET  /v1/actions/{action_id}    查询 ActionRecord/outcome
GET  /v1/releases/{release_id} 查询 ReleaseManifest
```

Evolution Control API MAY 仅面向内部/控制面：

```text
POST /v1/evolution/triggers/{id}/runs
GET  /v1/evolution/runs/{id}
GET  /v1/evolution/mutations/{id}
```

是否暴露创建 Trigger 的人工 API 由 Policy 决定；普通客户端不能伪造自动 Trigger Gate 事实。

## 4. 关键内部 Port

### 4.1 RuntimeAdapter

```text
start(run_context) -> runtime_handle
resume(run_context, checkpoint_ref, signal) -> runtime_handle
cancel(run_context, reason) -> cancel_ack
stream(runtime_handle) -> normalized runtime events
checkpoint(runtime_handle) -> checkpoint_ref
capabilities() -> RuntimeCapabilityManifest
```

规则：

- 一个 Run 只能绑定一个 active Runtime Adapter；
- Adapter 不得直接调用 Model Provider 或企业写 API；
- 模型调用必须走 `ModelStepPort`；
- 企业副作用必须走 `ToolIntentPort`；
- unsupported capability 必须显式拒绝。

### 4.2 ModelStepPort

```text
invoke(ModelInvocation) -> ModelRunResult
```

必须定义：

- provider/model route version；
- token/cost/latency measurements；
- structured output validation；
- timeout/provider error/retry classification；
- 不允许 Runtime 持有长期 Provider 凭据。

### 4.3 ContextPort

```text
build(ContextRequest) -> ContextManifest
```

必须保证权限过滤先于相关性排序；返回引用和选择结果，不改变原始业务事实。

### 4.4 ToolIntentPort

```text
submit(ToolIntent) -> ActionRecordRef
```

调用返回“动作已进入受控生命周期”，不等价于业务副作用已经成功。

### 4.5 ActionExecutionPort

Tool Gateway 内部执行：

```text
reserve(ActionRecord) -> Reservation
execute(ExecutionAttempt) -> ActionReceipt | outcome_unknown
reconcile(ActionRecord) -> ActionReceipt | unresolved
```

`timeout` 不得自动映射为 `certain_failure`。

### 4.6 TelemetryPort

```text
emit(TelemetryEvent) -> accepted | dropped_low_priority | unavailable
```

默认非阻塞。Audit/Security/ActionReceipt/P0-P1 使用独立最低可靠性要求，不得与普通 verbose telemetry 等价处理。

### 4.7 CandidateBuildPort

```text
build(MutationProposal, baseline_genome_ref) -> ReleaseCandidate
```

Candidate Build 前 MUST 先完成 Mutation Validator 校验。

### 4.8 EvaluationPort

```text
run(EvalConfig) -> EvalRunRef
get_results(EvalRunRef) -> EvalResult[]
```

Judge/Graders 只产生证据，不拥有 Release 权限。

### 4.9 EvolutionStrategyPort

```text
propose(StrategyInput) -> ProposalDraft[]
```

输入和输出遵守核心规范 09；输出允许为空。

## 5. Error Contract

所有跨模块错误 SHOULD 映射到 `ErrorEnvelope`，至少包含：

```yaml
error_code: string
source: string
category: validation | authorization | dependency | timeout | conflict | capacity | internal
retryability: retryable | non_retryable | conditional | unknown
outcome_certainty: certain_success | certain_failure | unknown | not_applicable
message_ref: string | null
evidence_refs: [string]
```

禁止用异常文本字符串作为跨模块唯一语义。

## 6. Idempotency

必须至少定义：

```text
Task creation -> request idempotency key
Action -> action_key
Event consumer -> event_id / producer sequence / dedup key
EvolutionRun creation -> trigger_ref + policy-controlled uniqueness/cooldown
Release signing -> candidate/environment/decision tuple uniqueness
```

同一幂等键重放不能创建第二个权威对象。

## 7. Timeout / Retry

统一规则：

```text
read-only deterministic dependency
  MAY retry according to policy

external side effect
  timeout -> outcome certainty check -> reconcile before retry

LLM/provider invocation
  retry only when request semantics and budget permit

state mutation conflict
  use CAS/revision/fencing; do not blind overwrite
```

每个 Port 必须显式声明 retry 由 caller 还是 callee 拥有，禁止双层重试放大。

## 8. Event Envelope

所有领域事件 SHOULD 使用统一 Envelope：

```yaml
event_id: string
event_type: string
event_version: string
occurred_at: timestamp
producer: string
tenant_id: string | null
aggregate_ref: string | null
revision: integer | null
correlation_refs: object
payload: object
```

## 9. V1 事件目录最小集合

### Admission / Runtime

```text
TaskQueued
RunAdmitting
RunAdmitted
RunDeferred
RunRejected
RunPhaseChanged
RunWaiting
RunTerminal
CheckpointCreated
```

### Model / Context

```text
ModelInvocationCompleted
ModelInvocationFailed
ContextBuilt
RetrievalObserved
```

### Tool / Action

```text
ToolIntentAccepted
ActionReserved
ExecutionAttemptStarted
ActionSucceeded
ActionFailed
ActionOutcomeUnknown
ActionReconciliationStarted
ActionReconciled
ActionUnresolved
ApprovalRequested
ApprovalResolved
```

### Eval / Release

```text
ReleaseCandidateBuilt
EvalRunStarted
EvalResultProduced
QualityGateDecided
SecurityGateDecided
OperationalReadinessDecided
ReleaseDecided
ReleaseManifestSigned
ReleaseRolledBack
```

### Evolution

```text
EvolutionTriggerCreated
EvolutionRunStarted
EvolutionRunPhaseChanged
MutationProposed
GenomeCandidateCreated
EvolutionRunTerminal
```

Projection-only `TriggerCandidate` 不作为必需跨模块领域事件。

## 10. 事件生产者唯一性

每类权威事件必须由 Semantic Owner 产生。例如：

```text
Run state event -> Run State owner
Action event -> Tool Gateway / Action owner
EvalResult event -> Eval owner
ReleaseManifest event -> Release owner
EvolutionTrigger event -> Trigger owner / Module 11
Mutation event -> Evolution owner / Module 11
```

消费者不得通过发布同名事件改写上游事实。

## 11. Ordering 与 Revision

需要强顺序的同一 aggregate 事件必须携带 revision。消费者：

```text
revision <= current -> duplicate/stale
revision == current + 1 -> apply
revision > current + 1 -> gap / recovery path
```

不要求全局事件总序。

## 12. At-least-once Consumer

V1 默认使用至少一次投递，因此所有消费者 MUST 幂等。禁止把消息队列的“已消费”当作业务事实提交的唯一依据。

权威 DB transaction 与 Event publish SHOULD 使用 transactional outbox 或等价机制。

## 13. Authorization

每个 Port 必须明确 service identity 和 capability scope。尤其：

- Runtime Adapter 无生产企业工具直连权限；
- Judge 无业务写工具权限；
- Evolution Strategy 无 Release Authority；
- Candidate Builder 无 Eval root 修改权限；
- Telemetry Reader 的原始 Payload 读取受数据分类限制。

## 14. Codex 实施规则

Codex MUST：

1. 从 Schema/Port Contract 生成接口，不通过直接模块 import 绕过 Port；
2. 每个 Port 至少实现 happy path、validation error、dependency failure、timeout、idempotency 测试；
3. 副作用路径必须测试 `outcome_unknown`；
4. 不新增未登记事件；
5. 不用框架原生事件替代 UEAF 事件；
6. 不让 consumer 成为第二 State Writer。

## 15. 完成定义

本包完成意味着：

- V1 主链所有跨模块调用有明确 Port；
- 关键外部 API 有 request/response/error 结构；
- 事件目录有 owner、payload、version、dedup/order 规则；
- timeout/retry/idempotency 不再依赖实现者猜测；
- contract tests 可自动验证 Adapter/Module 行为。
