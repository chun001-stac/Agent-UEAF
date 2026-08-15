# UEAF V1 API、Port 与事件契约规范

版本：`0.2.0-draft`  
规范状态：Draft  
Architecture Generation: `V1`  
Maturity: `Required for Implementation`  
Implementation: `Current`

## 1. 目的

本文把现有模块边界转换为可实现的 API、内部 Port 和 Event 契约。目标是让 Codex/工程实现者不需要自行猜测调用方向、错误语义、幂等、超时、重试和事件所有权。

本文只机器化核心规范，不重新命名核心 Port、Envelope 或错误契约。

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
POST /v1/tasks                 接收 RequestEnvelope；PrincipalContext 来自可信认证边界
GET  /v1/tasks/{task_id}       查询 TaskState projection
GET  /v1/runs/{run_id}         查询 RunRecord 或明确 consistency 的 projection
POST /v1/runs/{run_id}/cancel  提交规范 CancelRun command
POST /v1/runs/{run_id}/resume  提交规范 ResumeRun command
GET  /v1/actions/{action_id}    查询 ActionRecord/outcome
GET  /v1/releases/{release_id} 查询 ReleaseManifest
```

Evolution Control API MAY 仅面向内部/控制面：

```text
POST /v1/evolution/triggers/{trigger_id}/runs
GET  /v1/evolution/runs/{evolution_run_id}
GET  /v1/evolution/mutations/{mutation_proposal_id}
```

普通客户端不能伪造自动 Trigger Gate 事实。人工触发仍必须形成符合核心规范的 `EvolutionTrigger` 并受 Authority/Budget/Gate 约束。

## 4. Run / State Application Contract

状态应用层直接复用核心规范 02 的命令接口：

```text
CreateRun(task_ref, release_ref, runtime_ref, idempotency_key) -> RunRecord
AdmitRun(run_id, expected_revision) -> RunAdmissionResult + RunRecord
RegisterWait(run_id, reason, condition_refs, checkpoint, expected_revision) -> RunRecord
ResumeRun(run_id, resume_signal_ref, expected_revision) -> RunRecord
PauseRun(run_id, actor_ref, reason, expected_revision) -> RunRecord
ScheduleRetry(run_id, failure_ref, retry_policy_ref, expected_revision) -> RunRecord
CancelRun(run_id, actor_ref, reason, expected_revision) -> RunRecord
CommitRunTerminal(run_id, disposition, evidence_refs, expected_revision) -> RunRecord
GetRun(run_id, consistency_requirement) -> RunRecord
```

实现层不得再创建一套语义相同、名称不同的 Run command。

## 5. 关键内部 Port

### 5.1 `RuntimeAdapter`

V1 最小 SPI 以核心规范 04 为唯一标准：

```text
DescribeRuntime() -> RuntimeCapabilities
StartRun(RuntimeStartRequest) -> RuntimeSession
AdvanceRun(RuntimeAdvanceRequest) -> RuntimeEventStream
SuspendRun(RuntimeSuspendRequest) -> RuntimeCheckpointRef
ResumeRun(RuntimeResumeRequest) -> RuntimeSession
CancelRun(RuntimeCancelRequest) -> RuntimeCancellationObservation
InspectRun(RuntimeInspectRequest) -> RuntimeObservation
```

规则：

- 一个 Run 只能绑定一个 active Runtime Adapter；
- Adapter 不得直接调用 Model Provider 或企业写 API；
- 模型调用必须走 `ModelStepPort`；
- 上下文必须走 `ContextBuildPort`；
- 企业副作用必须走 `ToolIntentPort`；
- Handoff 必须走 `HandoffPort`；
- telemetry/audit 使用核心 `TelemetryPort` 能力；
- unsupported capability 必须显式拒绝。

`ValidateRelease`、`StreamEvents`、`Snapshot`、`Close` 等若某 Adapter 实现需要，只能作为私有/可选 convenience method，不替代上述规范 SPI，也不能成为 Conformance Suite 的另一套必需接口。

### 5.2 `ModelStepPort`

RuntimeExecutionContext 暴露的 `ModelStepPort` 负责把一次模型步骤交给模块 03；其实现最终使用核心 `ModelProviderAdapter`：

```text
DescribeModels() -> ModelCapabilities[]
Invoke(ModelInvocation) -> ModelRunResult
InvokeStream(ModelInvocation) -> ModelStreamEvent[]
CancelModelInvocation(model_invocation_id, deadline_at) -> CancellationObservation
Estimate(ModelEstimateRequest) -> ModelEstimate
```

必须满足：

- PromptContract、ContextManifest、ModelRoute、输出 Schema 在调用前冻结；
- token/cost/latency measurements 可观测；
- structured output 由 UEAF 校验；
- Runtime 不持有长期 Provider 凭据。

### 5.3 `ContextBuildPort`

规范能力为：

```text
ContextBuildPort.build(ContextBuildRequest) -> ContextManifest
```

具体语言方法名 MAY 适配，但公共接口/Schema 使用 `ContextBuildPort`，不得另建 `ContextPort` 作为第二规范名。

必须保证权限过滤先于相关性排序；返回引用和选择结果，不改变原始业务事实。

### 5.4 `ToolIntentPort`

```text
submit(ToolIntent) -> ActionRecordRef / controlled interruption
```

调用返回“动作已进入受控生命周期”，不等价于业务副作用已经成功。动作状态推进继续使用核心规范 02 的 `CreateAction/AdvanceAction/AppendActionReceipt/ReconcileAction` 语义，并由模块 05 唯一写入。

### 5.5 `ToolAdapter`

执行适配器直接复用核心规范 04：

```text
DescribeCapabilities() -> CapabilityDescriptor[]
Prepare(ToolExecutionRequest) -> PreparedAction
Execute(PreparedAction) -> ActionReceipt
QueryAction(ActionQuery) -> ActionReceipt
Compensate(CompensationRequest) -> ActionReceipt
Health(HealthRequest) -> AdapterHealth
```

`Execute` 的 timeout/断连且结果可能已发生时必须返回 unknown 观察；不得在 Adapter 内把 unknown 变成 certain failure。

### 5.6 `TelemetryPort`

V1 规范端口直接复用核心规范 04：

```text
EmitTrace(TraceRecord) -> TelemetryAck
EmitMetric(MetricPoint[]) -> TelemetryAck
EmitLog(LogRecord[]) -> TelemetryAck
EmitAudit(AuditRecord) -> AuditCommitReceipt
```

Evidence 规范中的轻量结构化 observation 由实现映射到上述 Trace/Metric/Log 能力或模块内非公共 buffer；不得再定义一个与核心 `TelemetryPort` 同名的 `emit(TelemetryEvent)` 公共接口。

Audit 的可靠性、完整性和保留独立于普通 Telemetry。

### 5.7 Genome materialization 与 Candidate Build

V1 演化链必须保留两步：

```text
MutationProposal
  -> materialize new GenomeManifest candidate
  -> Module 10 ReleaseCandidate build
```

模块 11 内部可实现：

```text
MaterializeGenome(MutationProposal, baseline_genome_ref) -> GenomeManifest
```

它不是新的 Canonical Object 或独立服务，只是 `GenomeManifest` owner 的应用操作。

随后 Candidate Build：

```text
CandidateBuildPort.build(genome_ref, mutation_ref, baseline_release_ref) -> ReleaseCandidate
```

Candidate Build 前 MUST 已完成 Mutation Validator 校验，并验证 `GenomeManifest`/Artifact refs 完整性和兼容性。禁止 `MutationProposal -> ReleaseCandidate` 跳过 Genome candidate。

### 5.8 `EvaluationPort`

```text
run(EvalConfig) -> EvalRunRef
get_results(EvalRunRef) -> EvalResult[]
```

Judge/Graders 只产生证据，不拥有 Release 权限。

### 5.9 `EvolutionStrategyPort`

```text
propose(StrategyInput) -> ProposalDraft[]
```

输入和输出遵守核心规范 09；输出允许为空。Strategy 不能签发 Eval、ReleaseDecision 或 ReleaseManifest。

## 6. 错误契约

V1 不建立新的 `ErrorEnvelope`。

### 6.1 跨进程/API 错误

直接使用核心规范 03 的 `ProblemDetail`：

```text
code
category
message_safe
retryability = never | safe | conditional | after_reconciliation
source
object_ref
field_paths
correlation_refs
cause_ref
observed_at
details_ref
```

### 6.2 Port 错误

直接使用核心规范 04：

```text
PortResult<T> = Success<T> | Rejected<PortError> | Unknown<PortError>
```

`PortError` 至少包含：

```text
code
category
retryability
certainty
message_ref
provider_error_ref
observed_at
details_schema_ref
```

API 层可以把 `PortError` 映射为 `ProblemDetail`，但不得丢失 `Unknown` / `after_reconciliation` 语义。

## 7. Idempotency

必须至少定义：

```text
Task creation -> request idempotency key
Action -> action_key
Command -> CommandEnvelope.idempotency_key
Event consumer -> EventEnvelope.event_id + aggregate sequence/version
EvolutionRun creation -> trigger_ref + policy-controlled uniqueness/cooldown
Release signing -> candidate/environment/decision tuple uniqueness
```

同一幂等键重放不能创建第二个权威对象；同键不同规范化 payload 必须产生 idempotency conflict。

## 8. Timeout / Retry

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

## 9. Event Contract

### 9.1 唯一 `EventEnvelope`

所有跨模块权威事件 MUST 直接复用核心规范 03 的完整 `EventEnvelope`。实施规范不得定义删减版 Envelope。

字段为：

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

事件名 MUST 使用：

```text
ueaf.<domain>.<past_tense_fact>
```

### 9.2 V1 公共事件目录

实施时优先直接使用核心规范 03 已注册事件，例如：

```text
ueaf.request.accepted
ueaf.request.rejected
ueaf.task.created
ueaf.task.revised
ueaf.run.created
ueaf.run.admitted
ueaf.run.phase_changed
ueaf.run.wait_registered
ueaf.run.resumed
ueaf.run.retry_scheduled
ueaf.run.paused
ueaf.run.terminal_committed

ueaf.context.manifest_created
ueaf.model.invocation_started
ueaf.model.invocation_completed
ueaf.structured_decision.validated
ueaf.handoff.requested
ueaf.handoff.accepted
ueaf.handoff.completed
ueaf.handoff.failed

ueaf.tool.intent_recorded
ueaf.policy.decision_recorded
ueaf.approval.requested
ueaf.approval.resolved
ueaf.action.reserved
ueaf.action.execution_started
ueaf.action.receipt_recorded
ueaf.action.reconciliation_scheduled
ueaf.action.terminal_committed

ueaf.evidence.pack_created
ueaf.memory.candidate_created
ueaf.memory.record_created
ueaf.memory.record_expired
ueaf.memory.record_deleted
ueaf.eval.result_recorded
ueaf.quality_gate.decision_recorded
ueaf.security_gate.decision_recorded
ueaf.operational_readiness.decision_recorded
ueaf.release.decision_recorded
ueaf.release.manifest_approved
ueaf.release.rollout_started
ueaf.release.activated
ueaf.release.rolled_back
ueaf.release.withdrawn
```

### 9.3 Evolution lifecycle facts

当前 V1 模块化单体 MAY 使用模块 11 内部事件/attempt metadata 推进 `EvolutionTrigger/EvolutionRun/MutationProposal/GenomeManifest` 生命周期；这些内部事件不是新的跨模块公共 Event Contract。

若实现需要把 Evolution lifecycle event 提升为跨进程稳定 `ueaf.*` 事件，必须先把 event_name、owner、aggregate、payload schema 加入核心事件规范/相应 ADR，再实现；实施层不得自行注册 `EvolutionTriggerCreated`、`MutationProposed` 等 PascalCase 公共事件。

## 10. 事件生产者唯一性

每类权威事件必须由 Semantic Owner 产生：

```text
Run state event -> Run State owner
Action event -> Tool Gateway / Action owner
EvalResult event -> Eval owner
ReleaseManifest event -> Release owner
Evolution authoritative object lifecycle -> Module 11 owner; cross-process event only after core registration
```

消费者不得通过发布同名事件改写上游事实。

## 11. Ordering 与 Revision

需要强顺序的同一 aggregate 使用核心 `aggregate_version + sequence`：

```text
sequence <= current -> duplicate/stale
sequence == current + 1 -> apply
sequence > current + 1 -> gap / recovery path
```

不要求全局事件总序。`occurred_at` 不用于并发仲裁。

## 12. At-least-once Consumer

V1 默认使用至少一次投递，因此所有消费者 MUST 幂等。禁止把消息队列的“已消费”当作业务事实提交的唯一依据。

权威 DB transaction 与 Event publish MUST 使用 transactional outbox、同一事务日志或可证明等价机制。消费者检测 sequence gap 时不能继续宣称 Projection 完整。

## 13. Authorization

每个 Port 必须明确 service identity 和 capability scope。尤其：

- Runtime Adapter 无生产企业工具直连权限；
- Judge 无业务写工具权限；
- Evolution Strategy 无 Release Authority；
- Candidate Builder 无 Eval root 修改权限；
- Telemetry Reader 的原始 Payload 读取受数据分类限制。

## 14. Codex 实施规则

Codex MUST：

1. 直接使用核心规范已有 Port/Envelope/错误名称，不建立同义接口；
2. 从 Schema/Port Contract 生成接口，不通过直接模块 import 绕过 Port；
3. 每个 Port 至少实现 happy path、validation error、dependency failure、timeout、idempotency 测试；
4. 副作用路径必须测试 `outcome_unknown`；
5. 不新增未在核心目录登记的跨模块 public Event；
6. 不用框架原生事件替代 UEAF 事件；
7. 不让 consumer 成为第二 State Writer；
8. 不跳过 `GenomeManifest` candidate 直接从 Mutation 构建 ReleaseCandidate。

## 15. 完成定义

本包完成意味着：

- V1 主链所有跨模块调用映射到唯一规范 Port；
- RuntimeAdapter/ContextBuildPort/TelemetryPort 与核心规范完全同名同义；
- 关键外部 API 有 request/response/error 结构；
- `ProblemDetail` 与 `PortError` 分工明确；
- 公共事件只使用核心 `EventEnvelope` 和规范 `ueaf.*` event_name；
- timeout/retry/idempotency 不再依赖实现者猜测；
- Evolution 仍保持 `Mutation -> Genome -> ReleaseCandidate` 链；
- contract tests 可自动验证 Adapter/Module 行为。
