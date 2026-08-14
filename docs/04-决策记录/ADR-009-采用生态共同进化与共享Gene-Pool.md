# ADR-009：采用生态共同进化与共享 Gene Pool

- 状态：Accepted Design Direction
- 决策日期：2026-08-14
- Architecture Generation：V2
- Maturity：Planned
- Implementation：Future

## 背景

仅优化单个 Agent 容易导致单体越来越复杂、重复创造相同能力，并扩大 Token、测试和回归成本。Skill、Tool、Workflow、Routing 与 Strategy 本身也具有独立演化价值。

## 决策

UEAF 将“整个 Agent 生态共同进化”作为 **V2** 的正式方向：

- 引入 Species / Population / Elite 的生态组织；
- 建立受治理的 Gene Pool 能力复用机制；
- 允许通过 V1 `MutationProposal(mutation_type=transfer)` 起步，并在有独立生命周期证据后再升级专门 Transfer 对象；
- 优先修改最小有效 Gene，而不是默认重写整个 Agent；
- Gene Pool 默认 tenant scoped，跨租户共享需要显式发布与重新治理；
- V2 初期 Gene Pool SHOULD 优先作为 Artifact/Registry Projection，而不是独立真相源。

本 ADR 不要求 V1 预建 Species Service、GenePool DB、Population Scheduler 或生态状态机。

## 后果

- 演化成果未来可以被整个生态复用；
- 降低重复生成、Token 和回归成本；
- V2 的 Lineage、兼容性、生态评测和撤销管理更复杂；
- 必须防止优秀 Gene 无审查传播成系统性单点风险；
- V1 只需要保留 provenance、compatibility metadata 与通用 GenomeManifest 的前向兼容性。

## 重审条件

- V1 已稳定运行并证明多个 Agent 存在重复能力；
- 独立 Skill/Tool 复用收益显著高于 Registry metadata 管理成本；
- Capability Transfer 形成可靠目标侧兼容评测；
- V2 正式进入 Current 实施阶段。
