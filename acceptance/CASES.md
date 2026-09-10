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

## 复现记录

（每条：Case ID / 命令 / 观察 / 根因 file:line / 判定）
