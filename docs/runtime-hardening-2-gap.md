# Runtime Hardening 2.0 —— 已做 / 未做对照表

对照对象：《agent_mini Agent Runtime Hardening 2.0 实施指南》（R20–R26）。
更新：2026-09-10（分支 `feat/runtime-hardening-2`）。
结论：**R20–R24 主体已落地并阶段验收（PASS，P0=0）；R25、R26 未开始；R20/R22/R23/R24 各有小项残留。**

图例：✅ 完成 / 🟡 部分完成 / ⬜ 未开始

---

## R20 Context Architecture

| 项 | 状态 | 说明 |
|---|---|---|
| 有序/有预算/可解释的 Context（§8/§9） | ✅ | `src/agent_core/context/`，每次 run 记 `context_sections` |
| Context 不再以"聊天历史"为唯一来源（§7） | 🟡 | 已有 task_state/memory 段；但历史仍是消息主体（见 R25 长任务） |
| **Tool Schema 治理（§10，PR-03）** | ✅ | `compact_definition` + 注册点/水合归一：丢掉纯装饰 schema 键（example/$schema/title…）并按上限截断工具/参数描述（默认 500/400 字符），**调用方式不变**。实测模型可见工具 token **5262 → 4282（−18.6%）**，MCP 一家 −28%。`AGENT_CORE_TOOL_SCHEMA_COMPACTION`（默认开）。**更进一步的"按需展开 schema"（只发 shortlist、用到再展开）仍未做**——当前是"压缩"，不是"裁剪工具集"。 |
| 30–50 turn 仍 context bounded（§47 验收） | ⬜ | 未跑；依赖 R25 长任务 |
| 硬性 context-window 闸门 | ⬜ | 目前只有 token/调用次数预算（`BudgetMiddleware`）+ 可选摘要，没有"接近窗口前强制裁剪" |

## R21 Task State

| 项 | 状态 | 说明 |
|---|---|---|
| 显式任务状态（§16） | ✅ | `src/agent_core/task_state/`（goal/status/steps/decisions/artifacts/failures/activity/current/next） |
| 事件驱动 reducer，非 LLM 臆测（§17） | ✅ | 纯函数折叠 trace 事件；plan 由 `update_plan` 声明 |
| 持久化 + 重启修正 | ✅ | `registry_items(kind=task_state)` + `reconcile` |
| §48 验收问答 | 🟡 | 目标/完成/当前/失败/产物可答；"下一步"依赖 agent 主动声明；`decisions` 目前基本为空（没人调用时传） |
| 状态驱动控制流 | ➖ | 按指南 §45"不许用 Summary/Memory 代替 Task State"，这里也**故意**只做记录+回注，不硬控流程 |

> 附带清理（非文档要求）：删除了死状态 `RunStatus.PLANNING` 与 team 提示词里悬空的 `todo` 工具引用（`41e6776`）。

## R22 Capability Resolver

| 项 | 状态 | 说明 |
|---|---|---|
| 唯一事实来源（§21/§22） | ✅ | `CapabilityResolver`；`ActionPolicy` 退化为薄适配；builder/console 同源 |
| UI 与 Runtime 不分叉（§20） | ✅ | `GET /agents/{id}/capabilities` 返回同一计算 |
| **每次 Run 记录 EffectiveCapabilitySet（§23/§49）** | ⬜ | 现在只在构建/判定时算，**没有落到 run 记录**。指南明确要"每次 Run 都能追踪本次实际能力集"，供 Audit/Replay/Debug/Security。小改动、价值高。 |
| 全量审计"是否还有地方自行判断能力" | 🟡 | 已收敛主要路径；未做一次穷尽扫描（arg_risk、MCP allowlist 仍是独立小判断） |

## R23 Memory Governance

| 项 | 状态 | 说明 |
|---|---|---|
| 记忆身份 = (scope, owner)（§26 的核心诉求） | ✅ | `scope_id` + `MemoryPolicy` 读写治理 |
| 写入必须过 Policy（§27） | ✅ | `add_governed`；agent 不能写 ORG、写 PROJECT 必须有绑定项目 |
| 可追溯来源（§28/§29） | 🟡 | 有 `source_run_id`/`created_by`/`task_id`/时间线；**缺"为什么创建"（creation reason）** |
| 显式 `owner/writer/readers/visibility` 字段（§26） | ⬜ | 目前**读者/写者是策略推导**（`visible_scopes`），未作为字段存储。单租户下可用；多用户/多租户前需补 |
| 生命周期 candidate→active→superseded→expired（§28） | 🟡 | 有 active/superseded_by/expires_at；**没有 candidate（候选→确认）阶段** |
| §50 验收（谁能读/改、为什么创建） | 🟡 | 读/改可推导回答；"为什么创建"缺 |

## R24 Execution / Network Policy

| 项 | 状态 | 说明 |
|---|---|---|
| 显式 ExecutionPolicy（§32/§35） | ✅ | `src/agent_core/execution/`（文件/网络/环境/超时/资源五问） |
| 网络模式可配（§34） | ✅ | `AGENT_CORE_SANDBOX_NETWORK=host|private|none`；allow 记录 |
| 环境白名单（§34） | ✅ | `AGENT_CORE_SANDBOX_ENV_ALLOW`，只转发真实存在项 |
| 资源上限（§34） | ✅ | podman memory/cpus/pids |
| **podman 加固（§34 剩余）** | ⬜ | 未加 `--cap-drop`、`--read-only` 根文件系统、`--security-opt no-new-privileges`、seccomp |
| 目标地址强制过滤（§34 示例） | ⬜ | host 模式下 podman 无法按地址过滤（策略已如实标 `enforced=false`）；真正强制需 `private` + 外部防火墙/代理 |
| §51 验收（能访问什么/多久/多少资源） | ✅ | `GET /execution/policy` 如实回答 |

## R25 Scenario-Level Reliability —— ⬜ 未开始

| 项 | 状态 | 说明 |
|---|---|---|
| SC-01 文件分析 / SC-02 Skill+Code / SC-03 Skill+MCP / SC-04 Multi-tool / SC-05 跨会话记忆 / SC-06 重启（§38） | ⬜ | 无。**基础已具备**：`src/agent_core/eval/` 有真实任务 + 校验器 + runner，但**没有"同一 scenario 重复 N 次"的模式**，也没有这 6 个固定 scenario |
| 每 scenario ×5（P0 ×10）（§39） | ⬜ | 未跑 |
| 30/50/100 turn 长任务（§40） | ⬜ | 未跑 |

## R26 Production Release Gate —— ⬜ 未开始

| 项 | 状态 | 说明 |
|---|---|---|
| `acceptance/reports/release-gate-<version>.md`（§53） | ⬜ | 无。**已有素材**：`stage-1/2/3.md` + `full-rounds-1-4.md`（可整合） |
| 最低标准矩阵（§43：P0=0 / 核心E2E 100% / Security 100% / Restart 100% / 重复成功≥95% …） | 🟡 | 部分项在阶段验收里覆盖；"重复成功率≥95%"依赖 R25 |

---

## 建议的收尾顺序（按 §46 + 性价比）

1. ~~**PR-03 Tool Schema 治理（R20 残留）**~~ ✅ `84c9186`（压缩，−18.6%）；**剩下的"按需展开 schema"是更彻底的一步**。
2. **R22 每次 Run 记录能力集** —— 小改动，补齐 §23/§49 的审计闭环。
3. **R24 podman 加固** —— 你若会切回 podman，优先；当前 host 下价值低。
4. **R23 补 creation reason + 显式 reader/writer 字段** —— 单租户非紧急，多用户前必做。
5. **R25 6 个 Scenario ×5** —— 需要先给 eval runner 加"重复 N 次 + 汇总成功率"，再固化 SC-01..06。
6. **R26 Release Gate 报告** —— 依赖 R25 的重复数据，最后整合 stage-1/2/3 + R25 汇总。

## 与指南的一致性检查（§45 禁止项）

- 无大规模重写 Runtime ✅；无"没失败测试就改代码" ✅（每项先写边界测试）。
- 未用 Prompt 代替权限 ✅（能力经 resolver 强制；`update_plan` 是工具不是权限）。
- 未用 Summary/Memory/Workspace 文件代替 Task State ✅（Task State 独立）。
- 未用 checkpoint 代替长期 Memory ✅；未用 host subprocess 冒充 Sandbox ✅（host 如实标为不可隔离）。
- 未用"一次成功 E2E 证明可靠" ✅——但仍需 R25 的重复性来真正满足这条。
