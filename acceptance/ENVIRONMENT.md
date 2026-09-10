# Agent Runtime 验收环境（冻结基线）

> 本文件在每次验收开始时冻结；验收过程中不得随意改变环境。
> 首次冻结：2026-09-10（refactor/runtime-boundaries 起点）

## 版本

| 项 | 值 |
|---|---|
| Git commit | `7463cb9`（分支 `refactor/runtime-boundaries` 起点，基于 main） |
| Python | 3.14.4 |
| Node | v24.19.0 |
| deepagents | 0.7.10 |
| langgraph | 1.2.11 |
| langchain | 1.3.18 |
| OS | linux 7.0.0-30-generic x64 |
| 对话模型 | 本地 vLLM qwen3.8-27b（http://10.10.10.146:8001/v1） |

## 运行环境

| 项 | 值 |
|---|---|
| Runtime URL | http://127.0.0.1:8000（scripts/serve_console.py） |
| Business DB | `AGENT_CORE_DATABASE_URL`（.env，SQLite） |
| Checkpoint DB | `agent_core-checkpoints.db`（与业务库分离） |
| Workspace root | `/home/user/project/agent_mini/workspace` |
| Artifact root | 任务目录内（`workspace/tasks/<task>/`，绑定项目时=项目目录） |
| Skill registry root | `workspace/skill-maker/` 及登记目录 |
| MCP endpoint | tinyfish（stdio + mcp-remote）、bip-work-hour-reporting（stdio） |
| Sandbox | `host`（AGENT_CORE_SANDBOX=host） |

## 已知环境性失败（非本次改动引入，基线即存在）

- `tests/unit/test_model_config.py::TestBuildModelOverrides::test_page_model_spec_beats_settings`
  依赖真实 `OPENROUTER_API_KEY`，hermetic settings 下必然失败。
- mypy strict 基线：11 errors / 7 files。
- 7 个既有环境性测试失败（历史记录）。

## 验收节奏（本次约定）

- **阶段验收**：每完成约 10 个问题（或一个 R 分组）做一次回归 + 抽查，避免每次全量 E2E 烧 token。
- **人工体验**：涉及 UI / 真实用户体验的验收轮，产出清单交人工过一遍。
- **完整验收**：全部 R 阶段完成后，按验收书 Round 1–4 跑完整证据矩阵。
