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
| 15 | 评估进阶：LLM-as-judge 四维质量评分 + 基线快照与回归对比（时间/token/质量漂移可见化） | ✅ |
| 16 | 持久化：SQLite 写穿透（注册中心/Run/审批/事件）+ 重启恢复，`AGENT_CORE_DATABASE_URL` 可选启用 | ✅ |
| 17 | 自治与预算治理：RunBudget 硬上限、循环/无进展检测、NEEDS_INPUT 任务级求助、执行后自检自修回路 | ✅ |
| 18 | 本地模型接入（`local:` provider，任意 OpenAI 兼容端点）+ 多模态内置工具（generate_image/view_image）+ 模型能力矩阵冒烟 | ✅ |
| 19 | 代理（`AGENT_CORE_PROXY_URL` + NO_PROXY 豁免内网服务）+ Telegram 通知渠道（telegram_notify 工具 + chat_id 引导脚本） | ✅ |
| 20 | run_code 内置工具 + workspace 真实文件 backend + 双长任务端到端自治验证（30 页 PPT / 网页画册） | ✅ |
| 21 | Podman Sandbox：run_code 容器内执行（仅挂载 workspace、资源上限、rootless），宿主机密钥不可达 | ✅ |
| 22 | Agent Console：局域网 Web 控制台——Run 时间线（持久化历史+实时 SSE）、事件详情、产物预览/下载、审批面板、派任务 | ✅ |
| 23 | 多轮对话：LangGraph checkpointer + thread_id，**任意 run 可续聊**（AsyncSqliteSaver 持久化，跨重启保留上下文） | ✅ |
| 24 | Console 工具箱：Skills/MCP 安装与管理 UI（MCP 以 JSON 录入为主 + 表单备选，兼容标准 mcpServers 格式），MCP 连接生命周期修复（owner-task），Agent 工具/技能绑定（PUT /v1/agents/{id} + 工具箱面板） | ✅ |

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

## 评估进阶：LLM-as-judge + 基线回归（Phase 15）

在确定性校验器之上补齐两个持续治理工具：

- **LLM-as-judge**（`eval/judge.py`）：评审员本身就是一个注册 Agent（rubric 放在 system prompt，执行复用正常 Run 机制，不新增执行路径），按 accuracy / completeness / conciseness / instruction_following 四维打 0-10 分。确定性校验器证明硬事实，judge 补软质量信号。`EvalRunner.run_judge()` 挂到 `EvalResult.judge`。校准要点（首跑教训）：数据真伪归确定性校验器管，judge 不因"看不到工具调用记录"扣分；输入注入评审日期避免"未来日期"误判；解析器对内嵌引号的破损 JSON 有正则回退。
- **基线回归**（`eval/baseline.py`）：一次运行的指标（通过率/耗时/token/checks）存为纯数据 JSON，后续运行逐任务对比：质量回退/提升、耗时或 token 超出 ±25% 容差判 regressed；渲染对比表，任何 regressed 令脚本非零退出（可直接接 CI）。

```bash
uv run --env-file .env python scripts/eval_real.py --suite fx --judge --save-baseline eval_results/baseline.json
uv run --env-file .env python scripts/eval_real.py --suite fx --judge --compare eval_results/baseline.json
```

实测（minimax-m3:free）：judge 稳定输出 6.5–7.6/10 的合理评分与中肯点评；基线对比把运行间漂移显式化——同一 fx 任务相邻两次运行即得到 `single 📈 improved (wall -55%, tokens -70%)` 与 `team 📉 regressed (wall +90%)` 的结论（team 质量未退、checks 3/3，速度波动被准确捕获）。附带的 team 调优延续：COORDINATOR_PROMPT 的 DELEGATE 步骤新增"实时数据必须来自 worker 自己的工具调用，不得凭记忆回答"，堵住 worker 跳过工具直接编数的路径。

## 持久化（Phase 16）

设置 `AGENT_CORE_DATABASE_URL=sqlite:///./agent_core.db` 后，所有可持久化事实经由 `persistence/`（仅标准库 `sqlite3`，WAL 模式）**写穿透**到 SQLite，进程重启后自动恢复：

| 持久化对象 | 机制 | 重启后语义 |
|---|---|---|
| 注册中心（Agent/Tool 定义/Skill/MCP/Team） | `BaseRegistry` 写穿透 + `hydrate()` | 原样恢复；Tool 只恢复定义，handler 由代码重新注册；MCP 服务器恢复为待重连 |
| Run / Task 记录 | `AgentRuntime` 在 create/transition 时保存 | 终态 run 原样可查；非终态 run 标记 `FAILED`（interrupted by process restart） |
| Trace 事件 | `PersistingTracer` 双写（内存读 + 库镜像） | 重启后 SSE 回放与 `final_output` 仍然可用 |
| 审批请求 | `ApprovalManager` 写穿透 | 已决审批原样保留；遗留 pending 自动置 `REJECTED`（resolved_by=restart，其 run 已无法恢复） |

设计要点：内存 dict 始终是读侧唯一来源（读性能不变、契约不变），库只是镜像；不设置该变量时行为与纯内存 v1 完全一致。**不解决执行恢复**——WAITING_APPROVAL 的 run 其图状态与进程内唤醒句柄不可序列化，跨重启恢复执行需接入 LangGraph checkpointer（远期）。

## 代理与 Telegram 通知（Phase 19）

### 进程级代理

```bash
AGENT_CORE_PROXY_URL=http://10.10.10.214:7890   # → HTTP_PROXY / HTTPS_PROXY
AGENT_CORE_NO_PROXY=10.10.10.146,10.10.10.169   # 内网服务（本地模型/文生图）直连豁免
```

`apply_proxy` 在设置代理时总是把 `localhost,127.0.0.1,::1` 加入 `NO_PROXY`，并追加 `AGENT_CORE_NO_PROXY` 主机——代理只覆盖 Telegram 等外网流量，本地方向不受影响。

### Telegram 出站渠道

| 项 | 说明 |
|---|---|
| 配置 | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`（标准环境变量，凭据不入库） |
| 首次绑定 | `uv run --env-file .env python scripts/smoke_telegram.py`：getMe 验证 token → 轮询 getUpdates 发现你的 chat_id（自动写入 .env）→ 发送测试消息 |
| Agent 工具 | 内置 `telegram_notify(message)`：配置齐全后自动注册，agent 在 `spec.tools` 里声明即可给主人发消息，照常走 Action Gate |
| 实现 | `agent_core/notify/telegram.py`：httpx `trust_env` 自动走进程代理；网络错误为 retryable `ToolError` |

## Podman Sandbox（Phase 21）

"分身"技术栈的三层边界从此完整：

```text
Runtime（大脑：决策/治理/自检）  → 已成熟
Workspace（工作台：文件视图）    → Phase 20，锁定在 workspace/
Sandbox（执行隔离：代码跑在哪）  → Phase 21，rootless Podman 容器
```

```bash
AGENT_CORE_SANDBOX=podman                       # 默认 none（宿主机直跑，向后兼容）
AGENT_CORE_SANDBOX_IMAGE=localhost/agent-core-sandbox:latest
AGENT_CORE_SANDBOX_MEMORY_MB=2048  AGENT_CORE_SANDBOX_CPUS=2.0  AGENT_CORE_SANDBOX_PIDS_LIMIT=256
bash scripts/sandbox_build.sh                   # 构建镜像（python:3.13-slim + pptx/Pillow/pandas + CJK 字体）
```

启用后 `run_code` 的每条命令都在容器内执行：**只有 workspace 挂载进容器**（`/work`）——宿主机的 `.env` 密钥、SSH、git 历史全部不可达；路径穿越（`/work/../..`）只到容器自己的根；内存/CPU/进程数有硬上限；代理环境变量透传（pip 装包走代理）。workspace 成为 agent 与宿主机之间的唯一交换点。已实测验证：边界四项检查全过 + 沙箱模式下真实任务（mini pptx + Telegram 汇报）端到端完成。

## 工具箱：Skills / MCP 安装与管理（Phase 24）

Console 顶部切换 **任务台 / 工具箱**。工具箱 = MCP 服务器面板 + Skills 面板，注册表已持久化（重启不丢）。

**MCP（JSON 优先）**：添加服务器默认是 JSON 粘贴框（含模板与校验：transport 只允许 `streamable_http`/`stdio`），表单模式为备选。列表页有状态徽章、连接/断开/删除按钮、发现的工具计数。凭据只存 `auth_ref` 引用名，连接时从服务器环境变量解析，密钥不过前端。

**Skills**：安装 = 把技能目录（内含 `SKILL.md`）放到服务器磁盘后，在表单里登记路径；列表可查看版本与路径、可删除。

两个底层修复：① MCP 连接改由**专属 owner task** 持有 SDK 会话——uvicorn 每个请求都是新任务，而 anyio 禁止跨任务退出 async 上下文，旧实现跨请求关闭会话必崩；② SqliteStore 开启跨线程访问 + 写锁（同步路由跑在线程池）。

**绑定到 Agent（工具箱闭环）**：工具箱 Agents 面板（或 `PUT /v1/agents/{id}`，传 `tools`/`skills`，省略字段保持不变）可随时把已连接 MCP 的工具与已安装技能挂到任意 agent，改动立即生效（下次 build 生效），并持久化（重启不丢）。绑定 skill 时 runtime 把技能目录**同步拷贝**到 `workspace/.skills/<agent_id>/`——DeepAgents 的技能与文件工具共用一个 backend，以 workspace 为根可同时保住文件工具的 workspace 语义、SKILL.md 的渐进披露可见性、以及技能脚本对 run_code 沙箱（workspace 挂载）的可见性。实机验证：avatar 绑定 mem0 两个工具 + demo 技能后，一轮任务内完成记忆写入（mem0_add_memory）与按 SKILL.md 格式的问候输出。

## 多轮对话（Phase 23）

**每个 run 天生自带对话线程**（`thread_id` = 自己的 id，对话状态经 LangGraph checkpointer 持久化到 `agent_core.db`）。在 Console 的任意 run 详情页输入框直接续聊——"把第 5 页改成……"、"刚才那个文件再补充一点"——agent 带着该 thread 的全部历史继续干活，产物实时进产物窗口。跨重启后依然记得全部上下文（AsyncSqliteSaver）。

```bash
# 程序化续聊
curl -X POST "http://<server>:8000/v1/runs/<run_id>/messages" \
  -H 'Content-Type: application/json' -H "X-Console-Token: $TOKEN" \
  -d '{"input": "把标题页日期改成今天"}'
```

- 根 run 拥有线程；子 run（验证器等）不携带，避免污染对话历史
- 同一 thread 的多次 run 在时间线上标 🔗，详情页显示完整对话转录
- 已知语义变化：`ResiliencePolicy.model_call_limit`（thread_limit）从"每 run 归零"变为"跨轮累计"（阶段预算 RunBudget 不受影响，仍按 run 记账）

## Agent Console（Phase 22）

```bash
uv run --env-file .env python scripts/serve_console.py   # 默认 0.0.0.0:8000
# 然后在局域网任意机器的浏览器打开：
#   http://<服务器IP>:8000/console/
```

一次解决"agent 在服务器上，人在别的机器"的三个痛点：

| 痛点 | Console 能力 |
|---|---|
| 交付物要 ssh 上去找路径拷贝 | **产物窗口**：run 收尾自动登记 workspace 新增文件（manifest 写入 run 元数据并持久化），图片缩略图直接预览、其余一键下载（路径严格限制在 workspace 内，穿越/隐藏文件拒绝） |
| 不知道它之前/现在在干嘛 | **时间线**：历史 run 来自 SQLite（重启不丢），进行中的 run 通过全局 SSE 实时刷新状态徽章；详情页有逐条事件时间线、token 用量、自检结果、最终输出 |
| 危险操作/求助需要人工 | **审批面板**：工具审批与任务级求助（NEEDS_INPUT）在页面上批准/驳回/填写给分身的答复 |

派任务也在页面顶部完成（选 agent → 写任务 → 提交，立即出现在时间线上）。安全：设置 `AGENT_CORE_CONSOLE_TOKEN` 后所有 `/v1` 与 `/console` 请求需携带 token（页面首次提示输入，存 localStorage）；不设置则局域网内开放。

## 本地模型与多模态工具（Phase 18）

### 模型工厂：`local:` provider

任意自托管 OpenAI 兼容端点（vLLM / llama.cpp server / LMDeploy…）与 `openai:` / `openrouter:` 走同一工厂路径，fallbacks / resilience / judge 全部兼容：

```bash
# .env（凭据走标准环境变量，不入库）
LOCAL_LLM_BASE_URL=http://10.0.0.5:8000/v1
LOCAL_LLM_API_KEY=optional          # 本地服务常无鉴权，可省略
```

```python
AgentSpec(id="avatar", model="local:qwen3.8-27b", ...)
AgentSpec(id="avatar", resilience=ResiliencePolicy(
    model_fallbacks=["local:qwen3.8-27b", "openrouter:minimax/minimax-m3:free"]), ...)
```

### 内置多模态工具（`agent_core/builtins/`）

| 工具 | 启用条件 | 说明 |
|---|---|---|
| `generate_image(prompt, width, height, steps, cfg_scale)` | `AGENT_CORE_IMAGE_API_BASE_URL`（A1111/Forge 兼容 `/sdapi/v1/txt2img`） | 生成 PNG 存入 `AGENT_CORE_WORKSPACE_DIR`（默认 ./workspace），返回绝对路径 |
| `view_image(path)` | 始终注册 | 返回多模态内容块（text + image_url data URI），视觉模型可直接"看到"图片——包括查看自己刚生成的图 |

工具照常走 Tool Registry → Permission → Action Gate，agent 按 `spec.tools` 白名单选用。

### 模型能力矩阵冒烟

```bash
uv run --env-file .env python scripts/smoke_model_matrix.py [--strict]
```

所有探测走**本项目的 `build_model()` 工厂**（即生产适配路径）：补全 / 工具调用 / 严格 JSON / 用户消息视觉 / **工具结果视觉**（agent 看图链路）五项，输出矩阵表；`--strict` 任一失败退出非零可直接接 CI。实测（qwen3.8-27b 本地）：5/5 全过，含工具结果带图路径。

端到端演示（画图 → 看图自查 → 描述确认）：

```bash
uv run --env-file .env python scripts/demo_multimodal.py
```

**附带修复的适配器 bug**：gated 工具路径此前未应用"模型省略的可选参数回退 handler 默认值"规则，`None` 会直接传给 handler（generate_image 收到 `width: null` 即 500）。现已统一在执行链路处理并有回归测试覆盖。

## 自治与预算治理（Phase 17）

面向"AI 分身"定位：长任务不失控、不空转、该问人就问人。全部能力由 `AgentSpec.autonomy`（`AutonomyPolicy`）声明，默认 None = 行为与之前完全一致：

| 能力 | 声明 | 行为 |
|---|---|---|
| 预算硬上限 | `autonomy.budget`（max_total_tokens / max_model_calls / max_tool_calls / warn_fraction） | 自定义 `BudgetMiddleware` 在每次模型调用前检查实时用量（run 级 `UsageCollector` 注册表）：到 warn 阈值向 system prompt 注入"尽快收尾"；到硬上限按原生 `jump_to end` 模式**优雅收尾**（run 正常完成并附说明），绝不报错死。`AgentLimits.token_budget` 旧占位字段同时接通为兜底 |
| 循环/无进展检测 | `autonomy.loop_guard`（max_identical_calls=3 / max_consecutive_failures=3） | Action Gate 在执行前按 run 记账工具调用指纹：第 N 次同参数调用被**软拒绝**（"你在空转，换方法"作为工具结果返回给模型），第 N+1 次升级人工；配置 loop_guard 后工具失败也从"杀 run"变为软消息（先自愈再升级） |
| 任务级求助 | 内置 `request_help(question)` 工具（配置任意 autonomy 自动注入，含 subagent） | 新增非终端状态 `NEEDS_INPUT`：agent 主动停下等人工，人工答复（审批的 `note`）作为工具结果回流继续执行；循环升级、自检失败升级共用此通道。重启后遗留 NEEDS_INPUT/WAITING_APPROVAL 仍按 Phase 16 语义标 FAILED（执行恢复属 Phase 18 checkpointer） |
| 执行后自检 | `autonomy.verification`（min_overall=7.0 / max_rounds=1 / on_fail="escalate"\|"accept"） | 输出完成后由 judge agent（内置 `verifier`，惰性注册）以嵌套 Run 打分（用量聚合回父 run）；不合格先自修最多 N 轮（把评审反馈拼进任务重跑同一 graph），仍不合格升级人工（人工答复引导最后一轮）或标记未验证完成。结果写入 `run.metadata["verification"]` |

```python
AgentSpec(
    id="avatar", name="Avatar",
    autonomy=AutonomyPolicy(
        budget=RunBudget(max_total_tokens=200_000),
        loop_guard=LoopGuardPolicy(),
        verification=VerificationPolicy(enabled=True),
    ),
)
```

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
├── persistence/     # 可选 SQLite 写穿透：注册中心/Run/审批/事件 + 重启恢复
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
