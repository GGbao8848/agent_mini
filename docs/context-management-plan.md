# 上下文管理工程问题观察与修复计划（Phase 27）

分支：`feat/context-management`。目标：通过真实多轮对话 + 工具调用，实测 agent_core
在上下文管理上的工程问题（对照业界常见 15 类问题清单），逐项确认/修复/回归，
完成后合并 main。

## 系统现状（勘察结论）

- 历史 = LangGraph `AsyncSqliteSaver` 按 `thread_id` 全量重放；follow-up 只发新消息 +
  thread_id，**不做任何窗口化**（`runtime/executor.py:68-80`）。
- 图每 run 重建；系统提示每 run 重建但有界（`runtime/builder.py:71-105`）。
- 摘要：deepagents `SummarizationMiddleware` 常驻。本地/自定义端点无 model profile →
  触发阈值 **扁平 170k tokens**（`compute_summarization_defaults`）。本地 qwen3.8-27b
  vLLM `max_model_len=262144`，170k < 256k，能触发，但触发前每轮 prefill 已巨大。
- 工具结果截断：gate 层 `cap_text` 4000 字符（仅字符串）；`run_code` stdout/stderr 各
  8000 字符。**dict/list 结构化结果不截断**（`permissions/gate.py:301-305`）。
- checkpoint 库无清理：删除任务/运行不删 checkpoint 线程（生产库已 309MB/1.4 万行）。
- token 观测：`UsageCollector` 汇总进 run usage；无 per-call/per-turn 的上下文大小观测。

## 问题映射（15 类 → 本项目）

| # | 问题 | 本项目状态 | 实验验证 | 修复 |
|---|------|-----------|---------|------|
| 1 | Context 过长 | 全量重放 + 170k 才摘要 | R1 tokens 曲线/延迟 | R2 |
| 2 | Context 丢失 | sqlite checkpointer 重启恢复 ✓ | 既有单测 | — |
| 3 | 信息太多抓不住重点 | 超长历史无筛选 | R1 观察远轮引用 | 视观测 |
| 4 | 历史消息污染 | 摘要仅在 170k 后重写 | 同上 | 视观测 |
| 5 | Tool 返回太大 | 字符串已截断；**结构化未截断** | R1 构造结构化大返回 | R2 |
| 6 | 多 Agent 上下文传递 | 子代理 thread=None 隔离（有意） | — | — |
| 7 | 上下文重复 | 系统提示有界 | — | — |
| 8 | 长任务状态丢失 | 每超步 checkpoint ✓ | — | — |
| 9 | Context/Memory 混淆 | 无长期记忆模块 | — | — |
| 10 | Prompt 越写越大 | 有界 | — | — |
| 11 | Tool 太多 | MCP 19 工具 schema 占用 | 测量 system 大小 | 视测量 |
| 12 | 注入风险 | approval gate ✓ | — | — |
| 13 | 并发污染 | thread 隔离 ✓（有单测） | — | — |
| 14 | 不可观测 | usage 汇总有；per-turn 无 | R1 用 usage 曲线 | R2 补观测 |
| 15 | 恢复困难 | 重启恢复 ✓；孤儿线程问题 | R1 删除任务验证 | R2 清理 |

## 实验设计

- R1：隔离服务（8010，独立 db/workspace）。任务：生成大文件 + cat（大工具输出），
  随后 ≥4 轮跟问（每轮引用早轮内容并触发新工具）。记录每轮 run usage
  （input/output tokens）、耗时、checkpoints.db 尺寸、摘要是否触发、远轮内容引用情况。
- R2：按实测结果修复（预期：① 模型 ctx 感知/摘要阈值合理化；② 结构化工具结果截断；
  ③ 任务删除连带清理 checkpoint 线程；④ per-call 上下文观测），每项配测试。
- R3：重复 R1 验证效果（曲线回落/摘要触发/删除清理生效）。
- R4：补充修复 + 全量回归（pytest、mypy strict、控制台冒烟）→ 合并 main。
