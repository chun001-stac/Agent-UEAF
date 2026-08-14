# ADR-009：采用生态共同进化与共享 Gene Pool

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

仅优化单个 Agent 容易导致单体越来越复杂、重复创造相同能力，并扩大 Token、测试和回归成本。Skill、Tool、Workflow、Routing 与 Strategy 本身也具有独立演化价值。

## 决策

UEAF 将“整个 Agent 生态共同进化”作为 Evolution Plane 的正式方向：

- 引入 `EcosystemGenome` 与 `SpeciesDefinition`；
- Agent、Skill、Tool、Workflow 与 Strategy 可作为独立 Species 演化；
- 建立受治理的 `GenePool` 保存已验证、可复用能力；
- 允许通过 `CapabilityTransferProposal` 实现跨 Agent/Species 横向能力迁移；
- 优先修改最小有效 Gene，而不是默认重写整个 Agent；
- Gene Pool 默认 tenant scoped，跨租户共享需要显式发布与重新治理。

## 后果

- 演化成果可以被整个生态复用；
- 降低重复生成、Token 和回归成本；
- Lineage、兼容性和撤销管理更复杂；
- 必须防止一个优秀 Gene 无审查传播成系统性单点风险。

## 重审条件

- 独立 Skill/Tool Genome 的管理成本显著高于复用收益；
- Capability Transfer 无法形成可靠的目标侧兼容评测；
- 生态规模不足以证明共享 Gene Pool 有价值。
