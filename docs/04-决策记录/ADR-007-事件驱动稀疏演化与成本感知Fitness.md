# ADR-007：采用事件驱动稀疏演化与成本感知 Fitness

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

如果每个生产任务结束后都调用 LLM 总结、反思、抽取经验、生成候选并再次用 LLM Judge，演化成本会与任务量近似线性增长。传统大 Population / 多 Generation 的遗传算法如果每个 Candidate 都依赖模型生成和模型评测，也会产生不可接受的 Token、费用和延迟。

同时，只以准确率或任务完成率为 Fitness 会激励系统通过增加 Context、Agent 数量、Critic 轮数和模型调用来换取小幅能力提升，最终形成经济上不可用的“能力增长”。

## 决策

UEAF 的默认 Evolution Mode 采用：

1. **事件驱动触发**：没有有效 `EvolutionTrigger` 时不启动 EvolutionRun；
2. **结构化预筛选**：Raw Evidence 先经过去重、统计、聚类、显著性和新颖性过滤；
3. **Sparse Mutation**：默认只允许证据相关的少量 Gene 变化；
4. **有限候选**：每轮 Candidate 数和 Generation 数必须有硬上限；
5. **Evaluator 升级漏斗**：Deterministic → Statistical → Small Model → Strong Model → Human；
6. **既有 Budget Domain / budget slice**：限制模型调用数、输入/输出 Token、金额、时间、候选数、代数和强模型调用数，不建立独立 `EvolutionBudget`；
7. **多维 Fitness**：同时记录 capability、quality、safety、robustness、Token、费用、latency、complexity 和 regression risk。

稳定系统在无 Trigger 时，额外演化 Token SHOULD 接近零。

## 结果判定

以下情况不能因为质量单项提升自动晋升：

- Token 或费用显著上升；
- P95 延迟恶化超出 Profile；
- Tool/Agent fan-out 或运行复杂度显著增加；
- 安全硬失败；
- 关键切片回归；
- 评测证据 inconclusive。

实现 MAY 计算 `EvolutionROI` 或 `IntelligenceEfficiency`，但必须保留原始分项。

## 后果

- Evolution 成本与“新颖且重要的问题”数量相关，而不是与全部请求数量线性相关；
- 可在大多数任务上完全不调用演化模型；
- 更倾向于把知识编译成 Tool/Policy/Workflow 而不是不断加 Prompt；
- 某些全局最优搜索可能因 Candidate 限额而变慢，需要证据后再放宽；
- GA/Population Search 仅在自动评价足够便宜且搜索收益有证据时扩大人口。

## 被否决方案

### 每任务自动反思

否决。重复信息多，Token 成本不可控，且容易将噪声升级为长期经验。

### 能力提升即可晋升

否决。会鼓励无限 Context、多 Agent 和更多推理轮次。

### 默认大规模遗传算法 Population

否决。UEAF 默认使用 reasoning-guided sparse search；Population Search 是按证据启用的策略。

## 重审条件

- 模型推理成本下降到可忽略且仍满足延迟/SLO；
- 某业务域证明大 Population Search 的 EvolutionROI 持续高于 Sparse Mutation；
- 出现新的低成本自动验证方法显著改变 Candidate 成本曲线。
