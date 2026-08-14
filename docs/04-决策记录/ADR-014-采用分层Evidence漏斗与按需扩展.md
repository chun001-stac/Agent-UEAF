# ADR-014：采用分层 Evidence 漏斗与按需扩展

- 状态：Accepted
- 决策日期：2026-08-14
- Architecture Generation：V1
- Implementation：Current

## 背景

若为了自我进化对所有 Agent 全量保存 Prompt、模型输出、RAG chunk、Tool payload 和完整 Trace，并持续交给模型分析，Evidence 成本会随生产请求量快速增长，形成日志、数据库、Token、计算和隐私风险。

另一方面，仅保存少量错误码又不足以支持 Trigger Gate、根因判断和受控演化。

因此 V1 需要一种“默认很轻、异常时逐步展开”的采集方式。

## 决策

### 1. 三层 Evidence 漏斗

V1 采用：

```text
L0 Always-on Minimal Evidence
  -> L1 Conditionally Sampled Evidence
  -> L2 On-demand Evidence Expansion
```

- L0：所有 Run 产生极小结构化观测和 Summary；
- L1：完整 Trace/详细 Payload 按成功、失败、Canary、P0/P1 等策略采样；
- L2：只有 Trigger Candidate/Trigger Gate/EvolutionRun 需要时，按引用拉取少量目标样本。

### 2. 职责边界

```text
Module 02..08  产生领域事实
Module 09      采集、buffer、sampling、aggregation、retention
Module 11      Trigger Candidate、Trigger Gate、Evidence Expansion
```

模块 11 不建设第二套 Trace/Log/Metric/Eval/Action 数据平台，也不得复制这些领域的权威事实。

### 3. 正常采集路径 0 LLM Token

默认 Collection、Run Summary、Fingerprint、滚动统计和 Trigger Candidate 检测使用规则、计数、SQL/streaming aggregation 和统计方法。

只有确定性信息不足以完成 Trigger Gate 的根因/价值判断时才逐级使用 cheap model 和 strong model。

### 4. Error Fingerprint 优先于全量 Embedding

错误先根据 stage、error_code、tool/model/adapter、operation 和 normalized signature 做确定性去重。

仅无法可靠归类的剩余错误进入 semantic clustering/embedding。

### 5. 自适应采样

成功 Run 使用低比例代表性采样；失败、Canary、P0/P1 使用更高比例。稳定 Release 可降低采样，异常上升时可临时提高采样。

Audit、Security、ActionReceipt 等最低保留要求不受普通 Evolution 成本策略削减。

### 6. 高基数隔离

`run_id`、`trace_id`、`user_id`、query、prompt、document/chunk id 等高基数字段不得作为常规 Metric label；只作为 Trace/Event/Artifact 引用。

### 7. Evidence Expansion 使用对照样本

需要详细调查时，优先抽取：

```text
A current failed samples
B current successful samples
C baseline release samples
```

并设置样本数、字节、Token、时间窗和敏感级别上限。

### 8. 不新增 Evidence Canonical Object

`RunSummary`、`ErrorFingerprint`、`AggregateWindow`、`TriggerCandidate` 和 Evidence Collection Budget 均可作为 Projection/Policy/Config/内部记录存在，不因本 ADR 自动升级为新的跨模块 Canonical Object。

## 后果

- 正常监控成本主要来自结构化遥测和聚合，而不是 LLM；
- Full Trace 和大 Payload 的存储增长显著降低；
- Trigger Engine 可以在很小的数据表面上工作；
- 异常时仍可通过引用恢复足够上下文；
- 需要设计采样、retention、backpressure 和 Evidence gap 可观测性；
- 对采样配置不当的系统，仍可能出现证据不足或存储过量，需要持续校准。

## 重审条件

- 实际运行证明 L0 字段不足以可靠发现主要问题；
- 采样导致关键回归长期无法定位；
- Evidence Expansion 成为主要 Token/存储成本来源；
- 生态规模进入 V2，需要跨 Agent 资源归因和生态级 Evidence 聚合。
