# ADR-005：采用独立 Evolution Plane 与候选式自改

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

UEAF 需要支持 Agent 从真实任务、评测和生产反馈中持续改进，但如果允许正在运行的 Agent 直接修改自己的 Prompt、Workflow、Tool、Memory Policy 或代码，会破坏 `ReleaseManifest` 的不可变性、审计可追溯性和回滚语义，也会让运行时与发布治理耦合。

同时，自我进化不应绑定某一种底层 Agent Runtime 或某一种优化算法。

## 决策

新增逻辑上的 `Evolution Plane`，其职责是：

- 聚合结构化 Experience 和反馈；
- 产生 `EvolutionTrigger`；
- 形成 `MutationProposal`；
- 构建新的 `AgentGenome` / `CandidateRelease`；
- 将候选提交给现有模块 08/07/09 的评测、安全、生产和发布门禁；
- 保存 Lineage 和失败实验历史。

任何自我修改都只能产生新的候选。正在运行的 `ReleaseManifest` 不允许原地改变；当前 Production Agent 无权把自身候选直接激活为生产版本。

Evolution Strategy 通过稳定端口接入，可实现为 LLM-guided mutation、Genetic Search、Bayesian Optimization、RL、Population Search 或 Human-guided Evolution。

## 后果

- Runtime 热路径与演化慢路径分离；
- 当前版本可复现、可回滚；
- 演化算法可替换，不把 UEAF 锁死为遗传算法；
- 需要新增 Genome、Lineage、EvolutionRun 和 Candidate 领域对象；
- 候选构建与评测产生额外成本，因此必须有独立预算和停止策略。

## 被否决方案

### Agent 原地修改自身

否决。会破坏运行绑定版本、审计、回放和职责分离。

### 把进化完全放入 Runtime Adapter

否决。不同 Runtime 会产生不同企业语义，并允许供应商内部机制绕过 UEAF 发布治理。

### 固定采用 Genetic Algorithm

否决。GA 只是可选搜索策略；许多语义问题更适合 LLM-guided sparse mutation，许多参数问题更适合统计或 Bayesian Optimization。

## 重审条件

- UEAF 未来引入可验证的在线参数自适应，且能证明不改变 Release 语义；
- 发布清单模型发生根本变化；
- 监管要求禁止任何自动候选生成。
