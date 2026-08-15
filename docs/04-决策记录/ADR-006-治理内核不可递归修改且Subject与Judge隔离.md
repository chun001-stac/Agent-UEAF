# ADR-006：治理内核不可递归修改，Evolution Subject 与 Judge 必须隔离

- 状态：Accepted
- 决策日期：2026-08-14

## 背景

递归自我改进如果允许被优化对象同时修改自身评测标准、保留集、权限、发布权或预算上限，会出现 reward hacking、测试污染、指标腐化和自提权。即使模型能力提升，也无法再证明“更好”来自真实能力而不是标准被放宽。

## 决策

UEAF 将以下能力定义为默认不可由同一递归链自主修改的 Governance Kernel：

- Identity / Delegation root；
- PDP/PEP 与权限模型；
- Tool Gateway 强制副作用边界；
- Secret/Credential 管理；
- Audit 完整性与保留；
- Eval root、holdout 答案、核心阈值和 Judge 权限边界；
- Release Authority 与 Manifest 签名；
- 既有 Budget Domain 对 Evolution budget slice 的强制执行；
- kill switch、删除传播和法律保留。

同时要求至少四个逻辑角色分离：

```text
Evolution Subject
  -> Proposer / Builder
  -> Evaluator / Judge
  -> Release Authority
```

允许同一模型供应商或同一基础模型承担不同角色，但必须使用不同服务身份、上下文、权限和证据写入边界。

## 强制规则

- Candidate 不得修改用于评估自身的冻结 `EvalConfig/EvaluationBundle`、阈值根或保留集答案；
- Candidate 不得写入或覆盖自身 Eval 事实；
- Judge 不得修改 Candidate；
- Judge 不得持有生产业务工具写权限；
- Proposer/Builder 不得签发 `ReleaseDecision` 或 `ReleaseManifest`；
- 修改 Governance Kernel 必须进入独立治理变更流程，不属于自动递归进化。

## 后果

- 自我进化存在稳定外部参照；
- 可降低 reward hacking 和 evaluator capture 风险；
- 需要服务身份、数据集权限和证据存储隔离；
- 递归深度不会无限扩散到治理内核；
- 部分真正的“自修改”需要人工或独立治理批准。

## 被否决方案

### Candidate 可以同时优化 Evaluator

否决。同一轮中会失去客观比较基准。

### 只依赖 Prompt 告诉 Agent 不要作弊

否决。该约束必须由权限、身份、存储和发布边界实现，而不是依赖模型服从。

## 重审条件

- 出现可形式化证明、可独立验证的 Evaluator 自修改机制；
- 监管或安全要求进一步扩大不可变治理边界；
- UEAF 建立跨组织独立审计/评测基础设施。
