# ADR-010：默认开放演化，但分离 Experiment 与 Promote 权限

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

若只提供 `can_modify=true/false`，无法表达“AI 可以自由发现、提出和实验，但不能无条件修改生产”的要求。过度保守会削弱自我进化能力，过度开放又会把实验权限误变成生产权限。

## 决策

UEAF 定义 `EvolutionAuthorityPolicy`，对每类可演化目标分别控制：

- `Observe`：读取允许的证据与 Lineage；
- `Propose`：提出 Mutation、Transfer 或 Replacement；
- `Experiment`：在隔离环境构建和评测 Candidate；
- `Promote`：推进 Candidate 到 Canary 或 Production。

对 mutable targets，默认 `Observe=allow`、`Propose=allow`、`Experiment=allow`。`Promote` 根据风险采用 `automatic_after_gates`、`canary`、`gated` 或 `never`。

推荐默认：

- Prompt、Model Routing、Context Policy、Memory Policy：通过独立门禁后可自动 Promote；
- Workflow、Skill、Agent Topology：默认 Canary；
- Tool、Ecosystem Topology、Evolution Strategy、Meta Evolution：默认 Gated；
- Governance Kernel：Propose/Experiment/Promote 永久禁止。

企业可以收紧 mutable targets，但普通配置不能把 Governance Kernel 改为可自主进化。

## 后果

- AI 默认拥有充分的实验空间；
- 自治实验与生产风险被解耦；
- 不同企业可配置自治程度；
- 权限模型和审计事件需要区分四类行为。

## 重审条件

- 四级权限不能覆盖实际演化场景；
- 自动 Promote 在低风险 Gene 上仍产生不可接受风险；
- 新治理机制可以在不降低控制力的情况下更简化表达。
