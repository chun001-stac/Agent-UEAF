# UEAF 产品定义

当前架构代际：`V1`  
长期架构：`V2 / V3`  
代际边界见：[UEAF 架构代际与实施范围](06-UEAF架构代际与实施范围.md)

## 1. 产品定位

UEAF 是企业 Agent 的统一架构与治理底座，由六类能力构成：

1. **规范层**：定义身份、请求、任务、运行、上下文、动作、证据、发布与演化契约。
2. **运行外壳**：在现有 Agent Runtime 外提供准入、状态、预算、工具执行和恢复控制。
3. **控制面**：管理 Agent、Prompt、模型、能力、策略、评测和发布版本。
4. **治理面**：管理权限、审计、数据生命周期、评测、SLO 和风险。
5. **开发者面**：提供 SDK、CLI、本地运行、测试夹具、Adapter SPI 和调试能力。
6. **演化面**：V1 把通过 Trigger Gate 的生产问题或机会转化为受预算、评测、职责分离和发布治理约束的 Candidate；V2/V3 再扩展到生态共同进化与 Meta Evolution。

UEAF 的产品价值不是提供另一种 Agent Loop，而是让不同 Agent Runtime 在同一企业契约下安全运行、可比较发布、可持续替换，并在不破坏治理边界的前提下形成可验证改进。

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
| 发现异常就立即自改导致版本震荡 | 分离 Operational Response 与 Evolution Response；异常先分级，Trigger Gate 通过后才创建 EvolutionTrigger |
| 严重事故不能等待自我进化 | P0/P1 先复用现有 rollback/fallback/isolation/kill 等安全与运行机制止血 |
| 系统正常时缺少主动优化 | Opportunistic Trigger 可评估新模型、新 Tool、新 Provider、成本或新业务机会 |
| 生产经验只能沉淀为日志 | V1 Evolution Kernel 使用 Trigger + bounded EvolutionRun + Mutation 形成候选 |
| 自我改进容易无限消耗 Token | Trigger Gate、事件驱动、Sparse Mutation、有界 Working Set、既有 Budget Domain 和停止条件 |
| 演化对象不断增加导致架构臃肿 | Minimum Semantic Surface：优先复用 existing object + ref / Projection / metadata |
| 未来生态设计会拖重当前实现 | 使用 V1/V2/V3 代际隔离当前与未来架构 |

## 3. V1 当前范围

UEAF V1 MUST 覆盖：

- 同步、流式和异步 Agent 请求；
- 单 Agent 运行和可恢复工作流；
- 模型、Prompt、结构化输出和上下文构造；
- RAG、会话连续性和受治理长期记忆；
- 本地工具、企业 API、MCP 和远程 Agent 能力；
- 身份委托、策略授权、审批、凭据代理和租户隔离；
- 结果、轨迹、安全、成本和生产评测；
- 发布、灰度、版本共存、回滚、灾备和删除传播；
- Runtime Adapter、Provider Adapter 和企业能力 Adapter；
- V1 Controlled Evolution Kernel：`EvolutionTrigger`、`EvolutionRun`、`GenomeManifest`、`MutationProposal`、`EvolutionAuthorityPolicy`；
- Operational Response 与 Evolution Response 分离；
- P0-P3 Trigger Priority、Reactive/Opportunistic Trigger、Trigger Gate、cooldown、novelty 和 expected-value 过滤；
- 复用模块 10 `ReleaseCandidate`、模块 08 Eval/Release、既有 Budget Domain；
- Sparse Mutation、Evaluator Funnel、有界 Active Working Set 和明确停止条件；
- `no_evolution_needed` 作为合法 EvolutionRun 终态。

V1 不要求 Species、Gene Pool、Population、Ecosystem Fitness 或 Meta Evolution 的独立实现。

## 4. V2/V3 长期范围

### V2 Planned：Adaptive Agent Ecosystem

计划包括：

- Species / Population / Elite；
- Gene Pool；
- Capability Transfer；
- Local + Ecosystem Fitness；
- Diversity / Monoculture Risk；
- Specialist 与生态级 Funnel Evaluation。

### V3 Research：Recursive Adaptive Ecosystem

研究方向包括：

- Meta Evolution；
- Evolution Strategy Evolution；
- Dynamic Niche / Species；
- Ecosystem Topology Evolution；
- Pareto Frontier；
- Evolution Debt / Systemic Risk；
- ModelEvolutionPort。

V2/V3 文档可以保留和继续细化，但不得被 V1 实现者解释为当前验收要求。

## 5. 非目标

UEAF 不负责：

- 替企业制定业务规则、风险偏好或合规结论；
- 承诺模型输出绝对正确；
- 将所有框架内部图、节点或消息统一成最低公分母 DSL；
- 为不支持幂等或查询状态的外部系统承诺 exactly-once；
- 默认启用无限自治、多 Agent 网络、无限长期记忆或无限递归自改；
- 让 Evolution Plane 取代现有 Incident Response、Safety、SRE、Rollback 或 Tool containment；
- 允许正在运行的 Agent 原地修改当前 `ReleaseManifest`；
- 允许 Candidate 修改自身评测根、保留集答案、发布权、预算执行器或权限根；
- 将 Genetic Algorithm 规定为唯一或默认的自我进化算法；
- 为 V2/V3 未被真实需求证明的对象提前建设独立服务、数据库或状态机；
- 强制绑定某个模型厂商、云平台、数据库或向量库。

## 6. 目标用户和责任

| 角色 | 主要责任 |
|---|---|
| 平台团队 | 运行外壳、控制面、数据面、Adapter、V1 Evolution Kernel 和 SLO |
| Agent 应用团队 | AgentDefinition、PromptContract、工具需求、业务验收、评测集和允许 Mutation 范围 |
| 业务系统团队 | 权威业务事实、动作幂等、状态查询、补偿和下游收据 |
| 安全团队 | 身份 Profile、策略、审批规则、凭据、安全门禁、P0/P1 containment 和 Governance Kernel 边界 |
| 数据治理团队 | 数据分类、用途、驻留、保留、删除、法律保留和演化证据可用范围 |
| SRE | 容量、告警、P0/P1 运行响应、发布、恢复、灾备及演化成本/SLO |
| 质量治理团队 | EvalCase、评分器校准、QualityGateDecision、保留集和豁免管理 |
| Evolution Owner | Trigger Gate/阈值、P0-P3 策略、cooldown、novelty、expected-value、Mutation Strategy、权限 Profile、停止条件和 Candidate 提交治理 |

## 7. 一致性 Profile

### 7.1 Core Profile

必须提供：RequestEnvelope、PrincipalContext、Task/Run、PromptContract、ModelInvocation、ToolIntent、明确终态、Trace 和基础 Eval。

### 7.2 Durable Profile

在 Core 基础上增加：事件日志、Checkpoint、队列、租约、暂停恢复、HumanTask、取消、幂等和 unknown 对账。

### 7.3 Enterprise Profile

在 Durable 基础上增加：多租户、PDP/PEP、Approval、Credential Broker、Audit、RAG ACL、Memory 治理、ReleaseManifest、评测门禁和 SLO。

### 7.4 Regulated Profile

在 Enterprise 基础上增加：独立租户 Cell、客户管理密钥、WORM 审计、数据驻留、职责分离、法律保留、恢复证明和强制人工门禁。

### 7.5 V1 Evolution Extension Profile

这是覆盖在 Enterprise 或 Regulated 之上的可选扩展，至少增加：

- `EvolutionTrigger`；
- `EvolutionRun`；
- `GenomeManifest`；
- `MutationProposal`；
- `EvolutionAuthorityPolicy`；
- Signal/Opportunity Detection + Trigger Gate；
- P0-P3 Policy、Reactive/Opportunistic Trigger 和 cooldown；
- Active Working Set 上限；
- 既有 Budget Domain 中的演化预算切片；
- Subject/Builder/Judge/Release Authority 职责分离；
- 候选复用模块 10/08/07/09 的构建、评测、安全、生产和发布门禁。

Experience/Lesson、Fitness、Lineage、P0-P3 Policy 细节在 V1 可作为内部记录、Projection 或 Policy/Config，不要求成为新的 Canonical Object。

## 8. 产品原则

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
12. **异常不等于 Trigger，Trigger 不等于必须修改。**
13. 严重风险先止血，长期改变再走 Evolution。
14. 没有有效 Trigger 时不持续消耗强模型 Token 进行自我反思。
15. Trigger Gate 优先规则/统计/Projection，模型仅处理难以可靠判断的根因或价值。
16. 能确定性评测的维度优先使用确定性/统计 Evaluator。
17. 历史可以增长，但 Active Working Set 必须有界。
18. 搜索算法可替换；GA 不是 Evolution 的定义。
19. Governance Kernel 是递归链外的稳定参照。
20. **Minimum Semantic Surface**：能用既有对象 + ref / Projection / metadata 表达时，不新增 Canonical Object。
21. V1/V2/V3 分离当前实现和未来设计；未来能力不得反向拖重当前实现。

## 9. V1 成功标准

UEAF V1 至少应证明：

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
- P0/P1 严重问题可在 Evolution 之外立即 rollback/fallback/isolate/degrade/kill；
- 普通单次失败不会直接成为 EvolutionTrigger；
- Trigger Gate 能过滤证据不足、已恢复、不可修改、重复、低价值和 cooldown 中的问题；
- Opportunistic Trigger 可以在无故障时评估新模型/Tool/Provider/成本机会；
- 无 EvolutionTrigger 时不会对每个生产任务追加演化模型调用；
- Production Agent 不能修改自身当前 ReleaseManifest；
- EvolutionRun 可以以 `no_evolution_needed`、平台期、预算耗尽、无有效候选、安全阻断或人工停止终止；
- 大量历史不会线性扩大 Active Evolution Context；
- Candidate 复用现有 ReleaseCandidate/Eval/Release 语义，而不是复制第二套；
- 一个 `GenomeManifest` 可覆盖 V1 Agent/Skill/Tool/Workflow 的统一版本生命周期；
- V1 未为 V2/V3 概念预建独立 Species/GenePool/Meta-Evolution 基础设施。
