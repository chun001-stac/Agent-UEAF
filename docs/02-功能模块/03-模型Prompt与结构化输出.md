# 模型、Prompt 与结构化输出

## 1. 定位

本模块是 UEAF 的模型语义边界，负责一次模型调用的调用前编译和调用后门禁：

```text
02 Runtime / Runtime Adapter 受控回调
  -> PromptCompileRequest
  -> 03 解析已冻结 PromptContract
  -> ModelInvocation
  -> Model Provider
  -> ModelRunResult
  -> 03 Schema、证据、语义和拒绝门禁
  -> StructuredDecision
  -> 02 Runtime
```

03 只把概率性的模型候选转换为可被 Runtime 判断的结构化决定。它不执行决定，也不拥有根 Task/Run、Context、Evidence、Memory、Action 或 Workflow 状态。

底层 Agent 框架不得以其私有对象直接调用本模块。LangGraph、Microsoft Agent Framework、OpenAI Agents SDK、Google ADK、CrewAI 等由 02 通过 `Runtime Adapter` 使用；Adapter 只能经 UEAF `ModelStepPort` 请求模型步骤。03 的 Provider Adapter 仅适配模型 API 和流事件，不能承担 Agent 编排、工具调用或业务状态持久化。

## 2. 职责与非职责

### 2.1 职责

- 管理不可变、可发布和可回滚的 `PromptContract`。
- 将任务语义、字段字典、Prompt、输出 Schema、证据规则、拒绝规则和消费者兼容声明绑定为原子 `ContractBundle`。
- 校验 02 提交的 Agent、Release、ContextManifest、能力描述和预算引用。
- 按指令层级和信任分区编译 `ModelInvocation`，隔离用户、RAG、Memory 和工具结果中的不可信指令。
- 依据能力、风险、数据区域、成本和 Release 选择 `ModelRouteSnapshot`。
- 通过 `ModelProviderPort` 调用模型，并将供应商流式/非流式响应归一为 `ModelStreamEvent` 和 `ModelRunResult`。
- 确保流式预览与最终非流式语义一致；半成品永不成为业务结果。
- 解析结构候选，执行 Schema、类型、枚举、范围、跨字段、证据和拒绝语义校验。
- 对允许的字段进行可追踪规范化，不改变业务含义。
- 仅在验证通过后形成 `StructuredDecision`，其 `kind` 严格使用 `final_response/tool_intents/handoff/need_input/refusal/no_progress` 核心闭集。
- 记录模型用量、配置快照、解析结果、验证报告和安全信号。

### 2.2 非职责

- 不认证用户，不从 Prompt 或模型响应提取真实权限。
- 不拥有或修改 `TaskState`、`RunRecord`、`TurnRecord`；只引用其标识。
- 不构建 `ContextManifest`，不检索 RAG，不读写长期 Memory；这些属于 04。
- 不授权或执行工具，不创建 `ActionRecord`；`ToolIntent` 只是候选，由 05 重新校验和授权。
- 不创建 `WorkflowRun`/`NodeRun`，不自行 handoff；编排候选由 06 处理。
- 不把结构化输出等同业务事实、审批结论或动作已完成。
- 不让 MCP Prompt、用户文本、文档、历史模型输出或工具结果改变 `PromptContract`。
- 不把 Provider response/conversation ID 当作 UEAF Run、Task 或 Memory。

## 3. 子组件

| 子组件 | 职责 | 输出 |
| --- | --- | --- |
| Prompt Registry | PromptContract 的版本、状态、完整性和回滚 | `PromptContract` |
| Contract Bundle Resolver | 解析 Task/Prompt/Schema/Evidence/Consumer 兼容集合 | `ContractBundle` |
| Instruction Composer | 按优先级与信任域编译消息/输入 | `CompiledPrompt` |
| Context Manifest Verifier | 检查上下文来源、权限证明、预算和完整性 | `ContextVerification` |
| Capability Presenter | 将本轮候选能力转换为最小模型可见描述 | `CapabilityProjection` |
| Model Router | 按能力、区域、风险、成本和健康选择已评测路由 | `ModelRouteSnapshot` |
| Model Provider Gateway | 供应商协议、认证、超时、错误和用量适配 | `ModelRunResult` |
| Streaming Reducer | 校验事件顺序并聚合最终候选 | `StreamAggregate` |
| Structure Parser | 解析 JSON/typed output/tool candidate 等结构 | `ParsedCandidate` |
| Schema Validator | 结构、类型、枚举、格式和兼容校验 | `ValidationIssue[]` |
| Semantic Validator | 范围、条件、互斥、跨字段和领域断言 | `SemanticReport` |
| Evidence Guard | 引用、覆盖、来源、版本和 EvidencePack 成员校验 | `EvidenceValidation` |
| Decision Builder | 规范化结果并生成 `StructuredDecision` | `StructuredDecision` |

## 4. Canonical 契约

所有对象继承 `ContractMeta`，并至少保留 tenant、principal、request/task/run/turn、trace、release、producer、classification、purpose、provenance 和 integrity 关联。

### 4.1 `PromptContract`

| 字段 | 说明与不变量 |
| --- | --- |
| `prompt_contract_id` / `version` | 不可变语义版本；已发布版本不原地改写 |
| `owner` / `business_purpose` | 业务与技术所有者、允许用途 |
| `agent_compatibility` | 允许的 AgentDefinition 版本范围 |
| `instruction_layers` | 组织安全、业务、任务、行为和表达层；低层不能放宽高层 |
| `variable_spec` | 名称、类型、来源、必填、分类、最大长度和转义规则 |
| `context_partition_spec` | system/task/state/evidence/memory/history/tool-result 分区与预算 |
| `input_schema_ref` / `output_schema_ref` | 输入和结构化输出 Schema |
| `semantic_rules` | 范围、条件、互斥、跨字段和不可变规则 |
| `evidence_policy` | 哪些 claim 必须引用、允许来源、时效和缺证据处理 |
| `refusal_policy` | 拒绝类别、说明边界和合法替代路径 |
| `tool_intent_schema` / `handoff_schema` | 候选动作与 HandoffEnvelope 的结构契约 |
| `examples_ref` | 与同一 Schema/语义版本兼容的示例集合 |
| `consumer_compatibility` | 消费者接受的主版本、枚举和扩展策略 |
| `security_profile` | 注入隔离、敏感数据、输出过滤和模型区域要求 |
| `status` | `draft`、`reviewed`、`approved`、`released`、`deprecated`、`revoked` |
| `integrity_ref` | Bundle 中 Prompt 内容和规则的完整性证据 |

### 4.2 `ContractBundle`

`ContractBundle` 是一次模型语义调用的原子版本单元，至少绑定：

- `TaskSpec`：目标、允许输出和完成条件投影；
- `DataDictionary`：字段定义、单位、缺失语义、来源和敏感级别；
- `PromptContract`；
- `SchemaSpec`：结构、必填、枚举、扩展区和兼容规则；
- `SemanticRuleSet`；
- `EvidencePolicy`；
- `RefusalPolicy`；
- `NormalizerSet`；
- 消费者兼容声明和评测基线。

一次 Run 只能冻结一个兼容 Bundle。单独升级 Prompt 而继续使用含义不兼容的旧 Schema 或证据规则属于非法组合。

### 4.3 输入：`PromptCompileRequest`

| 字段 | 说明 |
| --- | --- |
| `runtime_binding_ref` | 02 冻结的 Release、Agent、Contract 和 ModelRoute 上限 |
| `task_projection` | 当前目标、完成条件、开放问题和风险的最小投影 |
| `run_ref` / `turn_ref` | 当前 Run/Turn 及期望版本 |
| `principal_ref` | 可信主体引用，不包含原始凭证 |
| `context_manifest_ref` | 指向 04 生成的完整 `ContextManifest`；03 按引用读取并校验 |
| `observation_refs` | 已确认工具/工作流/用户事件引用 |
| `candidate_capability_refs` | 当前可向模型展示的能力候选；不代表可执行 |
| `budget` | 本轮输入/输出 Token、时间和费用上限 |
| `output_consumer_ref` | 消费者接受的 Schema 范围 |
| `delivery_mode` | stream 或 non-stream；只影响传输，不改变最终语义 |

03 必须拒绝 tenant、purpose、Release 或 integrity 不匹配的 ContextManifest 和能力描述。

### 4.4 `ModelInvocation`

| 字段 | 说明 |
| --- | --- |
| `model_invocation_id` | 一次模型调用标识，不等于 turn_id |
| `run_id` / `turn_id` | 与当前 Runtime Turn 严格绑定 |
| `model_route_ref` | 冻结的 `ModelRoute` 版本引用 |
| `prompt_contract_ref` | 冻结的 `PromptContract` 版本引用 |
| `rendered_prompt_ref` | 受控 Prompt 工件引用；跨模块事件不复制全文 |
| `context_manifest_ref` | 必填，指向本次调用使用的不可变 `ContextManifest` |
| `output_schema_ref` | 结构化输出时必填 |
| `tool_capability_refs` | 本次模型可见的候选能力引用，不表示可执行 |
| `deadline_at` | 继承 Runtime 的绝对 deadline |
| `budget_slice` | 本次调用的 Token、费用和时间上限 |
| `attempt` | 模型尝试序号；重试必须形成新调用/尝试记录 |
| `contract_bundle_ref` | 冻结 Bundle 和完整性 |
| `model_route_snapshot` | provider、model、能力、参数、区域、回退链和版本 |
| `compiled_instructions` | 可信指令分区及内容哈希 |
| `context_blocks[]` | 每块的 `source_ref`、kind、trust、purpose、classification、token_estimate |
| `capability_projection` | 最小候选工具/Agent 描述；不含服务端身份或审批控制 |
| `response_format` | 输出 Schema、strictness 和 refusal 通道 |
| `sampling_config` | temperature、top_p、seed 等已批准参数 |
| `streaming_policy` | 事件类型、缓冲上限、预览和取消语义 |
| `provider_state_ref` | 可选的会话连续性引用，须同租户同用途且可删除 |
| `data_handling` | 区域、保留、训练使用限制和敏感数据策略 |

`ModelInvocation` 不包含业务系统凭证、PDP 内部策略、审批密钥、其他租户数据或 05 的执行凭据。

### 4.5 `ModelStreamEvent`

| 字段 | 说明 |
| --- | --- |
| `model_invocation_id` | 所属模型调用 |
| `stream_sequence` | 对单次调用连续递增的序号 |
| `kind` | 核心值仅 `output_delta/tool_call_delta/usage/final/error` |
| `payload_ref` 或受限 `payload` | text、structured、usage、finish_reason 或 error 的受控载荷 |
| `observed_at` | UEAF Adapter 观察该事件的可信时间 |
| `provider_event_ref` | 供应商事件的受控引用 |
| `integrity_state` | 是否连续、是否缺片和聚合水位 |
| `is_preview` | 对 delta 始终为真；`final` 也只证明模型传输终态，不是 Run 结果 |

重复事件按 provider event id/sequence 去重；只允许一个 `final`。缺序、终止前断流或解析不完整必须产生本地 `error` 事件，不能伪造 `final`。

### 4.6 `ModelRunResult`

| 字段 | 说明 |
| --- | --- |
| `model_invocation_id` | 对应调用标识 |
| `status` | 仅 `succeeded/refused/failed/unknown` |
| `output_ref` | 完整候选的受控引用；无确定输出时为空 |
| `finish_reason` | stable reason：stop、length、content_filter、tool_candidate、cancelled、provider_error 等 |
| `usage` | input/output/cached/reasoning token、费用和延迟 |
| `provider_request_ref` | 供应商请求/响应关联引用，不替代 UEAF ID |
| `model_identity` | 实际 provider、model 与版本身份 |
| `latency_ms` | 调用端到端时延 |
| `error` | 稳定类别、retryability、certainty 和受限内部引用 |
| `integrity_ref` | 结果、用量与调用绑定的完整性证明 |
| `normalized_candidate_ref` | 可选供应商无关候选引用；不得替代 `output_ref` |
| `provider_state_ref` | response/conversation 引用，不充当 UEAF 状态 |
| `stream_integrity` | 事件完整性、断流和最终聚合结果 |

`succeeded` 只表示获得确定的模型终态和候选，不表示 Schema、语义、证据、授权或业务完成。供应商响应丢失且可能已计费时必须为 `unknown`；长度截断由 `finish_reason=length` 表达，不能新造 `incomplete` status。

### 4.7 `ValidationReport`

| 字段 | 说明 |
| --- | --- |
| `schema_result` | pass/fail、Schema 版本和字段问题 |
| `semantic_result` | 规则 ID、severity、字段路径和稳定原因 |
| `evidence_result` | 引用是否属于当前 EvidencePack、有效、可访问并覆盖 claim |
| `refusal_result` | refusal 是否符合边界和合法替代要求 |
| `normalization_log` | 原值引用、规范化规则和新值；禁止静默改义 |
| `security_signals` | 注入、外泄、越权字段、隐藏指令或可疑编码 |
| `repair_attempts` | 有限修复次数、原因、预算和使用的相同 Bundle |

### 4.8 输出：`StructuredDecision`

| 字段 | 说明 |
| --- | --- |
| `structured_decision_id` | 通过验证后生成的决定标识 |
| `run_id` / `turn_id` | 与当前 Runtime Turn 严格关联 |
| `kind` | 核心闭集：`final_response/tool_intents/handoff/need_input/refusal/no_progress` |
| `payload` | 与 kind 对应且通过 Schema 的候选；工具/交接仍未获授权 |
| `schema_ref` | payload Schema 版本和消费者兼容结果 |
| `validation_result` | Schema、语义、证据、拒绝和安全校验的确定结论与报告引用 |
| `evidence_refs` | 本轮获授权 Evidence 中实际支持 payload 的引用 |
| `source_model_result_ref` | 产生候选的 `ModelRunResult` 引用 |
| `confidence` | 可选校准信号，不能替代确定性验证 |
| `context_manifest_ref` / `prompt_contract_ref` / `contract_bundle_ref` | 可选便利因果引用；不得替代规范必需字段 |

只有 `validation_result=passed` 的决定可以由 02 应用。非法结构、证据不足或无法安全容纳上下文时，03 返回 `ValidationReport/ProblemDetail` 或在语义成立时签发 `kind=no_progress`；不得签发 `kind=invalid/incomplete/need_context/workflow_intent`。模型编排候选只能在模块内部验证后映射为核心 `handoff`，或由 02 根据已发布 Workflow 产生独立 `WorkflowStartCommand`。

## 5. 主流程

### 5.1 调用前

1. 接收 02 的 `PromptCompileRequest`，验证 tenant、run/turn、Release、deadline 和完整性。
2. 解析冻结的 `ContractBundle`，确认 Agent、消费者和 Schema 兼容。
3. 验证 04 `ContextManifest` 中每个块的来源、用途、信任、权限证明、有效期和 Token 预算。
4. 按优先级固定组织安全、业务、任务、字段语义、输出和拒绝规则。
5. 将用户文本、Evidence、Memory、历史模型输出和工具结果放入不可信数据分区；其中的指令文本不得进入控制层。
6. 从 05/06 的能力描述引用形成最小 `CapabilityProjection`，隐藏身份、内部参数和不可用工具。
7. Model Router 从 Release 允许集合中选择满足能力、区域、风险和预算的路由，冻结快照。
8. 计算输入 Token；先保护安全规则、目标、TaskState 和必要证据，无法安全容纳则拒绝本次调用并返回结构化预算问题，由 02 判断 `no_progress` 或重建上下文；不静默截断关键否定或条件。
9. 生成不可变 `ModelInvocation` 并记录内容哈希。

### 5.2 模型调用与流式归一

1. Provider Gateway 以最小工作负载凭据调用模型。
2. 所有尝试继承同一绝对 deadline 和重试预算。
3. Streaming Reducer 校验事件类型、顺序、重复、终止和 usage。
4. 流式 delta 仅作为 `is_preview=true` 交付；任何下游不得据此写状态或执行工具。
5. 完整结束后生成稳定四态 `ModelRunResult`；断流、长度截断或供应商拒绝被显式记录。

### 5.3 调用后

1. 按 ContractBundle 解析完整候选；不从未完成 delta 拼接业务对象。
2. 先分类 `succeeded/refused/failed/unknown`；只有具有确定候选的结果才进入 Schema 校验。
3. 执行字段类型、枚举、格式、必填、额外字段和消费者兼容校验。
4. 执行范围、条件、互斥、跨字段和领域只读断言。
5. 校验每个必须有证据的 claim，其引用只能来自本轮 `EvidencePack`。
6. 执行允许的日期、单位、词表等规范化，并保存规则日志。
7. 在预算内执行有限修复；修复仍使用同一 Bundle，不能通过改 Schema 让错误输出通过。
8. 仅在验证通过后生成核心 `StructuredDecision` 返回 02；03 不执行 tool、handoff 或 Workflow。

## 6. 状态与数据所有权

### 6.1 生命周期

```text
PromptContract: draft -> reviewed -> approved -> released -> deprecated -> revoked
ModelInvocation: compiled -> submitted -> streaming -> terminal
ModelRunResult.status: succeeded | refused | failed | unknown
StructuredDecision candidate: parsing -> validating -> signed | rejected
```

已发布 ContractBundle 不原地修改；修订产生新版本。模型调用失败不改变 PromptContract 状态。

### 6.2 唯一所有权

| 对象 | 唯一写所有者 | 其他模块行为 |
| --- | --- | --- |
| `PromptContract` / `ContractBundle` | Prompt Registry/Release Control | 02 按 Release 只读绑定 |
| `ModelRouteSnapshot` | 03 Model Router | 02 记录引用，不能中途改路由 |
| `ModelInvocation` / `ModelRunResult` | 03 | Provider Adapter 只能提交供应商事件 |
| `StructuredDecision` / `ValidationReport` | 03 | 02 应用或拒绝，不能改字段后冒充原决定 |
| `ContextManifest` / `EvidencePack` / Memory | 04 | 03 只读验证和引用 |
| 根 Task/Run/Turn | 02 | 03 仅关联，不能推进状态 |
| `ActionRecord` | 05 | 03 只产生 `ToolIntent` 候选 |
| `WorkflowRun` / `NodeRun` | 06 | 03 只产生编排候选 |

### 6.3 Provider state 边界

Provider response/conversation/compaction 只用于模型连续性，必须登记 owner、tenant、purpose、region、retention 和删除能力。它不等于 Conversation History、TaskState、Checkpoint 或长期 Memory；恢复时若不满足同主体同用途和版本要求，必须放弃并从 UEAF 状态重建调用。

## 7. 权限与多租户

- Prompt、Schema、示例和模型路由按租户/业务域授权；共享模板也必须通过显式发布范围。
- Contract 缓存键包含 tenant、contract version、release_id 和 integrity；不得按名称跨租户复用可变内容。
- `ContextManifest` 中 tenant、principal、purpose 或 Evidence 权限摘要不一致时失败关闭。
- 用户、RAG、Memory、附件、工具结果和 MCP Prompt 均是不可信数据，不能改变系统指令、Schema、能力范围或输出门禁。
- 发送给模型的数据受区域、供应商、保留、训练使用和敏感分类策略约束；路由不满足时不得为了可用性跨区。
- 模型不可见原始令牌、服务凭据、PDP 规则正文、审批密钥和内部工具执行参数。
- 日志默认不保存完整 Prompt、用户文本、Evidence 或模型 reasoning；需要调查时使用受控内容引用和独立授权。
- 同一 ContractBundle 的租户覆盖配置必须形成新完整性摘要，不能通过运行时字符串拼接绕过发布门禁。

## 8. 故障与降级

| 故障 | 默认处理 | 禁止行为 |
| --- | --- | --- |
| Prompt/Schema 版本缺失 | `version_incompatible`，停止调用 | 使用 latest 猜版本 |
| Contract integrity 不匹配 | 安全失败并告警 | 继续使用缓存内容 |
| ContextManifest 过期或 ACL 不匹配 | 返回结构化 `ProblemDetail`，由 02 请求 04 重建 | 忽略权限证明 |
| Token 超预算 | 按分区策略裁剪/压缩；关键内容放不下则不调用 | 尾部字符串截断 |
| 首选模型容量不足 | 在 Release 的已评测回退链内切换 | 使用任意未评测模型 |
| Provider 暂态错误 | 共享预算内有限退避重试 | 每次重试重置 deadline |
| 流式断开/缺序且无可信 final | `ModelRunResult.status=unknown` 并产生本地 error 事件 | 将已显示文本标为 final |
| 输出非合法结构 | 有限修复；耗尽后返回失败的 `ValidationReport`，不签发决定 | 宽松解析后默默补字段 |
| 证据不足/引用失效 | 合法 refusal，或 `kind=no_progress` 携带缺口供 02 重建上下文 | 让模型补写证据 ID |
| 安全过滤拒绝 | 显式 `refusal`，保留允许的替代路径 | 伪装为技术失败 |
| Usage 回报缺失 | 标记估算和不确定性，限制后续预算 | 按零成本继续 |
| Provider state 不可删除/跨区 | 不启用该连续性模式 | 将其作为唯一会话状态 |

## 9. 观测指标

- `model_invocations_total{contract,route,status,finish_reason}`。
- `model_time_to_first_event_seconds`、`model_duration_seconds`、`stream_gap_seconds`。
- `model_input_tokens`、`model_output_tokens`、`model_cost` 和预算使用率。
- `prompt_compile_duration_seconds`、`context_token_ratio{partition}`、`context_truncations_total{partition,reason}`。
- `contract_resolution_failures_total`、`contract_integrity_failures_total`。
- `structured_decisions_total{kind}`、`schema_validation_failures_total{rule}`。
- `semantic_validation_failures_total{severity,rule_id}`。
- `evidence_validation_failures_total{reason}`、无效引用率和证据覆盖率。
- `repair_attempts_total{reason,result}`、修复放大 Token/延迟。
- `provider_fallback_total{from_route,to_route,reason}`。
- `stream_preview_final_divergence_total`，目标为零语义分歧。
- `cross_tenant_context_rejections_total`，安全硬指标目标为零泄漏。

Trace 必须关联 contract bundle、context manifest、model invocation、model run result 和 structured decision；内容正文使用哈希/引用，不进入普通指标标签。

## 10. 可替换端口

| 端口 | 稳定语义 | 可替换实现 |
| --- | --- | --- |
| `PromptRegistryPort` | 版本、状态、完整性、发布和回滚 | Git/OCI、数据库、Prompt 平台 |
| `ContractRegistryPort` | Task/Schema/规则/消费者兼容 Bundle | Schema Registry、自建控制面 |
| `ModelRoutingPort` | 能力、风险、区域、成本和已评测回退 | 模型网关、策略路由服务 |
| `ModelProviderPort` | `ModelInvocation -> ModelStreamEvent/ModelRunResult` | OpenAI、Azure、Anthropic、Gemini、Bedrock、本地模型 |
| `TokenizerPort` | 按目标模型估算和核算 Token | 供应商 tokenizer、本地实现 |
| `StructureParserPort` | 供应商输出到 canonical candidate | JSON Schema、typed output、grammar parser |
| `SemanticValidationPort` | 确定性字段和跨字段规则 | 代码规则、规则引擎、领域服务只读校验 |
| `EvidenceValidationPort` | claim 与当前 EvidencePack 的成员/有效性校验 | 04 Citation/Evidence 服务 |
| `ContentSafetyPort` | 内容安全检测和转换信号 | 自建或云安全服务 |
| `TelemetryPort` | 模型、Prompt、解析和门禁语义 | OpenTelemetry、供应商观测平台 |

Provider Adapter 只能处理模型协议。任何带 Agent loop、handoff、tool execution 或 graph state 的框架集成必须进入 02 的公共 `RuntimeAdapter` SPI。

## 11. 配置项

| 配置键 | 含义 | 约束 |
| --- | --- | --- |
| `prompt.contract_bundle_version` | 默认 Bundle | 由 Release 冻结，不读取 latest |
| `prompt.max_variable_bytes` | 单变量大小 | 超限拒绝，不静默截断关键字段 |
| `prompt.instruction_precedence` | 指令层级 | 组织安全层不可由租户放宽 |
| `context.partition_budgets` | 各上下文分区 Token | 总和不超 ModelInvocation 预算 |
| `model.route_policy_version` | 模型选择与回退 | 回退必须已评测且区域兼容 |
| `model.timeout_ms` / `max_attempts` | 单次与重试 | 受 Runtime deadline 限制 |
| `model.sampling_profiles` | temperature、top_p、seed 等 | 按风险/任务批准 |
| `stream.max_buffer_bytes` / `event_timeout_ms` | 流聚合边界 | 无可信 final 时结果为 unknown |
| `output.schema_strictness` | 严格字段和扩展区策略 | 消费者兼容优先 |
| `output.max_repair_attempts` | 结构修复次数 | 默认小值并计入预算 |
| `evidence.required_claim_types` | 必须引用的 claim | 缺证据不得生成确定性结论 |
| `normalization.rule_set_version` | 规范化规则 | 每次改变均可追溯 |
| `provider_state.enabled` / `retention` | 会话连续性 | 必须支持租户、区域和删除治理 |
| `content_logging.mode` | none、hash、secure-reference | 生产默认不记录正文 |

## 12. 验收标准

- 每次模型调用前都能从冻结的 `PromptContract/ContractBundle` 重建同语义 `ModelInvocation`。
- Prompt、Schema、字段字典、证据、拒绝、语义规则和消费者兼容以 Bundle 原子发布。
- `ContextManifest` 的 tenant、purpose、来源、权限、有效期和完整性在编译前被校验。
- 用户、RAG、Memory、附件、历史模型输出、工具结果和 MCP Prompt 无法改变可信指令或 Schema。
- 流式 delta 只作预览；同一完整候选经流式或非流式路径得到相同 `StructuredDecision`。
- Provider `succeeded` 不被解释为业务完成；输出必须再经过 Schema、语义和证据门禁。
- 非法 JSON、额外字段、未知枚举、跨字段冲突和证据伪造均产生稳定 ValidationReport/ProblemDetail，且不签发可应用的 `StructuredDecision`。
- `ToolIntent` 不携带授权结论或执行凭据，且只能由 02 转交 05。
- 编排候选不直接创建 Workflow 状态，只能由 02 转交 06。
- 模型回退只发生在 Release 中已评测、能力和区域兼容的路由集合内。
- Provider state 与 UEAF Task/Run/Checkpoint/Memory 明确分离，并具备租户、保留和删除控制。
- 任一底层 Agent 框架不通过 03 直接接入；Agent framework 只通过 02 Runtime Adapter 使用。
