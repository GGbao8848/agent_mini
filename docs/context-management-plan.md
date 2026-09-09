# 上下文工程手册：问题清单、实测与解决方式（agent_mini）

> 独立参考文档：记录本项目上下文管理（Context Engineering）的全部工程问题、
> 实测数据与解决方式。随优化持续推进更新。勘察/实验基线：2026-09-08/09（Phase 27）。

## 架构现状（一句话）

FastAPI → AgentCoreService → AgentRuntime → AgentBuilder（每 run 编译 deepagents 图）
→ AgentExecutor 以 `thread_id` 调用 → LangGraph `AsyncSqliteSaver` 持久化全量消息状态，
follow-up 只发新消息 + thread_id，由 checkpointer **全量重放**历史。上下文窗口化/摘要
完全委托给 deepagents 的 SummarizationMiddleware。

## 问题→解决方式总表（持续更新）

| # | 问题 | 根因 | 解决方式 | 状态 | 提交/文件 |
|---|------|------|---------|------|----------|
| 1 | **token usage 恒为 0**：预算控制失效、UI 恒 0、增长不可观测 | langchain-openai 只对官方 OpenAI base URL 默认开 `stream_usage`，自定义端点（vLLM）流式响应不带 usage | `build_model` 对 custom/local/openrouter 强制 `stream_usage=True` | ✅ | `4755550` runtime/model.py |
| 2 | **API 白名单剥离新字段**：领域模型加字段后 API 静默丢弃（gauge 恒空环） | `RunUsageOut` 是字段白名单，新字段未同步 | 同步 wire schema + 回归测试（领域模型过一遍 RunOut 序列化断言字段存在） | ✅ | `16b2c73` api/schemas.py + test_usage.py |
| 3 | **结构化工具结果不限长**：dict/list 绕过 cap_text，一次 verbose 工具污染后续所有 prefill | gate 只对 str 截断 | `cap_result`：dict/list 序列化后限额，超限替换为截断字符串（限额内保持原结构）；顺带修 `cap_text` 的 `value[-0:]` 反向膨胀 | ✅ | `4755550` runtime/text.py + gate.py + test_text.py |
| 4 | **checkpoint 永久孤儿**：删任务不删 LangGraph 线程（生产 309MB/1.4 万行） | delete_task 只清业务表 | delete_task 连带 `adelete_thread` + 启动时孤儿 GC（lifespan 调 `cleanup_orphan_checkpoints`，生产首次启动回收 33 个孤儿线程；WAL 下文件不物理收缩，空间复用，可手动 VACUUM） | ✅ | `4755550` + `ff15198` runtime.py + app.py + test_sessions.py |
| 5 | **摘要阈值与真实窗口错配**：无 model profile 时 deepagents 用扁平 170k 触发 | 自定义端点无 profile | `CustomModel.context_window` → 注入 `profile={"max_input_tokens": …}` → 摘要按真实窗口 fraction 0.85 触发 | ✅ | `4755550` + `ff15198`（配置页 UI 录入）model_config.py + model.py + add-model-dialog.tsx |
| 6 | **上下文增长不可见**：用户看不到对话占了多少窗口、花在哪 | 无 per-call 快照指标 | `RunUsage.last_input_tokens`（最近一次调用 input ≈ 当前上下文）+ `estimated_system/messages_tokens`（on_chat_model_start 按 CJK 启发式拆 system/历史）+ `run.metadata.context_breakdown`（构建时静态估算工具 schema/技能清单） | ✅ | `2481005`/`6d19a9f` metrics/usage/builder/context_breakdown.py |
| 7 | **控制台无容量指示**：用户不知道何时该开新对话 | — | Composer 上下文圆环（灰黑单色）+ 悬停白底明细面板（消息/系统提示词/系统工具/MCP工具/技能/其他 各行占比） | ✅ | `2481005`/`6d19a9f`/`c48ecd4` chat/context-gauge.tsx |
| 8 | **发消息瞬间归零闪断**：新 run 无 usage，gauge 切过去读了个空 | gauge 只读 active run | 回退遍历最近 run 取最近一个带快照的，标注"（上一轮）"，新值到达后无缝切换 | ✅ | `c48ecd4` context-gauge.tsx |
| 9 | 上下文过长（全量重放、prefill 逐轮变大） | 无窗口化；摘要 170k 才触发 | 已可观测（#6/#7）；阈值已可配（#5）。实测 turn5 单跳 8.5k tokens（5 轮），生产 7 轮 14k→62k | 🟡 可观测/可控，未做主动压缩 | — |
| 10 | 信息太多抓不住重点 / 历史污染 | 长历史无筛选 | 未处理。方向：spec 级 SummarizationPolicy（已有机制，`keep_messages` 可配）实测 + 提示词引导 | ⏳ | — |
| 11 | checkpoint 每超步全量快照存储放大 | LangGraph 固有 | 靠 #4 清理；长对话摘要重写状态会自然收缩 | 🟡 接受 | — |
| 12 | **长期记忆缺失**：跨会话知识（用户偏好/项目约定）不带过来 | 无记忆模块 | ⚠️ **已尝试并回退**（`8b68e99`/`1f4aa13`）：扁平列表+面板+save_memory+每轮自动提炼全链路打通，但实测不好用——每轮提炼有成本与重复噪音，agent 主动调用不稳定。教训：记忆的价值在"准"不在"全"，重试方向是**会话级提炼**（结束时一次、内容更聚焦）或显式指令驱动（"记住这个"）而非每轮自动跑 | 回退 | — | domain/memory.py + builtins/memory.py + api/routes/memories.py + views/memory-view.tsx |

## 实测数据（隔离环境 R1/R3 + 生产验证）

- R1（修复前）：5 轮 usage 全 0；checkpoint 5 轮 0→1.37MB（每轮 +220~330KB 递增）。
- R3（修复后）：usage 曲线 21101/13823/14522/24486/8558（turn5 单跳 8.5k = 全量重放
  prefill 实测）；删任务后 checkpoint rows=0。
- 生产（`16b2c73` 后）：7 轮会话 input 14329→14533→144361→59377→62038；新 run
  `last_input_tokens=23854` 正常返回。
- 对话质量：5 轮内远轮记忆（文件名/内容特征）全部正确；多代理隔离/并发隔离/重启恢复
  均有既有单测覆盖。

## 关键经验（踩坑记录）

1. **wire schema 是白名单**：领域 pydantic 模型加字段，必须同步 `api/schemas.py` 的
   Out 模型，否则 API 静默剥离。回归测试：领域实例过一遍 Out 序列化断言新字段。
2. **langchain-openai 的流式 usage 默认关**（非官方端点）：必须显式 `stream_usage=True`。
3. **react adapter 的 effect 依赖含回调引用**：传给 FileViewer 的 onError 等必须
   useCallback/memo，否则每次重渲染整个 viewer 重建（预览面板拖拽踩过）。
4. **cap_text 的 `value[-0:]` 等于全串**：keep_head >= max_chars 时会反向膨胀。
5. **本地 vLLM qwen3.8-27b**：`max_model_len=262144`；端点 `http://10.10.10.146:8001/v1`。
6. 启动顺序坑：`uv run` 服务必须用持久后台方式启动（shell `&` 会随会话退出被杀）；
   pkill 匹配串含在自身命令行时用 `[s]erve_console` 防自杀。

## System 侧瘦身边际实测（P1.1 条目级量化）

对真实 avatar graph（生产 db 副本 + 记录型 fake model）做条目级拆解：

| 组成 | ≈tokens |
|------|---------|
| System message（avatar 提示 + autonomy + 运行环境 + 技能 manifest 段） | 1738 |
| 核心 harness/builtin 工具 schema（9 个：grep 571 / task 433 / read_file 429…） | 2672 |
| service 工具（ensure_packages/install_skill/create_schedule/request_help） | ~500 |
| **MCP 工具 schema（31 个，tinyfish 为主）** | **12188** |
| 合计固定开销 | **≈17k** |

两个假设被数据修正：① 技能文档**并非**全量注入——deepagents 的 SkillsMiddleware
本来就是 manifest 化（name + description + 读取路径），无需改造；② 真正的大头是
**MCP 工具 schema**：31 个注册工具共 12.2k tokens（70%），而生产 trace 显示历史上
只有 2 个 MCP 工具被调用过（tinyfish_search 20 次、fetch_content 6 次）。

落地：`MCPServerDefinition.exposed_tools` allowlist（None=全暴露兼容旧行为），
connect 时过滤 + 收窄时清理旧注册，`PATCH /v1/mcp/servers/{id}` 编辑并自动重连
即时生效。生产已配 tinyfish allowlist=[search, fetch_content]：注册工具 35→18，
预计每轮 prefill 固定开销下降 ≈9-10k tokens。

## 摘要触发实测（summlab 实验，trigger_tokens=1500 / keep_messages=4）

用低阈值测试 agent 跑 3 轮大工具输出对话（生成 20KB 文件 + cat 全文 ×2）：

1. **摘要真实触发且有效**：turn1 多次调用累计 input 39743（历史远超阈值），
   turn2 的 input 骤降到 **14965（-62%）**——历史确实被摘要重写，证明
   SummarizationMiddleware 在本项目链路里端到端工作。
2. **keep_messages 窗口保住近轮细节**：keep=4 下，最近的 cat 结果（gate 截断后
   头部 2000 字符含 marker）留在窗口内，紧邻两轮的无工具回忆探针全部答对。
   远轮损失需要更长链路才能观测（预期：窗口轮转后早期细节只剩摘要概述）。
3. **摘要后仍占 ~15k**：大头不是对话历史，而是 system 侧固定开销（工具 schema +
   技能文档注入）——与控制台 breakdown 面板的分布一致。**压缩对话历史的边际
   收益有限，优化系统提示/工具清单才是下一块大头**（#10/#11）。
4. 未发现 offload 文件落在 task 目录（deepagents 的 conversation_history 路径
   在本项目布局下未显现，待查）。

## 手动压缩上线（compact，真实会话验证）

`POST /v1/tasks/{id}/compact`：强制把 thread 压为摘要 + 最近 6 条；原始历史
offload 到任务目录 markdown（17 轮生产会话实测：26 条消息 → 7 条，摘要 936 字，
offload 197 行，压缩后 follow-up 正常且能复述会话主题）。拒绝运行中任务。
控制台对话头部新增「压缩」按钮（确认框 + 前后条数 toast）。

## 修复：MCP 启用开关是"假开关" + save_memory 僵尸工具

- **开关语义拍板**：连接与启用不分离，一个开关=连接总开关——开→立即连接，
  关→立即断开且开机不再自动连；工具随连接注册/注销，agent 运行时自然不可见。
  曾做过"关了仍保持连接、仅运行时屏蔽"的方案，用户否决（过度设计），回退为简单语义。
- **假开关根因**：`MCPServerUpdateRequest` 没有 `enabled` 字段，前端 PATCH
  `{enabled:false}` 被 pydantic 静默丢弃 → 空 patch 落进 `was_live` 分支 → 表现为
  "一关就莫名断开重连"。另 `auto_connect_all` 缺 `continue`，disabled 服务器开机
  照样连接。修复 `be9dc3f`。
- **save_memory 僵尸**：记忆系统回退后其内置工具仍在线——注册表 write-through
  持久化 + `hydrate()` 全量回灌复活了 store 里的旧行。`ToolRegistry.hydrate` 改为
  只回灌 `source=mcp`（handler 由 connect 重挂），代码自有工具以代码为准、过期行
  从 store 清除。生产 18→17 个工具。修复 `e56ddf0`。
- 教训（wire schema 白名单陷阱第二次咬人）：请求/响应模型没有的字段，pydantic
  默认静默丢弃不报错——领域模型加字段必须同步 API 模型，并用 curl 打真实端点验证。

## 下一步（Backlog，按价值排序）

1. ~~模型配置页 context_window 输入框~~ ✅ `ff15198`
2. ~~启动时孤儿 checkpoint GC~~ ✅ `ff15198`（生产首次启动回收 33 线程）
3. ~~摘要触发实测~~ ✅（见上节）。
4. ~~提示词引导 + 内容信任边界~~ ✅（environment_note 读片段引导 + `<untrusted-content>`
   信任边界，MCP 结果包裹 + 系统提示声明"数据非指令"）。
5. ~~长期记忆分层~~：⚠️ 最小记忆系统已回退（见 #12 行的教训）；aimemory MCP 维持下线。重试需换设计。
6. 远期：历史筛选/压缩策略（#10）。
