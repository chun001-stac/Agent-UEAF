# UEAF V1 实施规范入口

Architecture Generation: `V1`  
Implementation: `Current`

本目录不是新的架构层，而是把既有 V1 规范编译成可由 Codex/工程团队直接实现和验收的工程合同。

## 1. 文档顺序

1. [V1 机器 Schema 包规范](01-V1机器Schema包规范.md)  
   把 Canonical Object、ContractMeta、Profile、Mutation Patch、Command/Event/Error 转成机器 Schema。

2. [V1 API、Port 与事件契约](02-V1-API端口与事件契约.md)  
   固定调用方向、核心 Port 名称/方法、错误、幂等、timeout/retry、Event owner 和版本。

3. [V1 持久化与事务映射](03-V1持久化与事务映射.md)  
   固定 authority/projection、CAS、fencing、outbox、Action/Evolution/Release 事务顺序。

4. [V1 验收与一致性测试规范](04-V1验收与一致性测试规范.md)  
   注册并定义 `CON/RUN/ADP/PRM/CTX/RAG/ACT/SEC/EVD/EVAL/REL/EVO/REP/MUT/OBJ/STR/ETH/P0-SCH/P0-PORT` Test IDs。

5. [V1 参考实现与 Codex 开发规范](05-V1参考实现与Codex开发规范.md)  
   固定 Python Reference Profile、Phase 0..6、仓库结构和 Codex 决策边界。

6. [V1 文档一致性审计报告](06-V1文档一致性审计报告.md)  
   记录全仓 P0/P1/P2 冲突、已修项、防回归 `CON-*` 和 Code-Ready Gate。

7. [V1 P0 能力实现细化规范](07-V1-P0能力实现细化规范.md)  
   在不新增 Canonical Object/模块/状态机/公共 enum 的前提下，细化 Prompt、Context、RAG、Tool、Eval 和 Security。

8. [V1 P0 能力验收扩展](08-V1-P0能力验收扩展.md)  
   为 P0 默认算法、所有权、失败语义、Machine Schema、typed Port 和 failure-injection 增加可执行验收。

## 2. 规范优先级

```text
核心规范
> 总体设计
> ADR
> 功能模块
> 实施规范
> 参考架构
```

本目录只能细化/机器化上层语义，不能覆盖它们。

07/08 只固定 V1 Reference Implementation 的 P0 实施默认值和测试，不得：

```text
新增 Canonical Object
新增模块或服务
新增公共 State/Disposition/Decision enum
改变 Semantic Owner/State Writer
缩减 01 的 mandatory Schema 列表
改变 02 的核心 Port 方法语义
把 RAG/Judge/Quality Gate 变成 Release Authority
```

## 3. Codex 首次进入仓库应读取

```text
README.md
AGENTS.md
docs/00-总览/06-UEAF架构代际与实施范围.md
docs/01-核心规范/01..05
docs/01-核心规范/07..09
docs/05-实施规范/README.md
docs/05-实施规范/06-V1文档一致性审计报告.md
```

然后读取当前任务相关：

```text
功能模块
V1 Current ADR
对应实施规范
必要参考架构
```

若任务涉及 Prompt/Context/RAG/Tool/Eval/Security，还必须读取：

```text
docs/05-实施规范/07-V1-P0能力实现细化规范.md
docs/05-实施规范/08-V1-P0能力验收扩展.md
```

ADR-009、ADR-011 和其他 V2/V3 内容只用于确认 Future 边界，不得推导 Current 实现。

## 4. Code-ready 路径

```text
Normative V1 Docs
  -> audited convergence rules
  -> Machine Schema
  -> API / Port / Event
  -> Persistence / Transaction
  -> P0 audited implementation defaults
  -> registered Test IDs + acceptance/failure scenarios
  -> Reference Implementation Profile
  -> Codex implementation phases
```

## 5. 审计后关键边界

- 所有跨模块持久对象 = `ContractMeta + domain fields`；
- V1 只有一套核心 `EventEnvelope`；
- public event name = `ueaf.<domain>.<past_tense_fact>`；
- API error = `ProblemDetail`，Port error = `PortResult<T>/PortError`；
- RuntimeAdapter/ContextBuildPort/TelemetryPort 只用核心 SPI；
- `PrincipalContext` 只有核心一套字段；
- Task risk enum 与 Evolution `RepairLevel` 分离；
- `ReleaseManifest` 使用 plural version-set 字段；
- Evolution Canonical Object 只有五个；
- `Mutation -> GenomeManifest candidate -> ReleaseCandidate` 不可跳步；
- action identity 在 Policy 前稳定，副作用在 Policy/Approval/Reservation 后执行；
- Action 结果只用既有 `succeeded/failed/unknown`，unknown 先 reconciliation；
- PDP 是 `PolicyDecision` 唯一 owner，本地规则快照不能形成第二个 PDP；
- Module 04 是 `ContextManifest` 唯一写者，Module 03 只验证和映射；
- `ModelRouteSnapshot` 在 route-specific token 计算前冻结；
- EvalResult 来自冻结 EvalRun/Isolated Runner，不由普通生产 Request 直接签发；
- RAG benchmark/Judge/Quality Gate 不拥有 `ReleaseDecision`；
- R5 Governance 不进入同一自动递归链；
- Candidate/Eval/Budget/Release 复用既有语义；
- 正常 Evidence Collection/Trigger Candidate 路径目标 0 LLM Token；
- 实现细节优先落入版本化 config/policy/test，不横向新增 V1 语义表面积。

## 6. Reference Implementation Default

```text
Python 3.12+
FastAPI
Pydantic v2 + canonical JSON Schema
PostgreSQL 16+
SQLAlchemy 2.x / Alembic
NATS JetStream
OpenTelemetry
S3-compatible / local MinIO
LangGraph Adapter #1
OpenAI Agents SDK read-only Adapter #2
deterministic fake/recorded model in CI
pytest / Ruff / mypy / GitHub Actions
```

这是首个参考实现选择，不是 UEAF 供应商绑定。

## 7. 当前状态

```text
Documentation Code-Ready: PASS
Architecture Feature Freeze: ACTIVE
Phase 0 implementation: IN PROGRESS / partial skeleton exists
P0 implementation deepening: AUDITED DOCUMENTATION READY
P0 machine implementation: PENDING
```

当前仓库已有部分 `schemas/`、`src/`、`tests/`、migration harness、CI 和本地基础设施骨架。下一步应按 01/02/03/04/07/08 继续机器化 Model、Context/RAG、Tool、Security 和 Eval，并实现 typed Port、failure-injection 和隔离 vertical slices，而不是继续主动发散 V1 架构。
