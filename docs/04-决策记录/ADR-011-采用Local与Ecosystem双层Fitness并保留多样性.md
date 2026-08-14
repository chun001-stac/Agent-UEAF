# ADR-011：采用 Local 与 Ecosystem 双层 Fitness，并保留多样性

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

单个 Agent 或 Skill 可能通过增加共享 Agent 调用、强模型调用或工具依赖提高自身成绩，却把 Token、延迟、容量竞争和故障风险转嫁给整个生态。若只优化 Local Fitness，会产生局部最优和 Monoculture Risk。

## 决策

每个生态 Candidate 必须同时评估：

1. `Local Fitness`：自身任务成功率、质量、安全、鲁棒性、Token、费用、延迟与回归；
2. `Ecosystem Fitness`：整体业务效用、总成本、全链路延迟、共享资源竞争、相关故障、依赖集中度、运营复杂度、公平性和多样性风险。

Local Fitness 提升但 Ecosystem Fitness 明显退化时，不得自动 Promote。

UEAF 同时定义 `DiversityPolicy`：保留替代 Species、不同模型/实现路线和若干 Elite Variants，限制共享 Gene/依赖集中度。当前最优 Genome 不应导致所有差异显著的替代实现被删除。

## 后果

- 避免成本和风险从局部 Agent 转嫁给生态；
- 降低共享隐藏缺陷导致的系统性故障；
- 评测与选择成本上升；
- 需要建立生态级资源归因和依赖关系视图。

## 重审条件

- 生态规模很小且双层 Fitness 没有可测外部性；
- 多样性约束长期造成明显质量损失且无法通过风险收益证明；
- 出现更可靠的全局优化机制可覆盖当前双层模型。
