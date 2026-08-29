# Agent Core 架构

> 状态：全部核心 Phase 已落地（Domain / Registry / Runtime / Gate / 事件流 / MCP / HTTP API / CLI）。

## 分层

```text
┌─────────────────────────────────────────────┐
│  API (FastAPI)            — Phase 7         │  HTTP → Schema → Application Service
├─────────────────────────────────────────────┤
│  Application             — Phase 7          │  业务编排（RunService / ActionService …）
├─────────────────────────────────────────────┤
│  Agent Runtime           — Phase 3          │  统一生命周期、执行编排
├─────────────────────────────────────────────┤
│  Registries              — Phase 2          │  Agent / Tool / Skill / MCP
├─────────────────────────────────────────────┤
│  Permission → Action Gate — Phase 4         │  安全边界，工具执行前强制经过
├─────────────────────────────────────────────┤
│  Infrastructure                             │  DeepAgents / LangGraph / MCP SDK / API
└─────────────────────────────────────────────┘
        ▲
        │ 依赖倒置：Domain 定义接口，Infrastructure 实现
┌─────────────────────────────────────────────┐
│  Domain（已落地）                            │  纯数据 + 规则，零第三方框架依赖
│  agent / task / action / tool /             │
│  permission / skill / mcp / trace           │
├─────────────────────────────────────────────┤
│  横切（已落地）                              │
│  config（环境变量）errors（统一异常）        │
│  observability（logger / Tracer / EventBus） │
└─────────────────────────────────────────────┘
```

依赖方向严格单向：`API → Application → Domain ← Infrastructure`。Domain 不允许 import FastAPI、LangChain、DeepAgents、MCP SDK、数据库驱动。

## 系统架构图

```mermaid
flowchart TB
    API[FastAPI API] --> APP[Application Services]
    APP --> RT[Agent Runtime]
    RT --> AR[Agent Registry] & SR[Skill Registry] & MR[MCP Registry]
    RT --> DA[DeepAgents / LangGraph]
    DA --> TL[Tool Layer]
    TL --> PM[Permission Policy]
    PM --> AG[Action Gate]
    AG --> TE[Tool Executor]
    TE --> PT[Python Tool] & MCPS[MCP Server]
    PT & MCPS --> BS[Business Systems]
    State[State / Memory] -.-> RT
    Trace[Trace / Events] -.-> RT
```

## Agent 执行流程

```mermaid
sequenceDiagram
    participant U as User
    participant R as Runtime
    participant D as DeepAgents
    participant T as Tool Layer
    U->>R: run(agent, input)
    R->>R: Run CREATED → RUNNING
    R->>D: invoke (agent loop / planning)
    D->>T: tool call
    T->>T: Permission → Risk → Action Gate
    alt 需要审批
        R-->>U: WAITING_APPROVAL (interrupt)
        U->>R: APPROVE / REJECT / EDIT
        R->>T: 继续或终止
    end
    T-->>D: tool result
    D-->>R: result
    R->>R: Run COMPLETED
    R-->>U: result + trace
```

## Tool 调用链（含 HITL）

```mermaid
flowchart LR
    A[Agent] --> TC[Tool Call]
    TC --> PE[Permission Evaluation]
    PE -->|DENY| X[拒绝，不执行]
    PE --> RE[Risk Evaluation]
    RE --> AG[Action Gate]
    AG -->|LOW / MEDIUM| EX[Tool Execution]
    AG -->|HIGH / CRITICAL| AP[ApprovalRequest]
    AP -->|APPROVE| EX
    AP -->|REJECT / CANCEL| X
    AP -->|EDIT| EX
    EX --> RES[Result]
```

## 统一 Run 生命周期

```text
CREATED → PLANNING → RUNNING ⇄ WAITING_APPROVAL → COMPLETED
                 ↘ FAILED / CANCELLED / TIMEOUT（终态）
```

状态机在 `domain/task.py` 中用显式转移表实现，非法转移抛 `StateError`。

## 关键决策记录

- **复用 DeepAgents**：agent loop、subagents、skills 加载、HITL interrupt/checkpoint 全部复用；Agent Core 只做 Registry、Policy、Gate、Trace、API。
- **错误模型**：所有异常继承 `AgentError`，携带 `retryable` 标记；工具层不向 Agent 泄漏原始 Python 异常。API 层一次性把异常映射为 `{"error": {code, message, retryable, details}}`。
- **安全**：MCP 凭据只存 `auth_ref` 引用，连接时经 `CredentialResolver` 从环境解析；模型 API key 由 provider SDK 标准环境变量管理。所有工具（本地 Python 与 MCP）都经同一条 Permission → Action Gate 链路。
- **传输层极薄**：`AgentCoreService` 是 API/CLI 共用的唯一用例入口；`create_app` 支持注入自定义 service，路由无状态。
- **第一版不引入**：Kafka / Redis / PostgreSQL / 向量库 / 微服务，单进程可运行。
- **持久化（Phase 16）**：可选 SQLite（标准库 `sqlite3`，WAL）作为**写穿透镜像**——内存 dict 始终是读侧唯一来源，`AGENT_CORE_DATABASE_URL` 设置后注册中心/Run/审批/Trace 事件落库并在启动时恢复；跨重启的执行恢复（LangGraph checkpointer）仍属远期。
- **自治层（Phase 17）**：预算/循环检测/求助/自检全部是声明式的 `AgentSpec.autonomy` 纯数据 + 运行时三个挂钩点——中间件（Budget，复用原生 `jump_to end` 收尾模式）、Action Gate（LoopGuard 与 `request_help`，gate 仍是工具执行的唯一通道）、Run 收尾回路（verification 嵌套 judge run）。治理动作优先"软反馈给模型"，只在确认无进展时升级人工（`NEEDS_INPUT`），审批答复经同一 ApprovalManager 通道回流。
- **Sandbox（Phase 21）**：`run_code` 支持 podman 后端（`AGENT_CORE_SANDBOX=podman`）——rootless 容器仅挂载 workspace、资源受限、代理透传，宿主机密钥与文件系统不可达；workspace 是 agent 与宿主机的唯一交换点。自定义中间件必须同时实现 sync 与 async 钩子（运行时全 async，LangChain 无回退）。已知缺口：deepagents 文件工具（write_file 等）未纳入 Gate/事件系统，按路径约束在 workspace 内，远期收编到 SandboxBackendProtocol。
