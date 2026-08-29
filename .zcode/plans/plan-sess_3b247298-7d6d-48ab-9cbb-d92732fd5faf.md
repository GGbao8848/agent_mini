# Phase 19：代理 + Telegram 通知渠道（出站）

## 1. 代理配置（config/settings.py + .env）

- `.env`：`AGENT_CORE_PROXY_URL=http://10.10.10.214:7890`（复用现有 `apply_proxy` 机制，进程级 `HTTP_PROXY/HTTPS_PROXY`）。
- **关键**：新增 `AGENT_CORE_NO_PROXY`（Settings.no_proxy）——`apply_proxy` 在设代理的同时 `setdefault NO_PROXY`，并把 `localhost,127.0.0.1` 作为默认豁免。`.env` 中显式列出内网服务 `10.10.10.146,10.10.10.169`，保证本地模型/文生图**直连**，只有 Telegram 等外网流量走代理。
- `.env.example` 同步文档。

## 2. Telegram 通知模块（新包 `agent_core/notify/`）

- `notify/telegram.py`：`TelegramChannel`——`verify()`（getMe 验证 token）、`recent_updates()`（getUpdates，用于发现 chat_id）、`send_message(text)`（sendMessage）。httpx 默认 `trust_env`，自动走进程代理；网络错误包成 `ToolError(retryable=True)`。
- 配置沿用"标准环境变量"惯例：`TELEGRAM_BOT_TOKEN`（必填）、`TELEGRAM_CHAT_ID`（发消息必需；首次由引导脚本发现）。缺失配置报 `ConfigurationError`。
- **内置工具 `telegram_notify(message)`**：照 Phase 18 builtins 模式注册（配置齐了才注册），agent（你的分身）由此获得"给主人发消息"的能力，走正常 gate。将来接审批升级时直接复用这个工具/模块。

## 3. 引导脚本（`scripts/smoke_telegram.py`）

三步走，解决"还不知道你的 chat_id"：
1. `getMe` 验证 token → 打印机器人名；
2. 若 `TELEGRAM_CHAT_ID` 未设置：轮询 `getUpdates`（90 秒），提示你**在 Telegram 里给机器人随便发一条消息**；收到后打印 chat_id 并自动追加到 `.env`；
3. 发送测试消息"✅ agent-core Telegram 通道已接通"并确认。

## 4. 测试与文档

- `tests/unit/test_notify.py`：httpx.MockTransport 模拟 Bot API（发消息 URL/payload、getMe 解析、配置缺失报错、`register_builtin_tools` 条件注册 telegram_notify）；settings/apply_proxy 的 NO_PROXY 行为测试。
- README Phase 19 行 + 小节；记忆更新（机器人凭据存 `.env`，记忆只留提示）。

## 安全说明

Bot token 只进 `.env`（gitignored）。它已在对话中出现，建议之后在 @BotFather 用 `/revoke` 轮换一次。

## 验收

pytest/ruff/mypy 全绿；实机跑 `smoke_telegram.py`：代理连通 → 验证 token →（你给机器人发条消息）发现 chat_id → 收到测试消息。分支 `phase/19-telegram-notify` 合入 main。