# Examples

| 文件 | 说明 | 运行方式 |
|---|---|---|
| `quickstart.py` | 最小程序化闭环：注册本地工具 + Agent → 真实模型执行 → 打印 Run 生命周期事件 | `uv run --env-file .env python examples/quickstart.py` |
| `mcp_demo_server.py` | 一个最小 MCP 服务器（stdio，提供 `echo` / `add` 两个工具），供 MCP 冒烟脚本连接 | 被下面的脚本自动拉起 |

对应的端到端冒烟脚本在 [`scripts/`](../scripts/)：

| 脚本 | 覆盖链路 |
|---|---|
| `smoke_runtime.py` | Registry → DeepAgents 构建 → 执行 → Run 生命周期 + 真实模型工具调用 |
| `smoke_approval.py` | HIGH 风险工具 → WAITING_APPROVAL → 人工批准 → 继续执行（完整 HITL） |
| `smoke_mcp.py` | MCP stdio 连接 → 工具发现 → 经 Action Gate 调用 → 断开 |
| `smoke_api.py` | 全部走 HTTP 路由：MCP 注册/连接 → Run → SSE 事件流 → 断开 |
| `smoke_free_models.py` | 扫描可用的免费 OpenRouter 模型 |

前置条件：`.env` 中配置模型（如 `AGENT_CORE_MODEL=openrouter:minimax/minimax-m3:free`）与对应 provider key（`OPENROUTER_API_KEY` 等），以及可选的 `AGENT_CORE_PROXY_URL`。
