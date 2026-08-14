# ADR-005：采用独立 Evolution Plane 与候选式自改

- 状态：Accepted
- 决策日期：2026-08-14

> 术语收敛说明：本 ADR 的核心决策仍有效；其早期 `AgentGenome`、`CandidateRelease`、独立 Lineage/Candidate 领域表述已被 ADR-012 与当前 V1 核心规范收敛。V1 当前统一使用 `GenomeManifest`，候选复用模块 10 `ReleaseCandidate`，Lineage 作为 Projection，由既有引用构建。本文以下内容按当前术语解释。

## 背景

UEAF 需要支持 Agent 从真实任务、评测和生产反馈中持续改进，但如果允许正在运行的 Agent 直接修改自己的 Prompt、Workflow、Tool、Memory Policy 或代码，会破坏 `ReleaseManifest` 的不可变性、审计可追溯性和回滚语义，也会让运行时与发布治理耦合。

同时，自我进化不应绑定某一种底层 Agent Runtime 或某一种优化算法。

## 决策

新增逻辑上的 `Evolution Plane`，其职责是：

- 消费结构化 Evidence、Experience/Pattern Projection 与生产反馈引用；
- 产生 `EvolutionTrigger`；
- 推进有预算、可停止的 `EvolutionRun`；
- 形成 `MutationProposal`；
- 构建新的 `GenomeManifest` candidate；
- 通过模块 10 构建既有 `ReleaseCandidate`；
- 将候选提交给现有模块 08/07/09 的评测、安全、生产和发布门禁；
- 通过 `GenomeManifest.parent_refs`、Mutation、ReleaseCandidate、Eval、Release 与 Event history 生成 Lineage / failed-attempt Projection。

任何自我修改都只能产生新的候选。正在运行的 `ReleaseManifest` 不允许原地改变；当前 Production Agent 无权把自身候选直接激活为生产版本。

Evolution Strategy 通过稳定端口接入，可实现为 LLM-guided sparse mutation、Genetic Search、Bayesian Optimization、Self-reflection、Workflow/Tool Search 或 Human-guided Evolution。Population Search 不是 V1 Required，且不得因本 ADR 预建 V2 Population/Gene Pool 基础设施。

Strategy 的机器可执行 Mutation Surface、Evolution Objective 与最小输入/输出约束按 ADR-016 和 `09-V1可变操作面演化目标与策略契约.md` 执行。

## 后果

- Runtime 热路径与演化慢路径分离；
- 当前版本可复现、可回滚；
- 演化算法可替换，不把 UEAF 锁死为遗传算法；
- V1 仅新增 ADR-012 明确的五个 Evolution Canonical Object，不新增独立 Candidate、Lineage、Fitness 或 EvolutionBudget 真相源；
- 候选构建与评测产生额外成本，因此必须复用既有 Budget Domain 并配置停止策略；
- Mutation 必须先通过 Subject Profile / Authority / constraint 的机器校验，再进入 Candidate Build。

## 被否决方案

### Agent 原地修改自身

否决。会破坏运行绑定版本、审计、回放和职责分离。

### 把进化完全放入 Runtime Adapter

否决。不同 Runtime 会产生不同企业语义，并允许供应商内部机制绕过 UEAF 发布治理。

### 固定采用 Genetic Algorithm

否决。GA 只是可选搜索策略；许多语义问题更适合 LLM-guided sparse mutation，许多参数问题更适合统计或 Bayesian Optimization。

### 为 Candidate / Lineage / Fitness 再建第二套权威域

否决。V1 必须复用 `ReleaseCandidate`、`EvalResult`、Budget、Release 和 parent/provenance refs；需要比较或图查询时生成 Projection。

## 重审条件

- UEAF 未来引入可验证的在线参数自适应，且能证明不改变 Release 语义；
- 发布清单模型发生根本变化；
- 监管要求禁止任何自动候选生成；
- V1 现有五个 Canonical Object 与既有 Build/Eval/Release 复用无法承载真实独立生命周期。
