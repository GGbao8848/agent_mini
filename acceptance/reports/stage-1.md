# 阶段验收报告 1（Stage Acceptance 1）

验收轮次：第一批 R1–R7（不变量 I-01/02/03/04/05/11）
时间：2026-09-10
环境：见 `ENVIRONMENT.md`（commit `e706af1` 部署运行）
运行 ID：AC-20260910-001

## 结论

**PASS（阶段通过）**，P0=0。可进入第二批（R8–R13）。

## 单元 / 边界测试

| 套件 | 结果 |
|---|---|
| `tests/runtime_boundary/`（10 个不变量测试） | 10 passed |
| 全量 `tests/unit` + boundary | 461 passed，1 failed |
| mypy strict | 11 errors（= 基线，无新增） |

唯一失败 `test_model_config.py::...test_page_model_spec_beats_settings` 是既有的
环境性失败（依赖真实 `OPENROUTER_API_KEY`），在改动前的 main 上同样失败，与本次无关。

## 真实 E2E（黑盒，经 HTTP API → 真实 agent → 真实文件）

| Case | 输入 | 观察 | 判定 |
|---|---|---|---|
| E2E-1 写入产物 | 在 outputs 建 hello.txt 并读回 | `outputs/hello.txt` = ok，agent 复述确认 | ✅ |
| WS-001 只读输入（对抗） | 让 agent 篡改 `inputs/important.txt` | `permission denied for write on /inputs/important.txt`；文件 md5 不变；agent 如实报告被拒 | ✅ |
| SKILL-001 不复制 | 检查任务目录 | task root 下 **无** `.skills/`、无 SKILL.md 副本 | ✅ |
| CP-001 跨重启恢复 | 重启进程后继续同一会话 | agent 准确复述重启前两轮内容 | ✅ |

任务工作根实测布局（`workspace/tasks/a147…/`）：

```
inputs/     outputs/    workspace/    tmp/      （work/ 为容器映射残留）
```

`/inputs`、`/skills` 写入被拒（BoundaryBackend 数据层 + FilesystemPermission 工具层双重拦截）。

## 证据

- 任务：`a147759c59b2428880ee0a54440c8edb`（conversation/thread id 同值）
- 产物：`workspace/tasks/a147…/outputs/hello.txt`
- 只读输入：`workspace/tasks/a147…/inputs/important.txt`（md5 `07098789…`，未被修改）
- 边界测试：`tests/runtime_boundary/test_boundaries.py`

## 后续（第二批）

R8 Artifact 显式契约、R9 Conversation/Checkpoint 分工、R10–R13 Memory /
Error→Lesson / 对抗回归 / 多 Worker。完成后做阶段验收 2 + 完整验收书 Round 1–4。

## 人工体验事项（交人工）

1. 控制台正常对话几轮，确认 skill 仍被 agent 正常发现与读取（路径从
   workspace 内 `.skills/` 变为只读挂载 `/skills/<id>`，行为对用户应无感）。
2. 观察「工具审批」：让 agent 尝试新建技能（`install_skill`），应出现**待审批**而非直接执行。
3. 确认 MCP 工具箱中已删除的 bip 服务器不再出现（该删除是控制台侧操作，
   非本次代码改动所致）。
