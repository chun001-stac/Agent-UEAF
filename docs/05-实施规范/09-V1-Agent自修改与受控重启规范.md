# UEAF V1 Agent 自修改与受控重启规范

版本：`0.1.0-draft`  
规范状态：Draft  
Architecture Generation: `V1`  
Maturity: `Implementation Guidance`  
Implementation: `Current`

## 1. 目的

本文定义 UEAF V1 中 Agent 在发现实现缺陷后，如何在不新增 Canonical Object、不扩大既有 Authority、不绕过 Tool / Security / Eval / Release 边界的前提下完成：

```text
发现问题
-> 生成代码修改
-> 隔离验证
-> 受控应用
-> 运行时重启
-> 状态恢复
-> 健康检查
-> 必要时回滚
```

本文只机器化和收敛现有 V1 能力，不建立新的 Self-Modification Service、Restart Service、Sub-Iteration 状态机或第二套 Release Authority。

## 2. 核心结论

UEAF V1 MUST 区分两类场景：

### 2.1 开发态代码修改

Codex / 工程 Agent MAY 在隔离 worktree / sandbox 中修改参考实现代码，并执行 Ruff、mypy、pytest、contract/integration/failure-injection tests。

开发态修改不得直接证明生产发布安全，也不得绕过 PR / Release / Security 规则。

### 2.2 运行态 Agent 自我修复

当运行中的 UEAF Agent 试图修改 UEAF 自身可执行代码、Prompt、配置、拓扑或其他可发布组件时，必须映射到现有 Evolution / Mutation / Release 语义。

涉及代码生成或代码修改的自动修复属于现有 R4 generated-code mutable surface，必须遵守：

```text
Evidence / Diagnosis
-> Repair Router
-> MutationProposal
-> GenomeManifest candidate
-> ReleaseCandidate
-> Eval / Security / Operational gates
-> ReleaseDecision
-> ReleaseManifest
-> activation / restart
```

禁止：

```text
LLM
-> 直接覆盖当前运行目录
-> kill 当前进程
-> 以修改后的代码直接继续运行
```

## 3. Agent Loop 与 Runtime Restart 分离

Agent iteration 只表示同一 Run 内新的受控推理/编排步骤；Runtime restart 表示执行进程生命周期变化。

二者不得混为同一状态语义。

正常 Agent loop：

```text
Run
-> ContextBuildPort
-> ModelStepPort
-> StructuredDecision
-> Tool / Handoff / Observation
-> next AdvanceRun
```

受控重启：

```text
Run reaches safe persistence boundary
-> authoritative state committed
-> process exits gracefully
-> external supervisor starts approved revision
-> runtime reacquires valid lease/fencing token
-> ResumeRun / AdvanceRun
```

LLM 不拥有进程监督权。LLM 可以产生修复 intent；真正的文件写入、副作用、进程切换与恢复由既有执行/运行边界控制。

## 4. 不允许 Agent 直接“杀死自己”

UEAF Runtime MUST NOT 依赖运行中 Agent 对自身执行：

```text
kill -9
os._exit()
exec arbitrary replacement binary
in-process core module hot reload
```

作为规范重启路径。

推荐由进程外 Supervisor 管理 Runtime 生命周期，例如 systemd、container runtime 或 Kubernetes。具体 Supervisor 是 Reference Implementation detail，不成为公共 Canonical Object 或 Port。

V1 Reference Implementation 默认 SHOULD 支持 graceful shutdown + external supervisor restart；不得把 Supervisor 实现提升为 UEAF 公共语义 Owner。

## 5. 修改必须发生在隔离工作区

Agent / Codex 对代码的修改 MUST 首先进入隔离 mutable surface：

```text
canonical checkout / active revision
        |
        +-- immutable running source
        |
        +-- isolated worktree / sandbox
                |
                +-- candidate patch
```

禁止在 active revision 上边运行边原地覆盖核心模块。

隔离区至少必须支持：

```text
source diff
candidate revision identity
static checks
targeted tests
integration tests
security checks
artifact/build output
```

候选修改未通过门禁前，不得成为 active runtime revision。

## 6. 修改生成与副作用边界

LLM / Agent 可以：

- 定位错误；
- 形成修复假设；
- 生成 patch；
- 请求读取代码；
- 请求测试；
- 请求构建候选版本；
- 在既有 Policy / Authority 范围内请求推进候选。

LLM / Agent 不可以：

- 自行扩大 mutable surface；
- 绕过 PDP；
- 绕过 Security hard gate；
- 自签 EvalResult / QualityGateDecision / ReleaseDecision；
- 把测试通过等价为生产发布通过；
- 直接把 candidate revision 声明为 active；
- 修改 Governance Kernel；
- 通过自重启逃避审批、预算、审计或失败状态。

这保持现有原则：LLM 产生 intent / proposal，权威执行组件产生 effect / decision。

## 7. 开发态 Self-Repair Loop

本地/CI Reference Implementation MAY 使用以下开发循环：

```text
1. Observe failure
2. Diagnose smallest repair target
3. Create isolated worktree
4. Generate patch
5. Apply patch in worktree
6. Run targeted tests
7. Run Ruff / mypy / pytest
8. Run relevant contract/integration/failure-injection tests
9. If failed: return evidence to next Agent iteration
10. If passed: create candidate revision / PR
11. Human or configured governance path promotes change
12. External supervisor restarts runtime when activation requires restart
```

开发态循环不新增 `SelfRepairRun`、`PatchRun`、`RestartRequest` 等公共对象。实现 MAY 使用内部结构，但不得成为公共契约或第二事实源。

## 8. 运行态代码修复必须进入既有 R4 链

运行态 UEAF 自身代码属于高影响 mutable surface。

若 Diagnosis 认为必须修改代码：

```text
REP-001 root cause diagnosis
-> REP-002 smallest effective repair
-> REP-003 escalation requires evidence
-> existing Repair Router
-> r4 MutationProposal
```

MutationProposal 仍必须通过既有 mutable-surface intersection 与 patch-shape 规则，并先物化新的 immutable GenomeManifest candidate。

必须保持：

```text
MutationProposal
-> GenomeManifest candidate
-> ReleaseCandidate
```

禁止：

```text
MutationProposal
-> active source tree
```

或：

```text
MutationProposal
-> restart into unreviewed revision
```

## 9. Restart 前的持久化边界

任何可能中断当前 Runtime 进程的激活动作前，必须先到达可恢复的权威持久化边界。

至少满足：

- 当前权威 RunRecord 已提交；
- 已完成 Action 的 ActionReceipt 不可被覆盖；
- 未决 Action 引用保持可审计；
- outbox / authority event 与状态提交满足既有原子性要求；
- 当前 worker 不继续持有将被新进程误复用的执行权；
- restart 后必须重新验证 lease / fencing token；
- PrincipalContext、PolicyDecision、ReleaseManifest 等冻结引用不得因重启被静默替换。

Restart 不能作为“清空失败历史”的手段。

## 10. Restart 后恢复

新进程启动后 MUST 从持久化权威状态恢复，而不是依赖旧进程内存或直接续接旧 Prompt buffer。

推荐恢复路径：

```text
bootstrap approved active revision
-> inspect persisted RunRecord
-> verify runtime_adapter_ref remains valid/frozen
-> acquire a fresh valid lease/fencing token
-> restore authoritative task/run references
-> rebuild current ContextManifest through ContextBuildPort when needed
-> invoke ResumeRun / AdvanceRun
-> continue next controlled model step
```

不得把整个旧 Prompt / provider-local hidden state 当作唯一恢复来源。

Context 仍由 Context Semantic Owner 构建；Tool、Runtime Adapter 或 restart logic 不得自行裁剪、压缩或重排 ContextManifest。

## 11. Revision 与状态身份

受控重启 MUST 能区分：

```text
previous active revision
candidate revision
approved active revision
last known good revision
```

这些可以由现有 ReleaseCandidate / ReleaseManifest / component version-set / artifact identity 表达；V1 不为此新增新的 Canonical revision object。

Runtime restart 后必须能够证明自己加载的是已批准 ReleaseManifest 所绑定的组件版本，而不是工作区中任意最新文件。

## 12. Health Check 与 Rollback

候选 revision 被批准并激活后，必须进入既有 rollout / observation / rollback 语义。

典型流程：

```text
Revision A = last known good
-> candidate B
-> gates pass
-> ReleaseManifest activates B
-> restart into B
-> health / operational observation
   |-- pass -> continue B
   +-- hard failure -> existing rollback path -> A
```

Rollback MUST 使用既有 Release/rollback Authority 和签署清单，不允许 Agent 自己选择任意历史 commit 直接回退。

`REL-003`、`REL-004`、`REL-005` 仍是权威验收基线。

## 13. 不允许核心模块热替换

V1 Reference Implementation MUST NOT 把 Python `importlib.reload()`、动态 monkey patch、运行中替换已 import class/function 等作为核心 Runtime 升级的规范机制。

原因包括：

- 内存对象可能继续引用旧实现；
- 事务与 lease 状态难以证明一致；
- 审计无法可靠绑定代码 revision；
- rollback 边界不清晰；
- Adapter / Context / Policy 等 Semantic Owner 可能同时出现新旧实现。

核心组件升级默认采用新进程重新 import approved revision。

## 14. Retry、Re-plan 与 Restart 的区别

三者必须保持独立：

### Retry

同一 logical Action 的下一 ExecutionAttempt；遵守 `ACT-003/004` 的 outcome certainty、retry policy 与 budget。

### Re-plan

Agent 根据 Observation 产生新的 StructuredDecision / Action；它不是对旧 ActionReceipt 的覆盖。

### Restart

Runtime 进程生命周期变化；它不得隐式创建新的业务 Action，也不得改变已冻结的上游 authority facts。

进程重启不等于 AgentRun 重启，也不等于新的用户 Request。

## 15. Security 与权限

自修改能力 MUST 默认收窄权限，并至少满足：

- generated code 只进入 sandbox/build pipeline；
- Agent 无权写 Governance Kernel；
- Agent 无权修改/关闭 security hard-fail tests；
- candidate build identity 与 runtime execution identity SHOULD 分离；
- Judge/Eval identity 不拥有业务写权限；
- secrets 不进入 patch、Prompt、普通 log 或 generated test fixture；
- restart 不得导致 scope 扩大；
- resumed PrincipalContext 权限只能保持或收窄；
- 未通过 Release activation verification 的 candidate 不得启动为 active runtime。

## 16. Reference Implementation 最小实现

V1 首版不要求 Kubernetes。

推荐最小实现：

```text
Python UEAF Runtime
+ PostgreSQL authority persistence
+ existing queue/outbox infrastructure
+ Git isolated worktree for development/candidate build
+ deterministic test profile
+ external supervisor (systemd or container runtime)
```

Supervisor 只负责：

```text
start
stop
graceful restart
process liveness
```

它不得成为 Policy、Eval、Release 或 Run State 的第二 Authority。

## 17. Failure Semantics

### 17.1 Patch 生成失败

保留失败 evidence；进入下一 Agent iteration 或终止，不扩大 repair scope。

### 17.2 Tests 失败

candidate 不可推进；不得因为 Agent 自评“看起来正确”而跳过。

### 17.3 Restart 前进程崩溃

使用现有 `RUN-004 crash recovery`；不得重复权威提交。

### 17.4 Restart 后启动失败

不得把 candidate 标记为成功；进入 operational failure / rollback path。

### 17.5 Health check 失败

使用既有 Release rollback 机制回到批准的 last-known-good release。

### 17.6 Policy / Security / Release Authority 不可用

fail closed。Agent 不得生成本地 allow 或自行激活 candidate。

## 18. Acceptance Mapping

本文不注册新的 Test ID 前缀，也不成为 Test ID 的第二 Owner。

实现至少必须复用并扩展 fixture 覆盖以下既有验收语义：

```text
RUN-003 stale fencing
RUN-004 crash recovery
RUN-007 adapter binding frozen before admission
CON-013 authoritative state/event atomicity
ACT-003 timeout unknown no blind retry
ACT-004 certain failure retry only
SEC-002 delegation narrows after Resume/Retry
SEC-003 credential non-leak
REP-001 symptom != repair target
REP-002 smallest effective repair
REP-003 escalation requires evidence
REP-004 R5 no automatic MutationProposal
MUT-002 frozen reject
MUT-004 repair-level mismatch
MUT-005 effective surface intersection
MUT-007 Genome materialization
MUT-008 patch shape
REL-003 rollback
REL-004 release activation chain fail closed
REL-005 manifest lifecycle and delivery contract
```

后续若需要新增具体 Test ID，必须先登记到 `04-V1验收与一致性测试规范.md`，再由测试实现引用。

## 19. 禁止的 V1 实现捷径

以下实现均不合格：

```text
Agent has unrestricted shell and edits active source in place
Agent modifies code and restarts before tests
Agent kills itself before authoritative state is durable
restart reuses stale RunLease/fencing token
restart silently changes RuntimeAdapter
restart silently changes PrincipalContext / PolicyDecision
candidate revision bypasses ReleaseCandidate/Eval/ReleaseManifest
failed health check leaves candidate active without rollback path
hot reload creates mixed old/new core runtime
Agent invents local allow when PDP/Release Authority is unavailable
```

## 20. 设计原则总结

UEAF V1 的自修改能力遵守：

```text
LLM proposes
Tool / build pipeline materializes candidate
Policy constrains
Eval measures
Release Authority approves
Supervisor restarts
Run State restores
Context Owner rebuilds current model input
Rollback returns to approved last-known-good release
```

因此，“Agent 自己改代码并重启”在 UEAF 中不是一个拥有超级权限的新模块，而是既有 Diagnosis、Mutation、Tool、Security、Eval、Release、Run Recovery 能力的一次受控组合。
