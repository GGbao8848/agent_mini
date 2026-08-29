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
| 8 | Tests / README / Docs / Examples / CLI 完善 | ✅ |
| 9 | Run 指标：token/耗时/模型与工具调用数（callbacks 全链路统计） | ✅ |
| 10 | 团队编排：协调者规划 + 多子代理原生并行 + 显式 fan-out + SUBAGENT 事件 | ✅ |
| 11 | 评测基准：多类型任务端到端对比（时间/token/调用数，markdown+JSON 报告） | ✅ |
| 12 | 原生中间件接入：summarization / 调用上限 / 重试 / 降级（ResiliencePolicy → LangChain AgentMiddleware） | ✅ |
| 13 | 真实任务评估：5 类真实任务（实时 API/结构化抽取/代码执行验证/编排对比/多步工具链）+ 客观校验器 | ✅ |
| 14 | Team 模式调优：汇总保真硬规则 + worker 汇报紧凑化 + `TeamSpec.merge_instructions` + 校验器加固 | ✅ |

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

## 评测基准（Phase 11）

`src/agent_core/bench/` 提供可复用的基准套件：4 类常见任务（工具问答、多文档摘要、多主题简报、结构化抽取），每个任务可用三种执行模式跑通并自动对比——

- `single`：单 agent 一次性完成（对照组）
- `team`：协调者 + 工人团队，由模型分析任务后自行决定是否委派/并行（模型驱动，DeepAgents 原生并行 `task` 调用）
- `fanout`：代码显式拆分子任务并发执行 + 汇总（代码驱动，`orchestration.run_parallel`）

指标来自 Phase 9 的 usage 统计：耗时、输入/输出 token、模型与工具调用数，报告输出 markdown 对比表 + 各任务最快/最省策略结论，另附 JSON 便于追踪趋势。

```bash
uv run --env-file .env python scripts/bench_run.py   # 结果写入 bench_results/
```

已验证的行为：小任务上协调者会正确判断"无需委派、直接作答"（更省 token 与时间）；任务越重（子任务越多、越长），team/fanout 的并行收益越明显——这正是基准要量化的决策依据。

## CLI（Phase 8）

安装后提供 `agent-core` 命令（也可 `uv run agent-core ...`）：

```bash
# 启动 HTTP API 服务
agent-core serve --port 8000

# 自包含本地演示：注册本地工具 + Agent，真实模型执行
agent-core demo

# 操作一台运行中的服务器（--api 默认 http://127.0.0.1:8000，可放在子命令前后）
agent-core --api http://127.0.0.1:8000 agents
agent-core run calculator "What is 19 + 23?"          # 等待完成并打印输出
agent-core run assistant "hi" --no-wait               # 异步启动
agent-core runs [--agent assistant]
agent-core approvals                                  # 待审批列表
agent-core resolve <approval_id> --decision approved --by alice
agent-core resolve <approval_id> --decision edited --edit input='new text'
agent-core cancel <run_id>
agent-core events                                     # 实时事件流（Ctrl-C 退出）
agent-core events <run_id>                            # 单 Run 事件流，终态自动结束
agent-core mcp-connect demo / mcp-disconnect demo
```

## 真实任务评估（Phase 13）

`src/agent_core/eval/` 用 5 个**真实任务**端到端评估框架，每个答案由确定性校验器客观打分（不是目测）：

| 任务 | 覆盖维度 | 校验方式 |
|---|---|---|
| 实时天气问答（open-meteo 地理编码+预报真实 HTTP 工具） | 实时工具、单跳问答 | 工具确实被调用；答案温度与实测值 ±3°C |
| 客服记录 → 严格 JSON（4 笔订单） | 结构化抽取、指令遵循 | JSON 解析、条数、字段完整、金额合计=2236、日期 ISO 化 |
| 修复 off-by-one bug 的 Python 函数 | 代码能力 | **实际 exec 模型输出的代码**，跑 4 组用例 |
| 三币种汇率简报（frankfurter 真实汇率 API）× single/team/fanout | 编排对比、实时数据 | 三组汇率数值落在合理区间 |
| 2026 节假日查询 + calculator 拼假（nager.date 真实 API） | 多步规划、工具链、计算 | 关键词 + 具体天数 |

```bash
uv run --env-file .env python scripts/eval_real.py   # 结果写入 eval_results/
```

首轮实测（minimax-m3:free）：6/7 通过——天气答案与实测完全一致（18.4°C）、JSON 抽取全对（含合计金额）、修复代码通过全部 4 组执行用例、fanout 与 single 的汇率简报数值全部正确。**team 模式失败案例**：协调者确实并行委派了 3 个 worker 且 worker 返回了正确汇率，但汇总时混入了错误数字、耗时与 token 均为 single 的 ~1.3/3.4 倍——印证"小任务不值得委派"，也暴露了团队汇总的幻觉风险（这是需要 LLM-as-judge 或引用校验进一步治理的方向）。

## Team 模式调优（Phase 14）

针对 Phase 13 暴露的 team 汇总幻觉，从"提示词 + 领域模型 + 校验器"三层调优：

| 调优杠杆 | 位置 | 内容 |
|---|---|---|
| 汇总保真硬规则 | `COORDINATOR_PROMPT` | MERGE 要求：数字/日期/专名**逐字复制** worker 返回值，禁止重算、换算、凭记忆补数；关键数值标注来源 worker；缺失/冲突要明说，不许猜 |
| worker 汇报紧凑化 | `COORDINATOR_PROMPT` | DELEGATE 要求 worker 只回报具体事实/结果（短、结构化），压缩合并上下文 |
| 专属合并规则 | `TeamSpec.merge_instructions` | 按团队注入 MERGE 规则（如 fx 团队：每个汇率数值必须逐字复制子任务 JSON 的 rate 字段并标注来源） |

校验器同步加固：识别 `100 JPY ≈ ¥4.21` 这类百单位报价并归一化，消除对正确答案的误伤（plausibility 语义不变：输出须包含落在合理区间的汇率）。

实测（`uv run --env-file .env python scripts/eval_real.py --suite fx`）：team 从 FAIL → **PASS**，三个汇率全部逐字转录并标注 `worker-1/2/3` 来源。附带发现：single 输出中自算的"高约 16.4%"与 Phase 13 team 混入的错误数字 16.4 同源——幻觉源头正是模型把自行换算的百分比当成了汇率，"禁止重算"规则正中要害。成本结论不变：team 的委派开销是结构性的（~3.3x tokens），小任务仍应选 single；调优解决的是"用 team 时结果必须对"。

## 可靠性策略（Phase 12）

`AgentSpec.resilience`（`ResiliencePolicy`）把可靠性/成本控制声明为纯数据，构建时映射到 LangChain **原生** AgentMiddleware（不重复造轮子）：

| 策略字段 | 映射的原生中间件 | 作用 |
|---|---|---|
| `summarization`（trigger_tokens/messages/fraction + keep_messages） | `SummarizationMiddleware` | 上下文接近触发线时自动摘要历史，省 token |
| `model_call_limit` + `call_limit_exit` | `ModelCallLimitMiddleware` | 限制单次 Run 的模型调用数，防失控（end 优雅收尾 / error 报错） |
| `tool_retries` / `model_retries` | `ToolRetryMiddleware` / `ModelRetryMiddleware` | 瞬时失败自动退避重试 |
| `model_fallbacks` | `ModelFallbackMiddleware` | 主模型失败后按序降级到备选模型 |

已实测：调用上限在 1 次模型调用后优雅终止；首个工具调用抛错后重试自愈；summarization 策略下多轮工具任务正常完成（`scripts/smoke_middleware.py`）。

## 示例

见 [examples/](examples/README.md)：`examples/quickstart.py`（最小程序化闭环）与 `scripts/smoke_*.py`（Runtime / HITL / MCP / HTTP API 四条端到端冒烟链路）。

## 项目结构

```text
src/agent_core/
├── api/             # FastAPI 传输层：路由、DTO、错误映射、SSE 事件流（/v1）
├── application/     # 用例层：AgentCoreService（API/CLI 共用的唯一入口）、组装根
├── bench/           # 评测基准：任务集、执行模式（single/team/fanout）、报告渲染
├── config/          # 环境变量配置（AGENT_CORE_ 前缀）
├── domain/          # 领域模型：Agent / Task / Run / Action / Tool / Skill / MCP / Trace / Team / Metrics
├── errors/          # 统一异常体系（带 retryable 标记）
├── eval/            # 真实任务评估：任务集、确定性校验器、执行器
├── mcp/             # MCP 适配：凭证解析、SDK 会话、连接生命周期、工具注册
├── observability/   # 日志、Tracer、EventBus、事件扇出、Run 级事件流（SSE 数据源）
├── orchestration/   # 编排：compose_team（模型驱动团队）、run_parallel（代码驱动并发）
├── permissions/     # ActionPolicy、ActionGate、ApprovalManager（工具执行必经闸门）
├── registries/      # Agent / Tool / Skill / MCP / Team 注册中心（内存实现）
└── runtime/         # 模型工厂、AgentBuilder、AgentExecutor、AgentRuntime（DeepAgents）、native middleware 映射

cli.py               # agent-core 命令行（serve / demo / API 客户端）
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
