# Agent 运行时与状态

## 1. 定位

Agent Runtime 是 UEAF 的确定性执行外壳和根状态所有者。它接收 01 通过边缘预校验的候选，先创建或关联 `TaskState` 并创建 `RunRecord(queued)`；随后只在绑定该 run_id 的 `RunAdmissionResult.outcome=admitted` 时启动执行。在预算和策略约束内，它驱动 Runtime Adapter、上下文读取、模型步骤、工具动作和工作流编排，并计算唯一的根 Run 终态。

模型、底层 Agent 框架和工作流节点都只是 Runtime 的受控能力，不能成为业务状态真相。固定运行主链为：

```text
01 RequestEnvelope + TaskEnvelope + edge_validation_ref
  -> 02 创建/恢复 TaskState、创建 RunRecord(queued)
  -> 01 RunAdmissionResult(run_id)
  -> 02 admitting -> running | waiting | terminal
  -> 04 ContextBuildRequest -> ContextManifest/Evidence/Memory
  -> 03 调用前：PromptContract + ContextManifest -> ModelInvocation
  -> Model Provider
  -> 03 调用后：ModelRunResult -> StructuredDecision
  -> 02 应用决定
       -> final_response/refusal/no_progress：判定下一步或根终态
       -> tool_intents：交给 05 ActionRecord
       -> handoff：交给 06 形成 HandoffEnvelope/受控子运行
       -> need_input：登记 user_input wait
```

LangGraph、Microsoft Agent Framework、OpenAI Agents SDK、Google ADK、CrewAI 等只能位于 `Runtime Adapter` 后方。适配器可提供图执行、暂停恢复或 SDK 事件转换，但 UEAF Runtime 始终拥有 canonical Task、Run、Turn、Checkpoint、预算和终态。

## 2. 职责与非职责

### 2.1 职责

- 校验边缘 accepted 候选和 `RunAdmissionResult` 的身份、run_id、Release、预算、有效期和完整性。
- 创建或以乐观并发方式关联 `TaskState`。
- 创建、租赁、暂停、恢复、取消和终结 `RunRecord`。
- 冻结 Agent、Prompt、Schema、ModelRoute、Policy、Tool 和 Runtime Adapter 版本。
- 驱动有界 Agent Loop；每轮形成 `TurnRecord`。
- 请求 04 构建新的 `ContextManifest`，而不是继承不可解释的旧 Prompt。
- 调用 03 完成调用前 Prompt 编译和调用后结构化结果门禁。
- 把 `StructuredDecision.tool_intents` 提交给 05，并等待带 `action_ref` 的 `ToolResult` 或 `ActionRecord` 权威事件。
- 把 `StructuredDecision.kind=handoff` 提交给 06；已发布 Workflow 的启动由确定性 Runtime 控制逻辑产生 `WorkflowStartCommand`，并消费 `WorkflowProgress` 或 `WorkflowOutcome`。
- 维护步骤、时间、Token、成本、工具、写动作、节点和并发预算账本。
- 通过事件和 Checkpoint 支持崩溃恢复、审批等待和外部条件等待。
- 执行取消、deadline、无进展检测、重试上限和终态保护。
- 只依据确定性状态、动作收据、工作流状态和完成条件计算根终态。
- 发布 Trace、Metric、Log；将身份、审批、动作和关键状态变更关联到 Audit。

### 2.2 非职责

- 不认证外部凭证，不重新解释原始 HTTP/JWT 对象。
- 不拥有 Prompt 文本、Schema、模型供应商协议或 `StructuredDecision` 解析规则，这些属于 03。
- 不拥有知识索引、`EvidencePack`、长期 `MemoryRecord` 或记忆删除状态，这些属于 04。
- 不直接调用工具或 MCP Server，不写 `ActionRecord`，这些属于 05。
- 不写 `WorkflowRun` 或 `NodeRun`，这些属于 06。
- 不让模型输出直接覆盖 `TaskState`、权限、审批、预算或业务事实。
- 不用 Provider Conversation、SDK Session 或图框架 checkpoint 代替 UEAF canonical 状态。
- 不承诺外部副作用 exactly-once；完成必须依赖 05 的 `ActionReceipt` 或等价权威记录。

## 3. 子组件

| 子组件 | 职责 | 关键对象 |
| --- | --- | --- |
| Run Coordinator | 创建、租赁、恢复、取消、终结 Run | `RunRecord` |
| Task State Manager | 维护业务目标、已确认事实、开放问题和完成条件 | `TaskState` |
| Agent Loop Controller | 推进 Context→Model→Decision→Result 循环 | `TurnRecord` |
| Version Binder | 冻结 Release 中的兼容版本 | `RuntimeBinding` |
| Runtime Adapter Manager | 选择、约束并驱动底层框架 | `RuntimeAdapterSession` |
| Event Journal | 追加状态迁移依据并进行事件去重 | `RuntimeEvent` |
| Checkpoint Manager | 生成、校验和迁移可恢复快照 | `Checkpoint` |
| Lease Manager | Worker 租约、heartbeat、fencing 和僵尸执行隔离 | `RunLease` |
| Budget Ledger | 预留、结算和释放多维预算 | `BudgetLedger` |
| Wait Coordinator | 管理工具、审批、人工、外部事件和工作流等待 | `WaitCondition` |
| Cancellation Controller | 传播取消并隔离晚到结果 | `CancellationState` |
| Terminal State Evaluator | 按完成条件与未决副作用计算根终态 | `RuntimeOutcome` |
| Recovery Manager | 版本、权限、副作用和依赖恢复检查 | `RecoveryValidationResult` |

## 4. Canonical 契约

所有对象继承 01 定义的 `ContractMeta`；至少保留 `tenant_id`、`principal_ref`、`request_id`、`task_id`、`run_id`、`trace_id`、`release_id`、producer、classification、purpose、provenance、完整性和并发字段。

### 4.1 输入：`CreateRunCommand` 与 `RuntimeStartCommand`

| 字段 | 说明 |
| --- | --- |
| `command_kind` | `create_run` 或 `start_runtime`；二者不能合并成可跳过准入的一步 |
| `request_envelope_ref` / `task_envelope_ref` / `edge_validation_ref` | `create_run` 必填，分别引用 01 的规范请求、不可变任务输入与边缘预校验证据 |
| `run_id` / `run_admission_result_ref` | `start_runtime` 必填，结果必须绑定同一 run_id 且 `outcome=admitted` |
| `execution_mode` | `new_task`、`continue_task`、`resume_run`、`retry_run` |
| `expected_task_revision` | 关联已有任务时的乐观并发 revision |
| `resume_token_ref` | 恢复时的安全令牌引用，不能只靠 checkpoint_id |
| `caller_cancel_ref` | 调用方取消通道 |
| `requested_runtime_profile` | 可为空；最终选择必须受 Release allowlist 约束 |

`RuntimeStartCommand` 是应用层命令，仅由 02 的 Run Coordinator 消费，不属于 Runtime Adapter SPI。02 校验同一 `run_id` 的当前 `RunAdmissionResult.outcome=admitted`、revision、租约、预算、Release 和 Adapter 能力后，才把它映射为适配器层 `RuntimeStartRequest`。`RuntimeStartRequest` 包含受限 `RuntimeExecutionContext`；该上下文只授予 tenant/run/release/trace、revision/fencing、deadline/取消句柄，以及 `ContextBuildPort`、`ModelStepPort`、`ToolIntentPort`、`HandoffPort`、`TelemetryPort`，不得携带原始凭据、State Store 句柄或模型长期密钥。

### 4.2 `TaskState`

`TaskState` 是根业务任务的 canonical 状态，由 02 唯一写入。实现内部 MAY 采用 DDD Aggregate，但不得改变线级契约名。

| 字段 | 说明与不变量 |
| --- | --- |
| `task_id` / `revision` | `task_id` 稳定；每次合法变更使 revision 单调增加 |
| `task_envelope_ref` | 指向不可变初始目标和来源请求 |
| `completion_criteria_state` | 每项完成条件的 `pending/satisfied/waived` 状态及证据；不得从某个 Run 的终态直接复制 |
| `goal` / `completion_criteria` | 目标变更必须有显式事件和来源 |
| `confirmed_facts` | 结构化事实及权威来源；模型摘要不能覆盖 |
| `open_questions` | 仍需用户、工具或工作流补齐的信息 |
| `pending_action_refs` | 指向 05 的 Action，不复制动作状态 |
| `workflow_refs` | 指向 06 的 WorkflowRun，不复制其节点状态 |
| `evidence_pack_refs` / `memory_usage_refs` | 指向 04 的对象和使用范围 |
| `active_run_ids` | 受并发策略约束的 Run 列表 |
| `terminal_evidence` | 达成完成条件、拒绝或失败的结构化证据 |
| `last_event_seq` | 事件水位和并发提交依据 |

### 4.3 `RunRecord`

| 字段 | 说明 |
| --- | --- |
| `run_id` / `task_id` | 一次有边界执行和所属根任务 |
| `agent_ref` | 冻结的 `AgentDefinition` 版本引用 |
| `runtime_adapter_ref` | 一个 Run 全程绑定的 Runtime Adapter 版本引用 |
| `release_id` | 本次运行冻结的 `ReleaseManifest` 标识 |
| `run_kind` | `root`、`continuation`、`recovery`、`node_execution` |
| `phase` | `RunPhase`，见 6.1；只表达生命周期阶段 |
| `completion_disposition` | 仅 `phase=terminal` 时存在，固定为 `completed/rejected/incomplete/failed/cancelled` |
| `wait_reason` / `wait_condition_refs` | 仅 `phase=waiting` 时存在，说明等待种类和恢复条件 |
| `attempt` | 当前 Run 执行尝试，重试与后续 Run 不得混同 |
| `budget_snapshot` | 各维度已分配、预留、消耗和剩余预算的规范快照 |
| `pending_action_refs` | 指向 05 的未终结动作；不复制 Action 状态 |
| `result_ref` / `error_ref` | 规范结果或结构化错误引用；不在状态中复制大正文 |
| `created_at` / `updated_at` | 可信创建时间与最近一次提交时间 |
| `runtime_binding` | Agent、Prompt、Schema、ModelRoute、Policy、Tool、Adapter 版本快照 |
| `current_turn_id` / `step_no` | 确定性循环位置 |
| `budget_ledger_ref` | 预算账本实现引用；不得替代规范 `budget_snapshot` |
| `latest_context_manifest_ref` | 最近一次实际模型上下文引用 |
| `pending_wait` | 等待类型、对象引用、恢复条件和期限 |
| `cancellation` | 请求时间、来源、传播水位和已隔离晚到结果 |
| `lease` | worker、lease_epoch、fencing_token、heartbeat、expires_at |
| `checkpoint_ref` | 最近已提交 canonical checkpoint |
| `terminal_reason_codes` / `additional_result_refs` | 仅终态存在的稳定原因、附加结果、缺口和证据引用；主结果使用 `result_ref` |
| `revision` / `sequence` | CAS revision 和聚合事件水位 |

### 4.4 `TurnRecord`

| 字段 | 说明 |
| --- | --- |
| `turn_id` / `turn_no` | Run 内单调编号 |
| `observation_refs` | TaskState、工具/工作流结果和用户事件引用 |
| `context_manifest_ref` | 本轮实际使用的 04 输出 |
| `prompt_contract_ref` / `output_schema_ref` / `model_ref` | 本轮冻结的 Prompt、Schema 与模型版本 |
| `model_invocation_ref` | 03 调用前产物 |
| `model_run_result_ref` / `structured_decision_ref` | 03 调用后产物 |
| `normalized_model_event_refs` | 流式与非流式路径归一后的模型事件引用 |
| `tool_intent_refs` | 本轮产生的候选动作引用 |
| `decision_application` | Runtime 接受、拒绝或请求修复的确定性记录 |
| `usage_delta` | 本轮时间、Token、成本和调用增量 |
| `stop_reason` / `status` | 归一停止原因及本轮终态；流式与非流式必须等价 |

流式片段可以关联 Turn，但只有 03 的最终 `StructuredDecision` 可以被 Runtime 应用。

### 4.5 `RuntimeBinding`

| 字段 | 说明 |
| --- | --- |
| `release_id` | 01 冻结的 ReleaseManifest |
| `agent_definition_ref` | Agent 标识和不可变版本 |
| `prompt_contract_ref` / `schema_ref` | 03 兼容版本 |
| `model_route_ref` | 模型路由、回退和安全配置版本 |
| `policy_snapshot_refs` | 准入、上下文、工具和编排策略版本 |
| `capability_set_ref` | 本次可发现能力上限 |
| `runtime_adapter` | adapter_id、adapter_version、capability_profile |
| `state_schema_version` | Task/Run/Event/Checkpoint Schema 版本 |
| `compatibility_hash` | 上述集合的完整性摘要 |

进行中的 Run 不跟随默认配置热更新。安全撤销可触发暂停和重新授权，但不能静默替换语义版本。

### 4.6 `RuntimeStepCommand`

| 字段 | 说明 |
| --- | --- |
| `run_ref` / `expected_state_version` | 当前 Run 和 CAS 版本 |
| `step_kind` | `build_context`、`invoke_model`、`apply_decision`、`await_action`、`await_workflow`、`finalize` |
| `input_refs` | 当前步骤需要的 canonical 对象引用 |
| `remaining_budget` / `absolute_deadline` | 不得由 Adapter 重置 |
| `fencing_token` | 阻止过期 Worker 提交 |
| `allowed_callbacks` | Adapter 只能回调的 UEAF 端口集合 |

### 4.7 `RuntimeEvent`

| 字段 | 说明 |
| --- | --- |
| `event_id` / `aggregate_id` / `sequence` | 去重、聚合和严格顺序 |
| `event_type` | 稳定事件类型，不使用自由日志文本作为状态依据 |
| `expected_version` / `new_version` | 乐观并发 |
| `payload` | 最小状态变化和对象引用 |
| `occurred_at` / `recorded_at` | 业务发生时间与系统记录时间 |
| `actor_ref` | 用户、服务、Agent、Worker 或治理主体 |
| `causation_ref` / `correlation_ref` | 前因与跨模块关联 |

同一 `event_id + aggregate_id`、相同载荷是幂等无操作；相同标识不同载荷是数据一致性错误。

### 4.8 `Checkpoint`

| 字段 | 说明 |
| --- | --- |
| `checkpoint_id` / `run_id` / `state_schema_version` | 标识及 Schema |
| `run_position` | 已提交的 Turn、step、phase 和确定性执行位置 |
| `state_refs` | TaskState、RunRecord、Turn 及必要投影的版本化引用 |
| `event_high_watermark` | 快照已包含的最后事件水位 |
| `task_state_ref` / `run_state_snapshot` | 确定性状态及引用 |
| `runtime_binding` | 完整版本冻结信息 |
| `frozen_version_refs` | Release、Agent、Prompt、Schema、ModelRoute、Policy、Tool、Adapter 版本引用 |
| `concurrency_token` | 恢复时必须校验的 revision/lease/fencing 信息 |
| `budget_snapshot` | 已预留、已消耗和剩余预算 |
| `pending_wait` | 审批、动作、工作流、人工或外部事件条件 |
| `pending_action_refs` | 只保存 05 引用及已知状态，不伪造结果 |
| `workflow_refs` | 只保存 06 引用和消费水位 |
| `provider_state_refs` | SDK/provider state 的受控外部引用 |
| `integrity_ref` | 防止快照被替换或跨租户加载 |

Checkpoint 是恢复加速器，不是唯一事件事实源，不保存万能 Prompt，也不能证明外部动作可以安全重放。

### 4.9 `StructuredDecision` 的 Runtime 消费约束

03 返回的 `StructuredDecision` 至少包含 `structured_decision_id`、`run_id`、`turn_id`、`kind`、`payload`、`schema_ref`、`validation_result`、`evidence_refs` 和 `source_model_result_ref`。跨模块 `kind` 的核心闭集固定为：

- `final_response`：候选最终输出，仍由 Runtime 检查完成条件；
- `tool_intents`：一个或多个候选 `ToolIntent`，必须进入 05；
- `handoff`：`HandoffEnvelope` 候选，必须进入 06 并重新校验委托；
- `need_input`：登记 `wait_reason=user_input`；
- `refusal`：由 Runtime 判断是否形成 rejected/incomplete；
- `no_progress`：触发预算、上下文和终态判断。

`workflow_intent`、`need_context`、`invalid` 只能作为 03 内部解析/验证候选或命名空间化 extension，不能作为跨模块 `StructuredDecision.kind`。其中 invalid 必须写入 `validation_result` 并阻止决定被签发；补充上下文由 Runtime 基于 `no_progress`、缺失证据和确定性规则重新调用 04；已发布 Workflow 只能通过 02 生成的 `WorkflowStartCommand` 启动。任何模型自述“已经执行”都不能推进确定性状态。

### 4.10 输出：`RuntimeOutcome`

`RuntimeOutcome` 是从已提交终态 `RunRecord` 形成的不可变交付投影，不是第二套状态机。`RunRecord.phase` 与 `completion_disposition` 仍是权威终态；投影不得反向修改它们。

| 字段 | 说明 |
| --- | --- |
| `task_id` / `run_id` / `completion_disposition` | 根执行终态处置 |
| `result` | 通过最终 Schema 的结果或安全用户视图 |
| `completion_check` | 每项完成条件的 `met/not_met/unknown` 及证据 |
| `action_receipt_refs` | 必要副作用的 05 收据引用 |
| `workflow_outcome_refs` | 06 编排结果引用 |
| `evidence_refs` | 04 EvidencePack 和引用集合 |
| `remaining_open_questions` | 不完整时的明确缺口 |
| `reason_codes` | 拒绝、失败、取消和预算终止原因 |
| `usage` | 总 Token、成本、时长、步骤、工具和节点用量 |
| `trace_id` / `audit_refs` | 观测与审计关联 |

## 5. 主流程

1. 校验边缘 accepted 证据、`TaskEnvelope`、有效期、tenant、principal、候选 Release 完整性和 deadline；边缘 rejected 不得进入本流程。
2. 新任务时从不可变 `TaskEnvelope` 创建 `TaskState`；续接时以 `expected_task_revision` CAS 加载。
3. 创建 `RunRecord(phase=queued)`，冻结候选 `RuntimeBinding`、根预算和取消通道；取得 admission lease 后进入 `admitting`。
4. 调用 01 Admission Controller 获取绑定该 run_id 的 `RunAdmissionResult`：admitted 进入 running；deferred 登记等待；rejected 原子提交 terminal/rejected。只有 admitted 才继续以下执行步骤。
5. Run Coordinator 消费应用层 `RuntimeStartCommand`，复核 admitted 结果、当前 revision、租约、预算和 Release；再根据风险、任务与能力选择一个 Runtime Adapter。能力不匹配时拒绝启动，一个 Run 全程只绑定一个 Adapter 版本。
6. 02 将命令映射为 `RuntimeStartRequest`，在其中构造最小 `RuntimeExecutionContext` 和五个受控端口句柄，再调用 `StartRun(RuntimeStartRequest) -> RuntimeSession`；底层框架不得直接读取 UEAF 存储、模型凭据或企业工具。
7. Adapter 需要上下文时，经回调读取最新 TaskState、待决 Action/Workflow 引用和 Conversation 投影，并由 04 生成权限过滤后的 `ContextManifest`。
8. Adapter 需要模型步骤时，经 `ModelStepPort` 请求 03；03 解析 `PromptContract`、生成 `ModelInvocation`、调用 Model Provider，并在调用后形成 `StructuredDecision`。
9. Adapter 将框架内部事件归一为 UEAF `RuntimeEvent`；模型候选、ToolIntent、Handoff 候选和 CompletionCandidate 均先返回 Run Coordinator。
10. Run Coordinator 验证事件与当前 Turn、Context、Contract、预算、revision 和 fencing token 一致，只有通过验证的候选可被应用。
11. 若 `kind=tool_intents`，逐项向 05 提交并将 Run 置为 `phase=waiting`，以 `wait_reason=tool_result/approval/reconciliation` 区分条件；只消费权威动作结果。
12. 若 `kind=handoff`，向 06 提交 `HandoffEnvelope` 候选；已发布 Workflow 由确定性 `WorkflowStartCommand` 创建/推进，节点需要 Agent 执行时由 06 发 `NodeExecutionRequest` 给 02。
13. 若需要用户或外部事件，持久化 `WaitCondition` 和 Checkpoint，释放 Worker。
14. 将已确认工具/工作流结果作为新观察，重新从 04 构建上下文，不直接拼接不可信原文。
15. 每轮结算预算、检测无进展和停止条件，提交 Turn 与 Checkpoint。
16. Terminal State Evaluator 检查完成条件、必要收据、关键 Workflow 节点、开放问题和预算。
17. 以 CAS 写入根终态和 `RuntimeOutcome`，释放租约与剩余预算，发布观测和审计引用。

## 6. 状态与数据所有权

### 6.1 Run 生命周期与终态

```text
queued -> admitting -> running
admitting -> waiting
running -> waiting -> running
running -> retrying -> running
running | waiting | retrying -> paused
paused -> admitting | running | terminal
queued | admitting | running | waiting | retrying | paused -> terminal
```

`RunPhase` 只允许 `queued/admitting/running/waiting/retrying/paused/terminal`。等待用户、工具、审批、依赖、容量或对账通过独立 `WaitReason` 表达，不扩展为 `waiting_action` 等新 Phase。取消是命令和意图，在确认不再启动新动作并妥善记录在途动作后提交 `phase=terminal, completion_disposition=cancelled`。

`CompletionDisposition` 只允许 `completed/rejected/incomplete/failed/cancelled`，且仅在 `phase=terminal` 时非空。终态不可逆。`completed` 必须满足全部关键完成条件，且必要副作用都有确定成功收据；`unknown` 动作、关键 Workflow 未终结、流式未完成或模型自述完成都不足以成功。

### 6.2 根终态语义

| 终态 | 判定 |
| --- | --- |
| `completed` | 本 Run 的完成契约全部满足，必要动作与关键节点已确认；不自动关闭整个 Task |
| `rejected` | 策略、权限、安全边界或审批明确拒绝 |
| `incomplete` | 安全结束但信息、证据、预算或外部条件不足 |
| `failed` | 系统/依赖错误且不能安全恢复 |
| `cancelled` | 取消已阻止新工作，并记录在途动作核实状态 |

### 6.3 唯一所有权矩阵

| 对象 | 唯一写所有者 | Runtime 的权限 |
| --- | --- | --- |
| `TaskState`、根 `RunRecord`、`TurnRecord` | 02 | 完整写权限 |
| Runtime `Checkpoint`、`BudgetLedger`、lease | 02 | 完整写权限 |
| Provider Conversation/SDK Session | Provider/Runtime Adapter | 只登记引用；不能作为业务真相 |
| `PromptContract`、`ModelInvocation`、`ModelRunResult`、`StructuredDecision` | 03 | 请求、引用和消费，不原地修改 |
| `ContextManifest`、`EvidencePack`、`MemoryRecord` | 04 | 请求和引用；不得把 TaskState 写入 Memory |
| `ActionRecord`、canonical `ActionReceipt` | 05 Action Domain | 提交意图、等待和消费结果；业务系统仅提供下游收据/权威观察 |
| `WorkflowRun`、`NodeRun` | 06 | 创建意图、等待和消费；只有 02 判根终态 |
| 订单、余额、合同等业务事实 | 权威业务系统 | 保存 `BusinessFactRef`，不复制为模型事实 |

### 6.4 并发、事件与恢复

- 所有 Task/Run 变更使用 `expected_version`；冲突后重新加载并重新判定，不能 last-write-wins。
- Worker 提交必须携带当前 fencing token；过期租约产生的晚到结果被隔离。
- 事件是迁移依据，Checkpoint 是快照；恢复先加载快照，再重放高水位之后事件。
- 恢复必须验证 tenant/principal、Release 可用性、状态 Schema、策略变化、deadline、预算和待决副作用。
- 05 的 `unknown` Action 恢复时先对账，不能重新执行模型步骤来生成新 action_key。
- 06 的 Node Attempt 晚到结果由 06 隔离；02 只消费胜出的 NodeRun 终态。
- 原版本不可用时执行显式迁移；迁移失败时提交 `phase=terminal` 及 `failed` 或 `incomplete` disposition，不偷偷切换版本。

## 7. 权限与多租户

- 每次状态读写同时约束 `tenant_id + aggregate_id`；裸 ID 查询不可进入存储端口。
- Runtime 从 `PrincipalContext` 读取身份，但在恢复、高风险动作、上下文读取和跨 Agent handoff 时要求相应模块重新验证。
- Task、Run、Checkpoint、Conversation 和 Provider state 引用不得跨租户复用。
- Adapter 收到的是最小 `RuntimeExecutionContext`，不含原始用户凭证、跨租户密钥或完整企业配置。
- Adapter callback 必须携带 tenant、run、release、fencing token 和 purpose；回调白名单之外的存储、工具或网络访问被阻断。
- 租户配额同时限制活跃 Run、排队 Run、模型并发、工具写动作和 Workflow 节点，不允许只在 API 入口限流。
- Trace 与日志中的用户输入、工具正文和模型内容按 classification 脱敏；Audit 与调试日志分库、分权和分保留期。
- 恢复令牌绑定 tenant、principal、run、checkpoint、目的和有效期；仅有 `checkpoint_id` 不能恢复。

## 8. 故障与降级

| 故障 | Runtime 处理 | 禁止行为 |
| --- | --- | --- |
| State Store 写冲突 | 重新加载、合并合法事件或返回 conflict | 覆盖新状态 |
| Checkpoint 写失败 | 停止跨边界推进；可在同一原子提交内回滚 | 在内存继续执行长任务 |
| lease 过期/Worker 崩溃 | 新 Worker 取得更高 epoch，旧 Worker 结果隔离 | 两个 Worker 同时提交 |
| Runtime Adapter 不可用 | 恢复到兼容且已评测 Adapter；否则暂停/失败 | 临时导入另一个 SDK 改语义 |
| 04 上下文不可用 | 必须证据任务不运行；记忆可按策略关闭个性化 | 用其他主体缓存补齐 |
| 03 模型暂态错误 | 在共享预算内按安全路由重试/回退 | 重置 deadline 或使用未评测模型 |
| 03 `validation_result` 未通过 | 有限修复重试；耗尽后由 Runtime 判定 `incomplete/failed` | 把未校验 JSON 应用到状态 |
| 05 Action `unknown` | `phase=waiting, wait_reason=reconciliation`，触发对账 | 生成新 action_key 重试 |
| 06 optional 节点失败 | 按 WorkflowOutcome 标注缺口后继续 | 隐藏部分失败 |
| 06 critical 节点失败 | 阻断 completed | 仅凭其他节点文本成功 |
| Budget 耗尽 | `incomplete` 或预定义降级，保留收束预算 | 跳过审批/验证完成 |
| 取消到达 | 停止新步骤，传播取消，核实在途副作用 | 将取消直接标成所有动作未发生 |
| Telemetry 不可用 | 本地缓冲；按风险暂停敏感操作 | 完全不可追踪继续 R3 |

## 9. 观测指标

### 9.1 指标

- `runtime_runs_total{agent,run_kind,completion_disposition,risk_class}`。
- `runtime_run_duration_seconds`、`queue_wait_seconds`、`time_to_first_turn_seconds`。
- `runtime_active_runs`、`paused_runs`、`stale_leases`、`recovery_attempts_total`。
- `runtime_steps_total`、`turns_per_run`、`no_progress_terminations_total`。
- `checkpoint_write_duration_seconds`、`checkpoint_failures_total`、`event_replay_count`。
- `state_conflicts_total`、`fenced_late_results_total`、`duplicate_events_total`。
- `budget_consumption_ratio{dimension}`、`budget_exhausted_total{dimension}`、预算超支率，目标为零。
- `model_decision_invalid_total`、`context_rebuild_total`。
- `runtime_wait_duration_seconds{wait_reason}`。
- `runs_blocked_by_unknown_action_total`、`cancel_with_inflight_action_total`。
- `runtime_adapter_errors_total{adapter,error_class}`，不得以 run_id 作指标标签。

### 9.2 Trace 与事件

根 Run span 下至少包含 context build、prompt compile、model invoke、decision validate、action wait、workflow wait、checkpoint、recovery 和 finalize。Trace 通过 `task_id/run_id/turn_id/action_key/workflow_run_id/release_id` 关联，但不复制受限正文。状态迁移、租约接管、恢复迁移、根终态和取消形成稳定结构化事件。

## 10. 可替换端口

| 端口 | 稳定语义 | 可替换实现 |
| --- | --- | --- |
| `RuntimeAdapterPort` | 有界 step、暂停/恢复、事件归一、callback 限制 | LangGraph、MAF、OpenAI SDK、ADK、CrewAI、自研循环 |
| `TaskStatePort` | CAS、事件追加、Task/Run 快照和终态保护 | 关系库、事件存储、工作流状态后端 |
| `CheckpointPort` | 原子保存、读取、完整性、迁移 | 数据库、对象存储、工作流引擎 |
| `LeasePort` | lease、heartbeat、epoch、fencing | 数据库、Redis、协调服务 |
| `ContextBuildPort` | `ContextBuildRequest -> ContextManifest` | 04 的本地或远程服务 |
| `ModelStepPort` | 调用前 `ModelInvocation` 与调用后 `StructuredDecision` | 03 的模型网关 |
| `ToolIntentPort` | `ToolIntent -> ToolResult`，并提供 ActionRecord 等待和对账引用 | 05 Tool/Action Gateway |
| `HandoffPort` | 提交 `HandoffEnvelope` 候选并消费交接进度/结果 | 06 Orchestrator |
| `ConversationPort` | 消息顺序、保留、删除和并发 | 自管历史、Provider conversation adapter |
| `BudgetPort` | 原子预留、结算、释放和硬上限 | 本地账本、集中配额服务 |
| `TelemetryPort` | Run/Turn/step 语义和关联 | OpenTelemetry 或供应商平台 |

`RuntimeAdapterPort` 的适配器不得直接写 UEAF State Store、调用 05 之外的工具、绕过 03 构造模型请求，或把框架 checkpoint 当 canonical Checkpoint。框架原生能力不支持某个不变量时，适配器必须显式声明 unsupported，不能静默降级。

## 11. 配置项

| 配置键 | 含义 | 约束 |
| --- | --- | --- |
| `runtime.max_steps` / `max_turns` | 循环硬上限 | 不能由模型修改 |
| `runtime.default_timeout_ms` | Run 默认时限 | 与 01 absolute deadline 取更严格值 |
| `runtime.no_progress_window` | 重复状态/动作检测窗口 | 命中后停止或人工介入 |
| `runtime.concurrent_runs_per_task` | 同任务并发策略 | 默认单写，多读需显式定义 |
| `runtime.adapter_allowlist` | Release 可用 Adapter 与能力 | 生产只允许评测通过版本 |
| `runtime.lease_ttl_ms` / `heartbeat_ms` | 租约与心跳 | heartbeat 必须显著短于 TTL |
| `checkpoint.policy` | 每 Turn、等待前、动作前后、时间间隔 | 高风险边界必须提交成功 |
| `checkpoint.retention` | 可恢复窗口 | 与数据分类和任务生命周期一致 |
| `state.schema_version` / `migration_policy` | 状态版本和迁移 | 长运行恢复不得自动猜迁移 |
| `retry.model` / `retry.state` | 可重试错误、退避和次数 | 所有尝试共享根预算 |
| `cancellation.poll_interval_ms` | 长步骤取消检查 | 不代表外部动作可强制撤销 |
| `budget.reserve_finalize_ratio` | 收束保留预算 | 不得被子 Agent 借走 |
| `stream.preview_enabled` | 是否向调用方展示模型增量 | 增量不可触发业务动作 |
| `recovery.reauthorize_risk_level` | 恢复时重新授权阈值 | R2/R3 默认重新验证 |
| `telemetry.fail_closed_risk_level` | 遥测故障策略 | R3 至少保留本地最小审计 |

## 12. 验收标准

- `RuntimeStartCommand` 加绑定既有 run_id 的 admitted `RunAdmissionResult` 是唯一应用层执行启动入口；02 必须把它映射为 `RuntimeStartRequest` 后才可调用 `StartRun(...)`，原始传输、应用命令和底层 SDK 对象均不得冒充 Adapter 请求。
- `TaskState`、根 `RunRecord`、`TurnRecord`、事件和 Checkpoint 均有唯一写所有者和 CAS 版本。
- 每次模型调用可追溯到 Agent、Prompt、Schema、ModelRoute、ContextManifest、Adapter 和 Release 版本。
- 调用前一定经过 03 生成 `ModelInvocation`，调用后一定经过 03 生成 `StructuredDecision`；流式半成品不能被应用。
- 04、05、06 分别保持 Context/Evidence/Memory、Action、Workflow/Node 的唯一所有权。
- 任一底层 Agent 框架只能通过 `RuntimeAdapterPort` 使用，且不能绕过 03/04/05/06 或直接写 canonical 状态。
- Worker 崩溃、租约过期、重复事件和晚到结果不会造成双重状态提交。
- 在工具响应丢失场景，Run 进入等待对账，绝不通过新 action_key 盲重试。
- Checkpoint 恢复会重新验证租户、主体、版本、策略、预算、deadline 和未决副作用。
- 所有循环在步骤、时间、Token、成本、工具、节点和风险预算内终止，预算超支率为零。
- `completed` 只有在完成条件、必要 ActionReceipt 和关键 Workflow 节点全部确认后产生。
- `rejected`、`incomplete`、`failed`、`cancelled` 不被包装为成功；每种终态有稳定原因、指标和 Trace。
