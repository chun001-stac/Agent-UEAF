# ADR-001：采用 Runtime Adapter，而非重建全部 Agent Runtime

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

LangGraph、Microsoft Agent Framework、OpenAI Agents SDK、Google ADK、CrewAI 等已经提供 Agent Loop、图执行、流式、Checkpoint、HITL 或多 Agent 能力。UEAF 的核心差异是企业身份、状态、工具动作、证据和发布治理，而不是另一套通用图执行器。

## 决策

UEAF 定义 Runtime Adapter SPI，并允许一个 Run 绑定一个已批准的 Runtime Adapter。UEAF 统一企业边界契约，但保留 Runtime 内部执行模型。

Runtime Adapter MUST 提供能力声明、版本、start/resume/cancel/stream/checkpoint 接口和事件映射。每个模型步骤必须经 UEAF `ModelStepPort` 进入模块 03，每个企业工具候选必须经 `ToolIntentPort` 回到 Tool Gateway；Context、Handoff 和 Telemetry 同样只通过授予的受限端口访问。

## 后果

正面影响：

- 缩短参考实现周期；
- 可复用成熟 Runtime 的恢复与开发生态；
- 避免框架绑定进入业务契约；
- 可以用第二个 Adapter 验证可移植性。

代价：

- 需要维护能力矩阵和一致性测试；
- 不同 Runtime 的高级语义无法完全等价；
- 诊断需要关联 UEAF Trace 和 Runtime Trace。

## 禁止做法

- 在同一 Run 中由两个 Runtime 同时推进状态；
- 将 Runtime Thread/Session 自动映射为 Task 或长期记忆；
- 对不支持的能力静默降级；
- 让 Runtime 内置工具绕过 UEAF Tool Gateway。
- 让 Runtime 持有模型长期凭据或绕过模块 03 直接调用 Model Provider。

## 重审条件

当现有 Runtime 无法满足必要的事务边界、恢复语义、性能或安全隔离，并且 Adapter 补偿成本高于自研核心时重审。
