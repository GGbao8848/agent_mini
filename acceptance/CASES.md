# Runtime 边界验收用例（CASES）

来源：《Agent Runtime 验收书》+《工程化重构与验证指南》。
状态图例：⬜ 未开始 / 🔴 已复现（当前违规，红） / 🟢 已修复待验 / ✅ 验收通过。

## 不变量 ↔ 用例映射

| ID | 不变量 | 用例 | 状态 |
|---|---|---|---|
| I-01 | Agent 不能写只读 inputs | WS-001/004 | ⬜ |
| I-02 | Agent 不能改 Skill source | SKILL-002 | ⬜ |
| I-03 | Skill 不复制进每个 Task | SKILL-001 | ⬜ |
| I-04 | Agent 不能直接发布/安装全局 Skill | SKILL-005 | ⬜ |
| I-05 | Agent 不能直接访问 checkpoint 文件 | WS-006 | ⬜ |
| I-06 | Artifact 元数据独立于 workspace 扫描 | ART-001/003 | ⬜ |
| I-07 | 同一 Conversation 经 thread_id 延续 | CONV-001 | ⬜ |
| I-08 | 新 Conversation 不继承旧 thread 短期状态 | CONV-002 | ⬜ |
| I-09 | 新 Conversation 可召回相关长期 Memory | MEM-002 | ⬜ |
| I-10 | Memory 有显式 scope | MEM-004 | ⬜ |
| I-11 | Skill/tool 能力被真正强制（非仅 prompt） | SKILL-004 / TOOL-002 | ⬜ |
| I-12 | Agent 不能未经授权改 Control Plane 状态 | SEC-* | ⬜ |

## Runtime Hardening 2.0 不变量（R20–R24，2026-09-10）

| ID | 不变量 | 测试 |
|---|---|---|
| I-20 | 任务状态由事件投影（非 LLM 臆测） | `tests/runtime_boundary/test_task_state.py` |
| I-21 | 嵌套运行（验证器/子代理）事件不改任务状态 | 同上 |
| I-22 | 重启后状态被修正、不残留 running | 同上 + E2E 重启复验 |
| I-23 | 能力展示与运行时强制同源 | `tests/runtime_boundary/test_capabilities.py` |
| I-24 | agent 不能写 ORG / 无绑定项目的 PROJECT 记忆 | `tests/runtime_boundary/test_memory_governance.py` |
| I-25 | 记忆读取按 (scope, owner) 隔离 | `tests/runtime_boundary/test_memory_governance*.py` |
| I-26 | 执行/网络/环境信封显式且如实 | `tests/runtime_boundary/test_execution_policy.py` |

阶段报告见 `reports/stage-3.md`（PASS / P0=0，真实 E2E 发现 1 个 P2 已修）。

## 复现记录

（每条：Case ID / 命令 / 观察 / 根因 file:line / 判定）
