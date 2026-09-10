# 阶段验收报告 3（Stage Acceptance 3）

验收轮次：Runtime Hardening 2.0 第一批（R20 Context / R21 Task State / R22 Capability / R23 Memory Governance / R24 Execution Policy）
时间：2026-09-10
环境：见 `ENVIRONMENT.md`（分支 `feat/runtime-hardening-2`，部署运行）
运行 ID：AC-20260910-003

## 结论

**PASS（阶段通过）**，P0=0；真实 E2E 发现 1 个 P2 并已修复。R20–R24 全部落地，
每项都有「代码在、生产走」的真实运行证据（不只看单元测试）。

## 交付内容（R20–R24）

| R | 主题 | 关键落点 | 提交 |
|---|---|---|---|
| R20 | Context Architecture | `src/agent_core/context/`：有序/预算/可解释的 system prompt 装配；`run.metadata.context_sections` 记录每一段来源与 token | `7aebd3e` |
| R21 | Task State | `src/agent_core/task_state/`：事件投影出显式进度（plan/status/failures/artifacts/activity）；`update_plan` 工具；`GET /tasks/{id}/state` | `a6d0fcd` |
| R22 | Capability Resolver | `src/agent_core/capabilities/`：唯一能力事实来源（绑定∩技能∩可用∩规则∩风险阈值）；`GET /agents/{id}/capabilities` | `1cb4c75` |
| R23 | Memory Governance | `src/agent_core/memory/policy.py`：`(scope, scope_id)` 身份 + 读写策略 + 来源溯源 | `2d932c3` |
| R24 | Execution / Network Policy | `src/agent_core/execution/`：显式执行信封；`AGENT_CORE_SANDBOX_NETWORK`；`GET /execution/policy` | `62b4283` |

## 单元 / 边界测试

| 套件 | 结果 |
|---|---|
| 全量 `uv run pytest` | **592 passed，1 failed** |
| 新增 R20 `test_context.py` | 9 passed |
| 新增 R21 `test_task_state.py` + `test_task_state_runtime.py` | 17 passed |
| 新增 R22 `test_capabilities.py` + API | 全通过 |
| 新增 R23 `test_memory_governance.py` + `_runtime.py` | 19 passed |
| 新增 R24 `test_execution_policy.py` | 12 passed |
| ruff | 无新增（基线 38 → 36，改动未引入） |
| mypy strict | 11 errors / 7 files（= 基线，无新增） |

唯一失败仍是既有的 `test_model_config::test_page_model_spec_beats_settings`
（依赖真实 `OPENROUTER_API_KEY`），改动前 main 上同样失败。

## 真实 E2E（黑盒，HTTP API → 真实 agent → 真实文件）

设备：本地 qwen3.8-27b，sandbox=host，业务库/checkpoint 已从旧数据清理后重启。

| Case | 输入 | 观察 | 判定 |
|---|---|---|---|
| R21 计划落库（任务 1） | 三步创建 `outputs/hardening_{a,b}.txt` 并验证 | `GET /tasks/{id}/state` 返回 3 步计划、2 个 artifact、`status=completed`、`run_count=1` | ✅ |
| **R21 参数容忍（任务 1 暴露 P2）** | 同上 | agent 连续 4 次调用 `update_plan`：`["str"]`→`[{step}]`→`[{text}]`→`[{description}]`，前三次 `'str' object has no attribute 'get'` | 🔴→已修 |
| R21 修复复验（任务 2） | 两步：先 `update_plan` 再 `run_code` | 计划**一次成功**，`failures=[]`，artifact `accept2.txt` | ✅ |
| R20 Context 记账 | 检查任务 1 run metadata | `context_sections` = system 318 / autonomy 116 / environment 349 / memory 334 tokens；`context_injected_tokens=799`；`context_breakdown` 显示 MCP schema 3208（最大固定成本） | ✅ |
| R22 能力一致性 | `GET /agents/avatar/capabilities` | exposed 10 个（含 `update_plan`）；`install_skill` state=restricted（HIGH 风险 → 需审批）；notes 说明「未显式绑定工具」 | ✅ |
| R24 执行信封 | `GET /execution/policy` | host 模式如实报告：文件无隔离、网络 `enforced=false`、环境含全部宿主变量；超时 300s/上限 900s | ✅ |
| R23 记忆治理 | 控制台建 user / project(scope_id) 记忆后再检索 | 写入按 scope 落 owner；跨项目隔离（proj-b 看不到 proj-a）；`created_by`/`scope_id` 正确 | ✅ |
| R23 重启恢复 | 重启服务后读任务 1 状态 | `status=completed`、3 步、2 artifact 均存活 | ✅ |

（E2E 用的两条「验收测试：」记忆已删除，未污染业务库。）

## 发现并修复的缺陷（P2）

**`update_plan` 参数形状过严**：生产 trace 显示模型并不严格遵守 schema——
首次调用把 `steps` 传成字符串数组，随后试了 `{step}`、`{text}`，第四次才用
`{description}`。原 handler 假设字典，直接 `item.get(...)` 抛
`'str' object has no attribute 'get'`。

- 修：`_normalize_steps` 接受「字符串数组」或「任意常见键名的对象数组」
  （description/step/text/title/name/content），非法项丢弃而非整体报错；
- 附带：失败的「调查类工具」（`update_plan`/`read_file`/`ls`…）记录为 failure
  但**不再计入 activity**，避免「重试记计划」被误判为有效进展。

**教训（与 R4/R20 一致）**：模型对 tool schema 的遵守度很松，只有真实 agent
跑起来才会暴露；纯单元测试发现不了。

## 不变量覆盖（新增）

| ID | 不变量 | 覆盖 |
|---|---|---|
| I-20 | 任务状态由事件投影，非 LLM 臆测 | `test_task_state.py`（status/goal/failure 来自事件） |
| I-21 | 嵌套运行（验证器/子代理）事件不改任务状态 | `test_task_state.py::test_nested_run_events_are_ignored` |
| I-22 | 重启后状态被修正、不残留 running | `test_task_state.py::test_reconcile…` + E2E 重启 |
| I-23 | 能力展示与运行时强制同源 | `test_capabilities.py::test_resolver_and_policy_agree` + API |
| I-24 | agent 不能写 ORG / 无绑定项目的 PROJECT 记忆 | `test_memory_governance.py` 写入用例 |
| I-25 | 记忆读取按 (scope, owner) 隔离 | `test_memory_governance.py` / `_runtime.py` |
| I-26 | 执行/网络/环境信封显式且如实 | `test_execution_policy.py`（含 host enforced=false） |

## 已知限制（如实记录）

1. **网络目标过滤未强制**：`host` 模式下 podman 无法按地址过滤，策略如实标
   `enforced=false`；要真正限制需 `sandbox_network=private` + 外部防火墙。
2. **Cloud/远端模型下的 update_plan**：本次验证用本地 qwen3.8-27b；换模型后
   参数形状可能不同，`_normalize_steps` 已尽量宽，但仍可能有新形状。
3. **Task State 不驱动图控制**：状态是「记录 + 回注」，不是硬控制流；模型仍可
   忽略它——降低漂移，不消除。

## 人工体验事项（交人工）

1. **任务进度**：做一个 3 步以上的任务，前端应能看到进度（计划/当前步骤/产物），
   且刷新后仍在。
2. **上下文来源**：上下文仪表盘应能显示系统/环境/记忆各自的 token 占比。
3. **能力面板**：agent 能力视图应与「实际能调用」一致（如 `install_skill` 标为
   受限/需审批）。
4. **执行策略**：控制台应能看到「当前执行模式：host（无隔离）」这类如实提示。
5. **跨项目记忆**：绑定项目 A 会话里说的项目事实，不应出现在项目 B 会话。

## 后续（未做，下一批）

- R22 剩余：把能力集写入每次 Run 的记录（审计/回放）。
- R24 剩余：podman 下 `--cap-drop`/`--security-opt`/只读根文件系统的落地。
- R25/R26：6 个固定 Scenario ×5 的重复性验收 + Release Gate 报告（`release-gate-<version>.md`）。
