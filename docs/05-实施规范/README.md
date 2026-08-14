# UEAF V1 实施规范入口

Architecture Generation: `V1`  
Implementation: `Current`

本目录不是新的架构层，而是把既有 V1 规范编译成可由 Codex/工程团队直接实现和验收的工程合同。

## 文档顺序

1. [V1 机器 Schema 包规范](01-V1机器Schema包规范.md)  
   把 Canonical Object、Profile、Mutation Patch、Event 等转换为机器 Schema。

2. [V1 API、Port 与事件契约](02-V1-API端口与事件契约.md)  
   固定调用方向、输入输出、错误、幂等、timeout/retry、Event owner 和版本。

3. [V1 持久化与事务映射](03-V1持久化与事务映射.md)  
   固定 authoritative/projection 存储、事务、CAS、fencing、outbox 和 Action/Evolution/Release 一致性。

4. [V1 验收与一致性测试规范](04-V1验收与一致性测试规范.md)  
   把架构不变量转换为 RUN/ACT/RAG/EVAL/REL/EVO/MUT/OBJ/STR/ETH Test IDs。

5. [V1 参考实现与 Codex 开发规范](05-V1参考实现与Codex开发规范.md)  
   固定首个 Python Reference Implementation Profile、仓库结构、开发阶段和 Codex 决策边界。

## 规范优先级

本目录只能细化和机器化上层 V1 语义，不能覆盖它们。

发生冲突时遵循：

```text
核心规范
> 总体设计
> ADR
> 功能模块
> 实施规范
> 参考架构
```

## Code-ready 路径

```text
Normative V1 Docs
  -> Machine Schema
  -> API / Port / Event
  -> Persistence / Transaction
  -> Acceptance Test IDs
  -> Reference Implementation Profile
  -> Codex Development
```

## Codex 首次进入仓库应读取

```text
README.md
AGENTS.md
docs/00-总览/06-UEAF架构代际与实施范围.md
docs/01-核心规范/* V1 Current
docs/04-决策记录/ADR-001..016
docs/05-实施规范/README.md
```

任务开发时只再读取与当前模块直接相关的功能模块/参考架构，避免把 V2/V3 Future/Research 误当 Current。

## 当前 V1 关键边界

- Evolution Canonical Object 只有五个；
- V1 不建设 Species/Gene Pool/Ecosystem Fitness/Meta Evolution；
- Runtime Adapter 不绕过 Model/Tool/Context/Telemetry Port；
- 所有企业副作用经过 Tool Gateway；
- `outcome_unknown` 先 reconciliation；
- 当前 `ReleaseManifest` 不原地自改；
- Mutation 必须通过 Subject Profile + Effective Mutation Surface 校验；
- R5 Governance 不进入同一自动递归链；
- Candidate/Eval/Budget/Release 复用既有 UEAF 语义；
- 正常 Evidence Collection / Trigger Candidate 路径目标为 0 LLM Token。
