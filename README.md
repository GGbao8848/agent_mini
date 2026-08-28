# Agent Core

一个**最小、解耦、可长期演进的多智能体核心框架**。它不是某个具体业务 Agent，而是一个 Agent Runtime / Agent Core：统一管理 Agent、Skill、Tool、MCP、权限与人工审批，底层复用 [DeepAgents](https://github.com/hwchase17/deepagents) / LangGraph，不重复造轮子。

## 核心架构

```text
API (FastAPI, Phase 7)
 ↓
Application (RunService 等, Phase 7)
 ↓
Agent Runtime (Phase 3)
 ↓
DeepAgents / LangGraph        ← Harness：agent loop、subagents、skills、HITL、checkpoint
 ↓
Tool Layer → Permission → Action Gate → Tool Executor → Python Tool / MCP
```

- **Domain 层**（`src/agent_core/domain/`）：纯数据 + 领域规则，不依赖任何第三方框架
- **Infrastructure 层**：对接 DeepAgents / MCP / API，可整体替换
- 依赖方向严格单向：`API → Application → Domain ← Infrastructure`

## 当前进度

| Phase | 内容 | 状态 |
|---|---|---|
| 1 | 项目结构、配置、Domain Model、Error Model、日志、Trace 抽象 | ✅ |
| 2 | Agent / Tool / Skill / MCP Registry（内存实现） | ✅ |
| 3 | 接入 DeepAgents：AgentRuntime / AgentExecutor / SubAgent | ✅ |
| 4 | Permission / ActionPolicy / ActionGate / ApprovalRequest | ✅ |
| 5 | Trace / Events / Streaming（Run 级事件流） | ✅ |
| 6 | MCP Adapter / Client / Registry | ✅ |
| 7 | FastAPI（Run / Agent / Skill / MCP / Action API） | ✅ |
| 8 | Tests / README / Docs / Examples / CLI 完善 | ⬜ |

## 快速开始

```bash
# 安装（需要 uv，Python >= 3.11）
uv sync

# 运行测试
uv run pytest

# 代码检查
uv run ruff check .
uv run mypy

# 配置
cp .env.example .env   # 按需修改；模型 provider 的 API key 交给 OPENAI_API_KEY 等标准变量
```

## HTTP API（Phase 7）

```bash
uv run --env-file .env uvicorn agent_core.api.app:app --port 8000
# 交互式文档: http://localhost:8000/docs
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/healthz` | 存活探针 |
| GET | `/v1/agents` `/v1/agents/{id}` | Agent 注册表（只读） |
| GET | `/v1/skills` `/v1/skills/{id}` `/v1/skills/{id}/versions` | Skill 注册表（只读） |
| GET | `/v1/tools` | 工具注册表（MCP 连接后自动出现） |
| GET/POST | `/v1/mcp/servers` | MCP 服务器注册表 |
| POST | `/v1/mcp/servers/{id}/connect` `/disconnect` | 连接生命周期（失败 → 503 retryable） |
| POST | `/v1/runs?wait=true` | 创建并执行 Run（默认后台执行） |
| GET | `/v1/runs` `/v1/runs/{id}` | Run 查询（含最终 output） |
| POST | `/v1/runs/{id}/cancel` | 取消 Run（终态 → 409） |
| GET | `/v1/approvals/pending` | 待人工审批列表 |
| POST | `/v1/approvals/{id}/resolve` | 批准/拒绝/编辑参数（唤醒等待中的 Run） |
| GET | `/v1/runs/{id}/events` | SSE 事件流（回放历史 + 实时，Run 终态自动关闭） |
| GET | `/v1/events` | 全局事件流（长连） |

错误统一为 `{"error": {code, message, retryable, details}}`，由领域异常一次性映射（RegistryError→404/409、StateError→409、PermissionDeniedError→403、MCPUnavailableError→503、超时→504）。

## 项目结构

```text
src/agent_core/
├── api/             # FastAPI 传输层：路由、DTO、错误映射、SSE 事件流（/v1）
├── application/     # 用例层：AgentCoreService（API/CLI 共用的唯一入口）、组装根
├── config/          # 环境变量配置（AGENT_CORE_ 前缀）
├── domain/          # 领域模型：Agent / Task / Run / Action / Tool / Skill / MCP / Trace
├── errors/          # 统一异常体系（带 retryable 标记）
├── mcp/             # MCP 适配：凭证解析、SDK 会话、连接生命周期、工具注册
├── observability/   # 日志、Tracer、EventBus、事件扇出、Run 级事件流（SSE 数据源）
├── permissions/     # ActionPolicy、ActionGate、ApprovalManager（工具执行必经闸门）
├── registries/      # Agent / Tool / Skill / MCP 注册中心（内存实现）
└── runtime/         # 模型工厂、AgentBuilder、AgentExecutor、AgentRuntime（DeepAgents）

tests/unit/          # 单元测试
docs/architecture.md # 架构文档（含 Mermaid 图）
```

## 设计原则

- **解耦**：一个模块只负责一类事情；Registry / Policy / Gate 是一等公民
- **不重复实现 DeepAgents**：SubAgent、Skill 加载、HITL、State、Checkpoint 优先复用
- **安全边界**：Agent → Tool → Permission → Action Gate → Execution，禁止绕过
- **Explicit over Magic**：`agent_registry.get("researcher")`，不做魔法自动发现
- 详见 [docs/architecture.md](docs/architecture.md)

## Roadmap

见上文进度表。远期：Web UI、Agent 热更新、多租户、Agent Marketplace。
