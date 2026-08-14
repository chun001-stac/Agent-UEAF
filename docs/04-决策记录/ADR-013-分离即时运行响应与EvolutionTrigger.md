# ADR-013：分离即时运行响应与 EvolutionTrigger

- 状态：Accepted
- 决策日期：2026-08-14
- Architecture Generation：V1
- Implementation：Current

## 背景

如果把“发现问题”直接等同于“立即自我进化”，Agent 会因为单次噪声、短期 Provider 故障或暂时性数据波动频繁修改 Prompt、Context、Workflow 或 Tool，导致版本震荡、评测浪费和生产不稳定。

另一方面，真正的高风险问题（如跨租户泄漏、越权动作、错误删除、严重系统性质量崩溃）不能等待 EvolutionRun 完成后再处理，必须由现有运行、安全、发布与 SRE 机制第一时间止血。

因此 UEAF V1 必须把“现在如何保护生产”与“未来是否值得改变自身”拆成两条独立反馈链。

## 决策

### 1. 两条反馈链

UEAF V1 明确区分：

```text
Operational Response
  解决：现在怎么办

Evolution Response
  解决：以后是否需要改变自己
```

即时运行响应由现有 UEAF 能力负责，包括 Runtime、模块 07 安全治理、模块 09 生产运行、模块 08 Release/rollback、Tool Gateway、fallback、isolation、degrade 与 kill switch。

Evolution Plane 不成为事故响应系统，也不得为了“进化”延迟必要的 rollback、disable、fallback 或隔离。

### 2. `EvolutionTrigger` 的语义

`EvolutionTrigger` 不是异常信号、告警、Incident、回滚命令或 Mutation 指令。

它只表示：

> 在已有运行/安全响应之后，基于足够证据，当前问题或机会值得启动一次有预算、可停止的 EvolutionRun 来评估是否应产生长期版本改变。

Trigger 可以最终得到 `no_valid_candidate`；创建 Trigger 不代表 Agent 必须发生变化。

### 3. Reactive 与 Opportunistic

V1 Trigger 分为两类：

- `reactive`：针对 failure cluster、quality/cost/latency drift、安全或回归问题；
- `opportunistic`：针对新模型、新 Tool、新 Provider 能力、成本优化或新业务能力机会。

因此“系统没有故障”也可以产生 EvolutionTrigger。

### 4. P0-P3 响应优先级

Trigger Policy 使用四级响应优先级，但不新增新的 Canonical Object：

| Priority | 典型场景 | 即时动作 | Evolution |
|---|---|---|---|
| P0 | 数据泄漏、越权、高风险错误副作用 | 立即隔离/回滚/kill | 可立即形成高优先 Trigger |
| P1 | 大面积质量崩溃、系统性 Tool/Model 失败 | fallback/降级/限流 | 高优先 EvolutionRun |
| P2 | 可复现质量、成本、延迟退化 | 通常继续运行或局部降级 | 聚合确认后 Trigger |
| P3 | 新模型、新 Tool、低成本机会、周期优化 | 无紧急动作 | 低优先/计划性 Trigger |

P0/P1 MAY 绕过普通 cooldown 或最小样本数量，但不得绕过权限边界、Eval root、Release Authority、Budget Enforcement 或 Governance Kernel。

### 5. Trigger Gate

非 P0 的 Trigger 默认必须依次检查：

1. `evidence_sufficient`：证据数量、来源质量、置信度或可复现性足够；
2. `still_relevant`：问题仍存在或具有明确复发概率；Opportunity 仍可用；
3. `mutable_surface_match`：根因至少部分落在当前 `EvolutionAuthorityPolicy` 允许的 mutable surface；
4. `existing_mitigation_insufficient`：已有 fallback/runbook/rollback 不能充分解决长期问题；
5. `novelty_sufficient`：不是在环境未变化时重复已经失败或无效的 Proposal；
6. `expected_value_positive`：预期业务价值高于演化成本和回归风险；
7. `cooldown_satisfied`：满足最小时间、新任务数量或新证据要求。

Trigger Gate SHOULD 由规则、统计、索引和 Projection 优先实现；只有根因分类或价值判断不能可靠确定时才逐级升级到模型。

### 6. 三个时间尺度

V1 推荐把反馈分为：

```text
毫秒~分钟：Operational Response
小时~天：Evolution Response
周~月：Optimization Review / Opportunistic Evolution
```

Evolution 不替代实时保护，实时保护也不直接改变长期 Genome。

## 后果

- 严重问题可以立即止血，不等待自我进化；
- 普通噪声不会频繁触发版本修改；
- EvolutionTrigger 数量显著少于原始异常/告警数量；
- Trigger Engine 可以主要依赖确定性与统计逻辑，降低 Token；
- Evolution Plane 与安全/SRE/Release Control 的职责边界更清晰；
- 需要保存触发前的 Gate 证据和已有 mitigation 引用以便审计。

## 重审条件

- 实际运行证明 P0-P3 无法覆盖主要响应模式；
- Trigger Gate 过度保守导致长期问题无法进入演化；
- Trigger Gate 过度敏感导致版本震荡或演化成本异常；
- 未来 V2 需要生态级联动响应与 Trigger 协调。