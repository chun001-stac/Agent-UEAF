# UEAF 产品定义

## 1. 产品定位

UEAF 是企业 Agent 的统一架构与治理底座，由六类能力构成：

1. **规范层**：定义身份、请求、任务、运行、上下文、动作、证据、发布与演化对象。
2. **运行外壳**：在现有 Agent Runtime 外提供准入、状态、预算、工具执行和恢复控制。
3. **控制面**：管理 Agent、Prompt、模型、能力、策略、评测和发布版本。
4. **治理面**：管理权限、审计、数据生命周期、评测、SLO 和风险。
5. **开发者面**：提供 SDK、CLI、本地运行、测试夹具、Adapter SPI 和调试能力。
6. **演化面**：把结构化运行经验转化为受预算、评测、职责分离和发布治理约束的 Candidate，不直接修改当前生产版本。

UEAF 的产品价值不是提供另一种 Agent Loop，而是让不同 Agent Runtime 在同一企业契约下安全运行、可比较发布、可持续替换，并在不破坏治理边界的前提下从真实工作中形成可验证改进。

## 2. 要解决的问题

| 问题 | UEAF 的响应 |
|---|---|
| SDK 的 Session、Thread、Memory 语义不同 | 使用统一对象和显式映射，不直接继承 SDK 名称 |
| 模型能提出工具调用但缺少企业授权 | ToolIntent 与 PolicyDecision、ApprovalRequest、ActionReceipt 分离 |
| 对话历史被误当业务状态 | Conversation、Task、Run、Checkpoint 和 BusinessFactRef 分离 |
| 多框架并存导致重复治理 | 将身份、策略、预算、审计和发布放到 UEAF 控制边界 |
| 长任务恢复可能重复副作用 | 使用事件、租约、fencing、action_key、收据和对账 |
| 模型或 Prompt 变化难以回溯 | ReleaseManifest 固定兼容版本集合和回滚目标 |
| Trace 被误当审计 | 观测数据、合规审计和评测证据分别管理 |
| 生产经验只能沉淀为日志，不能形成可验证改进 | Evolution Plane 将 Evidence 聚合为 Trigger、Experience、Mutation、Candidate、Fitness 与 Lineage |
| 自我改进容易无限消耗 Token 或修改自己的评分规则 | EvolutionBudget、事件驱动稀疏演化、独立 Evaluator 与不可递归 Governance Kernel |
| 长期经验越积越多导致上下文膨胀 | Experience 分层压缩、Active Working Set 有界，并优先编译为 Tool/Policy/Workflow/Skill |

## 3. 范围

UEAF MUST 覆盖：

- 同步、流式和异步 Agent 请求；
- 单 Agent 运行和可恢复的确定性工作流；
- 模型、Prompt、结构化输出和上下文构造；
- RAG、会话连续性和受治理长期记忆；
- 本地工具、企业 API、MCP 和远程 Agent 能力；
- 身份委托、策略授权、审批、凭据代理和租户隔离；
- 结果、轨迹、安全、成本和生产评测；
- 发布、灰度、版本共存、回滚、灾备和删除传播；
- Runtime Adapter、Provider Adapter 和企业能力 Adapter；
- 可选的 Experience 聚合、Evolution Trigger、AgentGenome、Mutation、Candidate、Lineage 和 EvolutionRun；
- 对自我改进的 Token/金额/时间/候选/代数预算以及明确停止条件；
- 多种可替换 Evolution Strategy，包括 LLM-guided sparse mutation、Genetic/Evolutionary Search、Bayesian Optimization、RL、Population Search 和 Human-guided Evolution。

## 4. 非目标

UEAF 不负责：

- 替企业制定业务规则、风险偏好或合规结论；
- 承诺模型输出绝对正确；
- 将所有框架内部图、节点或消息统一成最低公分母 DSL；
- 为不支持幂等或查询状态的外部系统承诺 exactly-once；
- 默认启用无限自治、多 Agent 网络、无限长期记忆或无限递归自改；
- 允许正在运行的 Agent 原地修改当前 `ReleaseManifest`；
- 允许 Candidate 修改自身评测标准、保留集答案、发布权、预算执行器或权限根；
- 将 Genetic Algorithm 规定为唯一或默认的自我进化算法；
- 强制绑定某个模型厂商、云平台、数据库或向量库。

## 5. 目标用户和责任

| 角色 | 主要责任 |
|---|---|
| 平台团队 | 运行外壳、控制面、数据面、Adapter、Evolution Plane 基础设施和 SLO |
| Agent 应用团队 | AgentDefinition、PromptContract、工具需求、业务验收、评测集和允许进化的 Gene 范围 |
| 业务系统团队 | 权威业务事实、动作幂等、状态查询、补偿和下游收据/权威观察；模块 05 将其规范化为 ActionReceipt |
| 安全团队 | 身份 Profile、策略、审批规则、凭据、安全门禁和 Governance Kernel 边界 |
| 数据治理团队 | 数据分类、用途、驻留、保留、删除、法律保留及 Experience 可持久化范围 |
| SRE | 容量、告警、故障响应、发布、恢复、灾备演练及 Evolution 运行成本/SLO |
| 质量治理团队 | EvalCase、评分器校准、QualityGateDecision、保留集、Evolution EvaluationSuite 和豁免管理 |
| Evolution Owner | Trigger 阈值、EvolutionBudget、Strategy Registry、Lineage、停止条件和 Candidate 提交治理 |

## 6. 一致性 Profile

UEAF 通过分级 Profile 控制采用成本。

### 6.1 Core Profile

必须提供：RequestEnvelope、PrincipalContext、Task/Run、PromptContract、ModelInvocation、ToolIntent、明确终态、Trace 和基础 Eval。

适用于无高风险副作用的短任务。

### 6.2 Durable Profile

在 Core 基础上增加：事件日志、Checkpoint、队列、租约、暂停恢复、HumanTask、取消、幂等和 unknown 对账。

适用于长任务和异步依赖。

### 6.3 Enterprise Profile

在 Durable 基础上增加：多租户、PDP/PEP、Approval、Credential Broker、Audit、RAG ACL、Memory 治理、ReleaseManifest、评测门禁和 SLO。

适用于正式企业生产环境。

### 6.4 Regulated Profile

在 Enterprise 基础上增加：独立租户 Cell、客户管理密钥、WORM 审计、数据驻留、职责分离、法律保留、恢复证明和强制人工门禁。

适用于金融、医疗、政务等受监管场景。

### 6.5 Evolution Extension Profile

这是覆盖在 Enterprise 或 Regulated 之上的可选扩展，而不是替代前述 Profile。至少增加：

- `EvolutionTrigger`、`EvolutionExperience`、`EvolutionLesson`；
- `AgentGenome`、`MutationProposal`、`CandidateRelease`、`FitnessRecord`、`LineageGraph`；
- `EvolutionRun`、`EvolutionBudget` 与停止条件；
- Subject/Builder/Judge/Release Authority 职责分离；
- Governance Kernel 不可由同一递归链自主修改；
- Active Evolution Working Set 上限与 Experience Consolidation；
- 候选复用模块 08/07/09 的质量、安全、生产和发布门禁。

## 7. 产品原则

1. 确定性控制包围概率性推理。
2. 统一企业边界，不强行统一 Runtime 内部实现。
3. 一个事实只有一个语义所有者。
4. 可见能力与执行权限分离。
5. 发现、信任、授权和执行是不同阶段。
6. 上下文是临时、可复现的受控视图。
7. 长期记忆是受治理数据产品。
8. 默认单 Agent，按证据引入多 Agent。
9. 副作用使用 effectively-once 和可对账语义。
10. 版本、证据、风险和回滚共同决定发布。
11. 自我进化只产生 Candidate，不原地修改当前生产 Release。
12. Experience 不等于 Prompt；原始历史首先结构化、聚合、压缩，再按需进入模型。
13. 没有有效 Trigger 时不持续消耗强模型 Token 进行自我反思。
14. 能确定性评测的维度优先使用确定性/统计 Evaluator。
15. 能力提升必须和 Token、费用、延迟、复杂度、回归和安全一起评估。
16. 历史可以增长，但 Active Working Set 必须有界。
17. Genetic Algorithm 是可替换 Evolution Strategy，而不是 UEAF 自我进化的定义。
18. Governance Kernel 是递归链外的稳定参照。

## 8. 成功标准

UEAF 的实现至少应证明：

- 两个测试租户无法通过数据库、缓存、向量索引、队列、日志或工件互相访问数据；
- 重复请求和重复消息不会产生重复业务副作用；
- 过期租约持有者不能提交状态或执行权；
- Tool 超时进入 unknown/reconciling，而不是自动判定失败；
- 暂停恢复重新验证身份、策略、版本和在途副作用；
- 每次模型调用可还原 Prompt、模型路由和 ContextManifest；
- 每个高风险动作可还原身份、策略、审批和 ActionReceipt；
- 不安全或退化版本能够被发布门禁自动阻断；
- 删除能够传播到派生索引、缓存、供应商状态和备份恢复流程；
- 更换 Runtime Adapter 不改变 UEAF 业务契约和审计语义；
- 没有 EvolutionTrigger 时不会对每个生产任务追加演化模型调用；
- Production Agent 不能修改自身当前 ReleaseManifest；
- Candidate 不能读取保留集答案、篡改自身 Eval 或提升自身 EvolutionBudget；
- EvolutionRun 可以因平台期、预算耗尽、无有效候选、安全阻断或人工停止而确定终止；
- 大量历史 Experience 不会线性扩大 Active Evolution Context；
- 同一 Candidate 的质量提升与 Token、费用、延迟、复杂度和安全差异可同时还原；
- GA 与至少一种非 GA Evolution Strategy 可以通过相同规范契约替换。
