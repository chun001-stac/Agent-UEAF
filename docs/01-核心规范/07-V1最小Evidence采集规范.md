# UEAF V1 最小 Evidence 采集规范

版本：`0.1.0-draft`  
规范状态：Draft  
Architecture Generation: `V1`  
Maturity: `Required`  
Implementation: `Current`

## 1. 范围

本文定义 UEAF V1 为受控演化自动采集 Evidence 的最小规范。目标是在不建立第二套 Evolution 数据平台、不全量保存 Prompt/Trace/Payload、不让 LLM 持续监控所有 Agent 的前提下，为 `EvolutionTrigger`、Trigger Gate 和 `EvolutionRun` 提供足够、可追溯且成本可控的证据。

核心原则：

> **全量采集小指标，条件采集中证据，按需读取大证据。**

职责分工：

```text
Module 02..08
  -> 在事实产生位置输出结构化观测
Module 09
  -> buffer / sampling / aggregation / retention / evidence projection
Module 11
  -> Trigger Candidate / Trigger Gate / Evidence Expansion
```

模块 11 MUST NOT 复制 Trace、Log、Eval、Action、Audit 或业务 Payload 成为第二真相源。

## 2. Evidence 三层漏斗

### 2.1 L0：Always-on Minimal Evidence

所有生产 Run 默认产生极小结构化观测，用于统计、漂移检测和定位引用。目标是单条记录保持小而稳定，不携带大文本正文。

典型内容：

```text
tenant / environment
agent / release / run / trace refs
task class / outcome / duration
model calls / tokens / amount
tool calls / retries / error class
context/retrieval counters
security flags
schema / producer version
```

L0 MUST NOT 默认包含：

- 完整用户输入；
- 完整 Prompt；
- 完整模型输出；
- 完整 RAG chunk；
- 完整 Tool input/output；
- chain-of-thought 或模型私有推理；
- 高基数 Payload 作为 Metric label。

### 2.2 L1：Conditionally Sampled Evidence

完整 Trace、详细状态迁移、模型/Tool/RAG Payload、case-level Eval 等大证据按采样或风险条件保留。

推荐默认策略：

```text
successful run full trace    low sample rate
ordinary failure             medium/high sample rate
P1 incident                  high/100%
P0 security/safety incident  100% where policy permits
new canary release           temporarily elevated sample rate
stable release               progressively reduced sample rate
```

采样 Profile MUST 可按 tenant、environment、risk、agent、release 调整。

### 2.3 L2：On-demand Evidence Expansion

只有 Trigger Candidate 或 Trigger Gate 无法仅依赖 L0/L1 聚合判断时，模块 11 才按引用读取少量相关大证据。

推荐最小对照集合：

```text
A: current failed samples
B: current successful samples
C: baseline release samples
```

Evidence Expansion MUST 设置样本数、字节、Token、时间窗和敏感级别上限，禁止无界读取历史。

## 3. 统一 Telemetry 事件骨架

业务模块在事实产生位置通过既有 `TelemetryPort` 或等价内部端口输出结构化观测。公共骨架 SHOULD 至少包含：

```yaml
timestamp: timestamp
tenant_id: string
environment: string
agent_id: string | null
release_id: string | null
run_id: string | null
trace_id: string | null
event_type: string
stage: string
status: string
severity: string | null
duration_ms: integer | null
error_code: string | null
schema_version: string
producer_version: string
measurements: object
dimensions: object
refs: object
```

规则：

1. `measurements` 只放数值/可聚合测量；
2. `dimensions` 只放受控低基数枚举；
3. `refs` 保存 run/trace/model invocation/context/action/eval 等高基数引用；
4. 大文本和敏感 Payload 不得进入 Metric dimension；
5. 模块 09 可以规范化字段名，但不得改变源领域事实语义。

## 4. 最小 Run Summary

模块 09 SHOULD 为每个终结或可计量的 Run 形成一条轻量 Summary Projection。它不是新的 Canonical Object。

```yaml
run_id: string
agent_id: string
release_id: string
task_class: string | null
completion_disposition: string | null
duration_ms: integer
model_calls: integer
tool_calls: integer
retry_count: integer
input_tokens: integer
output_tokens: integer
total_amount: number | null
context_tokens: integer | null
retrieval_calls: integer | null
security_flag_count: integer
primary_error_class: string | null
trace_ref: string | null
```

Trigger Candidate Detector 默认读取 Run Summary、聚合窗口、Error Fingerprint、Eval/SLO/Security Projection，而不是全量 Trace。

## 5. 各模块最小 Evidence 字段

| 模块 | Always-on 最小字段 | 条件/按需字段 |
|---|---|---|
| 02 Runtime/State | phase/disposition、duration、retry、wait/cancel、run/release refs | 完整状态迁移、checkpoint/debug trace |
| 03 Model | model route/family、input/output tokens、amount、latency、finish/error、schema validity、retry | Prompt/Input/Output、provider raw payload，通过 invocation ref 读取 |
| 04 Context/RAG/Memory | query count、candidate/retrieved/selected count、retrieval empty、filter count、context tokens、latency | retrieval manifest、document/chunk refs、必要上下文片段 |
| 05 Tool/MCP/Action | tool id、operation class、latency、status、error code、retry、outcome certainty、reconciliation flag | Tool input/output、ActionReceipt 详情，通过 action/receipt ref 读取 |
| 06 Workflow/Multi-Agent | node count、fan-out、handoff count、failed node class、retry、duration | 完整 node/handoff trace |
| 07 Security | allow/deny/approval outcome、risk class、security event class、policy ref | 敏感事件详情，按权限受控读取 |
| 08 Eval/Release | eval result ref、dataset/slice、grade/score、regression flags、gate outcomes、candidate/release refs | case-level trace、judge/human review evidence |
| 09 Production/Ops | queue depth、capacity、SLO、P50/P95/P99、error rate、resource/telemetry health | debug logs、host/process diagnostics |
| 10 Build/Artifact | candidate/genome/artifact/version/compatibility refs | build logs、SBOM/debug artifact |

字段命名 MAY 按各领域 Schema 细化，但跨模块聚合必须能稳定映射到上述语义。

## 6. RAG 最小观测

RAG 是 V1 重点观测域。模块 04 SHOULD 至少输出：

```yaml
query_count: integer
candidates_before_policy: integer | null
candidates_after_policy: integer | null
retrieved_count: integer
reranked_count: integer | null
context_selected_count: integer
retrieval_empty: boolean
retrieval_latency_ms: integer
context_tokens: integer
retrieval_manifest_ref: string | null
```

不得为了 Evolution 将所有 retrieved chunks 复制到模块 11。需要调查时通过 `retrieval_manifest_ref` 读取目标样本。

## 7. Tool 结果确定性

Tool Evidence MUST 区分“失败”和“结果未知”。至少保留：

```yaml
tool_status: succeeded | failed | timeout | denied | cancelled | unknown
outcome_certainty: certain_success | certain_failure | unknown
reconciliation_required: boolean
action_ref: string | null
receipt_ref: string | null
```

Evolution 不得因为 timeout 计数升高就自动提出增加 retry；`unknown` 必须遵守模块 05 对账语义。

## 8. Error Fingerprint

V1 SHOULD 优先使用确定性 Fingerprint 进行错误去重，而不是对每条错误执行 embedding。

推荐输入：

```text
release_id
stage
error_code
tool/model/adapter id
operation class
normalized error signature
```

内部 Projection 可保存：

```yaml
fingerprint: string
count: integer
affected_runs: integer
first_seen_at: timestamp
last_seen_at: timestamp
sample_refs: [string]
```

只有无法通过确定性规则归类的自然语言/新型错误 MAY 进入 embedding/semantic clustering。

## 9. Streaming Aggregation

Trigger Engine 不应扫描全量 Trace。模块 09 SHOULD 维护紧凑滚动窗口，例如：

```text
5m
1h
24h
7d baseline
```

典型聚合：

```yaml
runs: integer
success_rate: number
failure_rate: number
p50_latency_ms: number
p95_latency_ms: number
p99_latency_ms: number
avg_input_tokens: number
avg_output_tokens: number
cost_per_run: number
cost_per_success: number
tool_failure_rate: number
retrieval_empty_rate: number
schema_invalid_rate: number
security_event_rate: number
```

窗口数值只是 Projection，不覆盖 Run/Eval/Action 原始事实。

## 10. Adaptive Sampling

采样策略 SHOULD 随风险与稳定度自适应：

```text
new/canary release -> elevated sampling
stable release     -> reduced sampling
failure spike      -> temporary sampling increase
P0/P1              -> highest permitted evidence retention
```

成功样本 SHOULD 使用 reservoir/representative sampling 保留基线，不得只保存失败样本。

## 11. Metric Cardinality

Metric label MUST 使用受控低基数字段，例如：

- `agent_id`；
- `release_id`；
- `task_class`；
- `model_route`；
- `tool_id`；
- `error_code`；
- `region`；
- `environment`。

以下字段禁止作为常规 Metric label：

- `run_id`；
- `trace_id`；
- `user_id`；
- 原始 query/prompt；
- document/chunk id；
- 完整 URL；
- 自由文本 error message。

高基数字段只作为 Trace/Event/Artifact `ref`。

## 12. Collection Cost Policy

Evidence 采集预算属于模块 09/11 的 Policy/Config，不新增 Canonical Object。至少 SHOULD 支持：

```yaml
success_trace_sample_rate: number
failure_trace_sample_rate: number
p0_p1_trace_sample_rate: number
max_hot_storage_bytes: integer
max_evidence_events_per_second: integer
max_semantic_cluster_jobs_per_hour: integer
max_trigger_candidates_per_hour: integer
max_expansion_samples_per_trigger: integer
max_expansion_bytes_per_trigger: integer
```

资源紧张时的降级顺序：

```text
preserve Audit / Security / ActionReceipt / P0-P1
preserve Run Summary / core counters
reduce success full-trace sampling
reduce verbose logs/debug payload
reduce semantic clustering
```

Audit、Security、ActionReceipt 等受规范/合规要求保护的数据不得因普通 Evolution 成本策略静默丢弃。

## 13. 异步采集与背压

业务 Run 不得同步等待所有 Evidence 持久化。推荐：

```text
producer emit
  -> local/non-blocking buffer
  -> telemetry queue
  -> batch collector
  -> metric/trace/log stores + projections
```

Telemetry backpressure 时：

1. 优先保证 Audit/Security/ActionReceipt；
2. 保护 P0/P1 Evidence；
3. 保护最小 Run Summary；
4. 降低普通 success trace；
5. 最先丢弃 verbose debug。

普通 Telemetry 故障 SHOULD 标记 Evidence gap，但不默认让低风险业务 Run 一起失败；受监管 Profile 可提高最低证据门槛。

## 14. 存储分层

V1 推荐复用现有基础设施，不要求独立 Evolution DB/Vector DB/Graph DB/TSDB。

```text
HOT   recent aggregates / recent failures / trigger inputs
WARM  sampled traces / eval / medium-term comparison
COLD  archived trace/artifact/object storage
```

模块 11 默认查询 HOT；只有 Trigger Gate 或 EvolutionRun 明确需要时才定向读取 WARM/COLD。

## 15. Trigger Candidate 与 Evidence Expansion

`Trigger Candidate` 是内部分析结果，不是 Canonical Object。

默认数据流：

```text
Run Summary / Aggregate Window / Fingerprint / Eval / Security
  -> Trigger Candidate Detector
  -> Trigger Gate
      -> enough evidence: decide
      -> insufficient: Evidence Expansion
  -> EvolutionTrigger or no_trigger
```

Evidence Expansion 只获取与当前 subject、release、fingerprint、time window、mutable surface 直接相关的引用和样本。

## 16. Token 原则

正常 Collection 和 Aggregation 的目标应为 **0 LLM Token**。

优先级：

```text
rules / counters / SQL / statistics / fingerprints
  -> semantic index if needed
  -> cheap model only when needed
  -> strong model only for unresolved diagnosis/value judgement
```

禁止使用中央强模型持续读取所有 Agent Trace 作为默认监控方案。

## 17. V1 不变量

1. 原始事实由原领域拥有，模块 11 只保存引用/投影；
2. 所有 Run 可产生小型结构化 Evidence，但不要求保存全部大 Payload；
3. Trigger Engine 默认读取聚合和 Fingerprint，不扫描全量 Trace；
4. 大 Evidence 只在 Trigger Gate/EvolutionRun 按需扩展；
5. 正常采集路径不依赖 LLM；
6. Metric label 严格控制基数；
7. 采样、保留、聚合和扩展均有成本上限；
8. Audit/Security/ActionReceipt 的保留规则优先于 Evolution 成本优化；
9. 模块 09 负责 telemetry collection/aggregation，模块 11 不建设第二套数据平台；
10. Evidence 缺口必须可见，禁止把“没有数据”解释为“系统正常”。
