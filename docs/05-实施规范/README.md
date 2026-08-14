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
   把不变量转换为 `CON/RUN/ADP/ACT/RAG/SEC/EVD/EVAL/REL/EVO/REP/MUT/OBJ/STR/ETH` Test IDs。

5. [V1 参考实现与 Codex 开发规范](05-V1参考实现与Codex开发规范.md)  
   固定 Python Reference Profile、Phase 0..6、仓库结构和 Codex 决策边界。

6. [V1 文档一致性审计报告](06-V1文档一致性审计报告.md)  
   记录本轮全仓 P0/P1/P2 冲突、已修项、防回归 `CON-*` 和 Code-Ready Gate。

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

ADR-009 / ADR-011 和其他 V2/V3 内容仅用于确认 Future 边界，不得推导 Current 实现。

## 4. Code-ready 路径

```text
Normative V1 Docs
  -> audited convergence rules
  -> Machine Schema
  -> API / Port / Event
  -> Persistence / Transaction
  -> CON-* + domain Acceptance Tests
  -> Reference Implementation Profile
  -> Codex Phase 0
```

## 5. 审计后关键边界

- 所有跨模块持久对象 = `ContractMeta + domain fields`；
- V1 只有一套核心 `EventEnvelope`；
- public event name = `ueaf.<domain>.<past_tense_fact>`；
- 未登记的 Evolution lifecycle event 只能 internal；
- API error = `ProblemDetail`，Port error = `PortError`；
- RuntimeAdapter/ContextBuildPort/TelemetryPort 只用核心 SPI；
- `PrincipalContext` 只有核心一套字段；
- Task risk enum 与 Evolution `RepairLevel` 分离；
- `ReleaseManifest` 使用 plural version-set 字段；
- Evolution Canonical Object 只有五个；
- `Mutation -> GenomeManifest candidate -> ReleaseCandidate` 不可跳步；
- `outcome_unknown` 先 reconciliation；
- R5 Governance 不进入同一自动递归链；
- Candidate/Eval/Budget/Release 复用既有语义；
- 正常 Evidence Collection/Trigger Candidate 路径目标 0 LLM Token。

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
Phase 0 implementation: NOT STARTED / requires actual code generation
```

下一步应创建真实 `schemas/`、`pyproject.toml`、`src/`、`tests/`、`migrations/`、CI 和本地基础设施配置，而不是继续主动发散 V1 架构。
