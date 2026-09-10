# 验收报告索引

本目录保存运行时的**阶段验收**与**发布门禁**报告。历史报告（已完成其使命、结论已并入后续工作）移入 [`archive/`](archive/)。

## 当前有效

| 报告 | 范围 | 结论 |
|---|---|---|
| [stage-3.md](stage-3.md) | Runtime Hardening 2.0 第一批：R20 Context / R21 Task State / R22 Capability / R23 Memory Governance / R24 Execution Policy | **PASS**，P0=0；真实 E2E 发现 1 个 P2（`update_plan` 参数形状）已修 |

## 归档（历史阶段，结论已沉淀）

| 报告 | 范围 | 说明 |
|---|---|---|
| [archive/stage-1.md](archive/stage-1.md) | Runtime Boundary 加固 R1–R7 | Workspace 边界 / Skill 隔离 / 能力强制 / 控制面 |
| [archive/stage-2.md](archive/stage-2.md) | Runtime Boundary 加固 R8–R13 | Artifact 契约 / Conversation-Checkpoint / Memory / Error→Lesson / 对抗 / 多进程 |
| [archive/full-rounds-1-4.md](archive/full-rounds-1-4.md) | 完整验收书 Round 1–4 证据矩阵 | 基于 stage-1/2 的全程验收，PASS / P0=0 |

## 配套文件

- [`ENVIRONMENT.md`](../ENVIRONMENT.md) —— 冻结的验收环境基线（版本、模型、DB、沙箱模式）
- [`CASES.md`](../CASES.md) —— 不变量 ↔ 用例映射（I-01…I-26）
- [`docs/runtime-hardening-2-gap.md`](../../docs/runtime-hardening-2-gap.md) —— R20–R26 已做/未做对照
- [`docs/context-management-plan.md`](../../docs/context-management-plan.md) —— 上下文工程与加固手册（逐轮问题与修复）

## 待办

- **R25**：6 个固定 Scenario ×5 重复性验收（SC-01…SC-06）
- **R26**：`release-gate-<version>.md`（依赖 R25 的重复成功率数据）
