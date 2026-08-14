# 上下文、RAG 与记忆

## 1. 定位

本模块把分散的会话历史、任务状态、企业知识、业务事实引用和受治理记忆，转换为一次模型调用可验证、可追溯、最小充分的上下文。它是 `ContextManifest`、`EvidencePack`、`MemoryCandidate` 与 `MemoryRecord` 的语义治理域；02 Agent Runtime 发起构建请求并消费引用，不拼装或持久化私有上下文副本。

模块必须同时解决四个问题：调用者是否有权看到候选内容、候选内容是否适合当前用途、哪些内容在预算内最有价值、跨会话信息是否允许被长期保存。权限过滤必须先于相关性排序；未经授权的文档不得进入排序候选集、缓存或调试输出。

```text
02 ContextBuildRequest
  -> 身份/租户/用途校验
  -> 授权范围下推到数据源
  -> 召回获授权候选
  -> 相关性/新鲜度/可信度排序
  -> EvidencePack + Memory 召回
  -> Token 与风险预算装配
  -> ContextManifest
  -> 02 引用 -> 03 编译 ModelInvocation
```

### 1.1 非职责

- 不拥有根 `TaskState`、`RunRecord`、Turn 或 Run 终态；这些属于 02。
- 不编译系统 Prompt、不调用模型、不解释 `StructuredDecision`；这些属于 03 与 02。
- 不授权或执行工具，不将检索结果当作执行许可；副作用统一进入 05。
- 不把模型摘要、搜索命中或用户陈述自动升级为权威业务事实。
- 不让向量数据库、搜索引擎或模型 Provider 的会话状态成为语义所有者。
- 不把 RAG 索引当作原始记录系统；删除、保留和权威版本仍由来源系统约束。

## 2. 职责

- 归一 `ContextBuildRequest` 与 `QueryIntent`，校验 tenant、principal、purpose、Release 和预算绑定。
- 按数据源能力把租户、主体、资源、地域、用途和时间范围下推到检索层。
- 在授权后执行混合召回、去重、排序、重排和证据聚合。
- 为每条证据保存来源、版本、权限、有效期、可信度和引用定位。
- 根据 Prompt 槽位、Token 预算和优先级构建不可变 `ContextManifest`。
- 管理 Memory 候选生成、同意、验证、冲突、更正、过期、删除和使用审计。
- 对索引延迟、来源不可用、权限变化和缓存失效提供显式降级语义。
- 输出选择与排除原因，支持审计、评测和上下文质量诊断。

## 3. 子组件

| 组件 | 职责 | 关键约束 |
| --- | --- | --- |
| Context API | 接收构建、证据查询和记忆命令 | 只接受可信内部身份；强制公共元数据 |
| Context Builder | 装配本次调用的 `ContextManifest` | 唯一 State Writer；不复制正文到 Run 状态 |
| Query Planner | 将目标转为一个或多个 `QueryIntent` | 计划是派生对象，不改变 `TaskState` |
| Authorization Filter | 计算并下推可见资源集合 | 必须在召回排序前生效；失败关闭 |
| Source Registry | 管理来源、权威级别、地域、保留和连接器版本 | 未登记来源不得进入生产上下文 |
| Retrieval Router | 选择关键词、向量、图、SQL/API 或组合检索 | 不得绕过来源 ACL |
| Ranker/Reranker | 在获授权候选内按相关性、新鲜度、可信度排序 | 不能重新引入已过滤候选 |
| Evidence Assembler | 生成 `EvidencePack`、引用和缺失摘要 | 证据正文与元数据分离存储 |
| Token Budgeter | 按槽位和风险裁剪、压缩、去重 | 安全规则与关键否定不得静默截断 |
| Memory Service | 管理 `MemoryCandidate` 与 `MemoryRecord` 生命周期 | 只有受治理记录可跨会话召回 |
| Context Cache | 缓存授权范围内的查询与装配结果 | 键包含 tenant、scope、purpose、版本 |
| Indexing Pipeline | 从权威来源增量索引、重建、删除传播 | 索引是投影，不是权威记录 |

## 4. Canonical 契约

所有线级对象必须携带 `contract_version`、`tenant_id`、`correlation_id`、`trace_id`、`created_at` 和 `integrity_ref`；敏感对象还必须携带 `classification`、`region`、`purpose` 与 `retention_policy_ref`。

### 4.1 输入：`ContextBuildRequest`

| 字段 | 规则 |
| --- | --- |
| `context_request_id` | 全局唯一；重试保持相同幂等身份 |
| `task_id` / `run_id` / `turn_id` | 必须引用 02 中存在且未越权的对象 |
| `principal_context_ref` | 绑定当前代表主体与委托链 |
| `task_state_ref` | 只读引用并包含 revision；不得接收隐式内存对象 |
| `prompt_contract_ref` | 声明目标上下文槽位、信任分区和上限 |
| `release_manifest_ref` | 冻结来源、连接器和策略兼容范围 |
| `goal` / `query_hints` | 目标与可选确定性查询提示 |
| `purpose` | 必须与授权和来源允许用途匹配 |
| `source_constraints` | 允许/禁止来源、时间、新鲜度、地域、语言 |
| `memory_scope` | `none/session/subject/team/tenant` 中获准范围 |
| `budget_slice` | Token、延迟、查询次数和费用上限 |
| `citation_requirement` | 是否逐项引用、最低新鲜度和证据数量 |
| `known_context_refs` | 可复用引用；仍需重新验证授权和有效期 |

相同 `context_request_id` 与不同规范化输入哈希冲突时必须拒绝，不能覆盖旧结果。

### 4.2 `QueryIntent`

`QueryIntent` 是一次受控证据查询，最小字段为：

- `query_intent_id`、`task_id`、`run_id`、`principal_context_ref`；
- `query`、`purpose`、`source_constraints`、`authorization_scope_ref`；
- `freshness_requirement`、`citation_requirement`、`budget_slice`；
- `normalized_query_hash`、`policy_snapshot_ref`、`expires_at`。

自然语言查询只能表达信息需求，不能扩大授权范围。检索连接器必须同时接收授权过滤器；不支持可靠下推的来源只能通过已完成行/文档级过滤的受控投影接入。

### 4.3 输出：`EvidencePack`

| 字段 | 规则 |
| --- | --- |
| `evidence_pack_id` | 不可变版本标识 |
| `query_intent_ref` | 指向产生它的查询 |
| `principal_context_ref` | 指向本次授权检索使用的主体上下文 |
| `items` | 每项含来源、版本、位置、内容引用/最小片段、权限范围、信任标签和引用句柄 |
| `authorization_proof_refs` | 证明每项在查询时可见 |
| `source_versions` | 用于重放、缓存和新鲜度判断 |
| `coverage` | 已覆盖问题、缺失问题和矛盾集合 |
| `conflicts` | 来源间不能静默消解的冲突及引用 |
| `freshness` | 各来源新鲜度、水位和是否满足需求 |
| `selection_policy_ref` | 授权后召回、排序与证据选择策略版本 |
| `citation_map` | 结果片段到稳定来源定位的映射 |
| `expires_at` | 超时后不得直接复用于新调用 |
| `omission_summary` | 因授权、预算、过期、冲突被排除的统计，不泄露内容 |

`EvidencePack` 证明“在给定时间、主体和用途下观察到什么”，不证明内容必然为真，也不替代 `BusinessFactRef` 指向的权威系统。

### 4.4 输出：`ContextManifest`

`ContextManifest` 由本模块的 Context Builder 为 02 构建；02 只请求、引用并在运行记录中关联它。它是本次模型调用实际上下文的不可变清单，不是正文副本。

最小字段：

- `context_manifest_id`、`run_id`、`turn_id`；
- `sections`：本次实际装入的槽位/分区，每项记录内容引用、来源版本、用途、Token、选择原因；
- `source_refs`：所有 section 可追溯的来源、Evidence、Memory、BusinessFact 与 Artifact 引用；
- `policy_snapshot_ref`：本次授权、用途、数据处理和选择策略快照；
- `budget_before` / `budget_after`：装配前与装配后的 Token/时间/费用预算；
- `selection_decisions`：每个候选的选择、降级或排除决定及稳定理由；
- `omissions`：因权限、过期、预算、冲突或风险未装入的安全摘要；
- `compression_records`：每次压缩的输入引用、规则、输出引用、损失与完整性；
- `trust_labels`：各 section 的权威、审核、用户、模型派生或外部不可信标签；
- `integrity_ref`：上述内容与来源版本的完整性证明。

作为可选关联字段，Manifest 可以包含 `task_id`、`principal_context_ref`、`purpose`、`prompt_contract_ref`、`task_state_ref/revision`、`authorization_proof_refs`、`created_at` 和 `expires_at`；这些字段不得替代上述核心最小字段。正文保存在受控 Artifact/Source Store，`sections` 与 `source_refs` 只保存最小片段或引用。

03 在编译 `ModelInvocation` 前必须验证 tenant、principal、purpose、PromptContract、有效期和完整性。任何内容变化都必须生成新的 manifest，不得原地修改。

### 4.5 Memory 输入与输出

`MemoryCandidate` 由 Runtime 或确定性提取器提交，至少包含：`candidate_id`、`subject_ref`、`source_refs`、`purpose`、`scope_requested`、候选内容引用、`classification`、`confidence`、`consent_requirement`、`retention_hint` 和完整性证明。

候选不是可召回记忆。Memory Service 完成以下治理后才能生成 `MemoryRecord`：

1. 验证来源、主体、用途和是否允许持久化；
2. 识别秘密、凭证、受监管数据和禁止记忆类别；
3. 验证同意、合法用途、保留与地域策略；
4. 与现有记录去重、冲突检测，并关联更正或替代链；
5. 设定 scope、有效期、置信度和每次使用审计策略；
6. 写入权威 Memory Store 后再更新检索投影。

`MemoryRecord` 必须包含核心规范定义的 subject、scope、source、consent、validity、status、supersedes 与 deletion 字段。`MemoryResolution` 返回 `promoted/rejected/needs_review`、理由码和生成的 record 引用；它不是 Run 终态决定。

## 5. 主流程

### 5.1 上下文构建

1. 02 提交 `ContextBuildRequest`，04 验证 Run、TaskState revision、Principal、tenant、purpose、Release 和预算。
2. Query Planner 形成一个或多个 `QueryIntent`，并为每个查询固定授权策略快照。
3. Authorization Filter 计算可见资源边界并下推到来源或受控投影。
4. Retrieval Router 只在获授权集合内召回；连接器回传资源版本和 ACL 证明。
5. 去重、排序和重排仅处理已授权候选，综合相关性、新鲜度、来源权威度和多样性。
6. Evidence Assembler 生成 `EvidencePack`，显式记录冲突、覆盖缺口、过期内容和安全省略。
7. Memory Service 按 subject、scope、purpose、consent 和有效期召回受治理记录；被删除或已替代记录不得命中。
8. Token Budgeter 按 PromptContract 分区装配，优先保留系统约束、任务目标、确认事实、关键否定和必要引用。
9. Context Builder 写入不可变 `ContextManifest` 和 outbox 事件，再把引用返回 02。
10. 03 读取引用并再次校验，不得使用未登记的旁路上下文。

### 5.2 索引与删除传播

1. Source Registry 接收权威来源的变更事件或受控增量扫描。
2. Indexing Pipeline 验证租户、版本、分类和区域，生成可重建投影。
3. 删除、权限收回和法律保留事件的优先级高于新增索引；缓存和向量/关键词投影同步失效。
4. 若失效传播超出 SLO，受影响来源必须被隔离或查询失败关闭，不能以旧 ACL 继续服务。
5. 重建完成后通过样本 ACL、计数、版本水位和删除证明校验再切流。

### 5.3 Memory 治理

Memory 写入与 Run 完成解耦。除非任务完成条件明确要求持久化记忆，记忆晋升失败不应把已经完成的业务动作改为 Run failed，但必须形成可观察告警和重试记录。用户更正必须创建新版本并使旧记录 `superseded`；删除要求必须同时覆盖权威 Store、搜索投影、缓存、备份策略和使用审计证明。

## 6. 状态与唯一所有权

| 对象 | 语义所有者 / State Writer | 本模块边界 |
| --- | --- | --- |
| `TaskState` | 02 Task Domain | 只读指定 revision；不写入 Memory 代替任务状态 |
| `RunRecord` / Turn | 02 Runtime Domain | 只关联 run/turn；不提交根终态 |
| `ContextManifest` | 04 Context Domain / Context Builder | 唯一创建者；不可变版本 |
| `EvidencePack` | 04 Evidence Domain / Evidence Assembler | 唯一创建者；来源系统仍拥有原始事实 |
| `MemoryCandidate` | 04 Memory Domain / Memory Service | 管理评审生命周期；提交方不能直接晋升 |
| `MemoryRecord` | 04 Memory Domain / Memory Service | 管理版本、过期、更正、删除和使用审计 |
| `BusinessFactRef` 指向内容 | 外部权威业务系统 | 04 只保存引用和观察版本 |
| 索引/缓存 | 04 的 Physical Store/Projection | 可删除重建；不取得语义所有权 |

`ContextManifest` 不具有可变状态机。其状态通过新版本、过期或撤销投影表达。Memory 状态至少覆盖 `candidate/pending_review/active/superseded/expired/deleted/rejected`，其中终态和转换必须由 Memory Service 以 revision/CAS 提交。

## 7. 多租户与安全

- tenant、region、principal、delegation、purpose 和 authorization scope 必须贯穿查询、缓存、索引、Evidence、Manifest 与 Memory。
- 权限过滤必须在检索和排序前完成；不得先做全局 Top-K 再过滤，也不得在错误、计数或延迟中泄露不可见资源存在性。
- 缓存键至少包含 tenant、授权范围摘要、purpose、查询摘要、来源版本、策略版本和地域；禁止只按自然语言 query 跨主体复用。
- RAG、Memory、附件和历史模型输出均属于不可信数据，不能改变系统指令、工具权限或输出 Schema。
- 连接器凭证使用服务身份和最小权限，按 tenant/region 隔离；原始凭证不得进入 Evidence、Manifest、日志或 Prompt。
- 敏感正文应保存在受控 Artifact Store，Manifest 只存引用；调试视图默认脱敏并执行二次授权。
- Memory 需要主体隔离、用途限制、同意撤销、数据最小化、保留期和可验证删除；团队/租户级记忆必须有更高审查阈值。
- 对知识来源的 Prompt Injection 内容进行标记和隔离，但安全分类器不得替代访问控制。

## 8. 故障、降级与恢复

| 场景 | 处理 | 禁止行为 |
| --- | --- | --- |
| Principal、tenant 或 purpose 不一致 | 返回结构化 `forbidden/invalid`，不查询来源 | 以空 ACL 当作全量访问 |
| 来源不可用 | 按必需性返回 `partial/unavailable`，记录 coverage gap | 静默使用未知时效缓存 |
| ACL 服务不可用 | 失败关闭或只使用可证明的本地授权快照 | 先检索后补权限 |
| 索引水位落后 | 标记 freshness，必要时回源或拒绝 | 把旧索引包装成实时事实 |
| 排序器/Embedding 不可用 | 在获授权集合内退化到确定性关键词排序 | 重新扩大候选范围 |
| Token 超限 | 按声明策略去重/压缩并生成 omission summary | 截断关键否定、授权条件或引用 |
| Manifest 过期/损坏 | 重建新版本 | 原地修改或跳过完整性校验 |
| Memory 冲突 | 隔离为 needs_review 或记录并列观点 | 最后写入胜出覆盖确认记录 |
| 删除传播失败 | 隔离记录和来源、告警并持续重试 | 继续向新调用召回 |

恢复时以权威来源版本、Memory Store 和事件水位重建投影；重建任务必须可暂停、分片和校验。重复的 `ContextBuildRequest` 可返回同一不可变结果，前提是 Principal、授权、来源版本、策略和有效期均未变化；否则生成新 manifest。

## 9. 观测指标

核心指标：

- `context_build_latency_ms{tenant,release,status}` 与各阶段耗时；
- `retrieval_candidates_authorized_total`、`retrieval_candidates_ranked_total`；
- `acl_filter_denied_total`、`acl_filter_error_total`，不得携带敏感资源标签；
- `evidence_coverage_ratio`、`citation_valid_ratio`、`stale_evidence_ratio`；
- `context_tokens_selected`、`context_tokens_omitted`、槽位利用率；
- `context_cache_hit_ratio`，按授权摘要隔离聚合；
- `source_index_lag_seconds`、`deletion_propagation_lag_seconds`；
- `memory_candidate_promoted/rejected/review_total`、`memory_recall_use_total`；
- `memory_conflict_total`、`memory_expiry_lag_seconds`、`memory_deletion_slo_breach_total`。

每个 trace 至少关联 context_request、query_intent、evidence_pack、manifest、来源版本和策略快照。正文、查询秘密和不可见资源标识不得成为普通指标标签。

## 10. 可替换端口

| 端口 | 语义 | 可能适配器 |
| --- | --- | --- |
| `ContextBuildPort` | `ContextBuildRequest -> ContextManifest` | 进程内模块、独立 Context Service |
| `EvidenceQueryPort` | `QueryIntent -> EvidencePack/拒绝` | Elasticsearch/OpenSearch、向量库、图检索、企业搜索 |
| `AuthorizationFilterPort` | 生成来源可执行过滤器和授权证明 | 07 Policy Service、数据源原生 ACL |
| `KnowledgeSourcePort` | 版本化读取、变化流、删除和授权查询 | 文档库、数据库、对象存储、SaaS API |
| `RankingPort` | 获授权候选的排序/重排 | 确定性排序、交叉编码器、Provider reranker |
| `ArtifactReadPort` | 受控读取正文与附件 | 对象存储、内容服务 |
| `MemoryPort` | candidate、recall、correct、expire、delete | 关系库+索引、专用 Memory Service |
| `ConsentPort` | 校验主体同意与撤销 | 企业同意管理系统 |
| `ContextCachePort` | 授权感知缓存与失效 | Redis、本地加密缓存 |
| `IndexAdministrationPort` | 水位、重建、隔离和验证 | 流处理、批处理平台 |

任何适配器都必须通过 UEAF 契约测试：租户隔离、ACL 先过滤、版本追踪、删除传播、超时取消、幂等和错误归一。

## 11. 配置项

| 配置 | 说明 | 默认原则 |
| --- | --- | --- |
| `allowed_source_types` | Release 允许的数据源类型 | 显式 allowlist |
| `required_source_sets` | 某类任务不可缺少的来源 | 缺失则 incomplete/failed closed |
| `retrieval_strategy` | hybrid/keyword/vector/graph/API | 按用途和数据分类选择 |
| `top_k_per_source` / `rerank_k` | 召回与重排上限 | 受预算和来源限制 |
| `freshness_requirements` | 来源最大陈旧时间 | 关键业务事实更严格 |
| `context_token_budget` | 总量和槽位配额 | 安全与任务关键槽位优先 |
| `manifest_ttl` / `evidence_ttl` | 结果有效期 | 不超过授权和来源快照有效期 |
| `cache_policy` | TTL、加密、scope、失效策略 | 禁止跨授权摘要共享 |
| `memory_allowed_scopes` | 允许的 Memory 范围 | 默认 session 或不持久化 |
| `memory_retention` | 分类对应期限 | 最小化并可删除 |
| `memory_review_thresholds` | 晋升/人工复核阈值 | 团队与租户级更高 |
| `deletion_slo` | 删除传播目标 | 超时触发隔离 |

配置必须版本化并被 `ReleaseManifest` 引用；生产运行中不得通过未审计环境变量改变访问范围或 Memory 策略。

## 12. 验收标准

- 所有检索路径均证明权限过滤发生在召回排序之前；测试可构造高相关但无权资源且永不进入候选、缓存和日志。
- 04 的 Context Builder 是 `ContextManifest` 唯一写者；02 只请求和引用，03 只验证和消费。
- 每个 Manifest 可追溯到 TaskState revision、PromptContract、Principal、purpose、Evidence、Memory、来源版本和选择/排除理由。
- `EvidencePack` 明确区分观察证据与权威 `BusinessFactRef`，来源冲突不会被静默合并。
- Runtime 只能提交 `MemoryCandidate`；候选通过同意、分类、冲突、有效期和用途治理后才成为 `MemoryRecord`。
- Memory 的更正、过期、撤回和删除能在配置 SLO 内传播到 Store、索引与缓存，并产生证明。
- tenant、scope、purpose 或策略不同的请求不会命中同一不安全缓存项。
- 来源不可用、索引陈旧、Token 超限和授权服务故障都有确定性失败/降级结果，不产生“看似完整”的上下文。
- 关键指标、trace 与审计引用完整，同时不泄露正文、凭证或不可见资源标识。
- 至少通过租户越权、Prompt Injection、删除传播、索引回滚、缓存投毒、重复请求和灾难重建演练。
