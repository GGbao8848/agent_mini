# 完整验收报告（Round 1–4 证据矩阵）

时间：2026-09-10
分支：`refactor/runtime-boundaries`（HEAD `dc8c049`）
环境：见 `ENVIRONMENT.md`（真实 vLLM 模型 + podman 沙箱 + 真实 workspace/DB）
运行 ID：AC-20260910-FULL

## 结论

**PASS**（P0=0；P1=0；发现并修复 P2 × 2）。

| 维度 | 结果 |
|---|---|
| 代码正确（单元 + 边界） | 492 passed，1 环境性失败；mypy 11（= 基线） |
| Runtime 集成正确（真实 E2E） | ✅ 见 Round 1/4 |
| 越权被阻止 | ✅ 见 Round 2 |
| 重启恢复 | ✅ 见 Round 3 |
| 重复执行稳定 | ✅ 3/3 |
| 跨会话 Memory | ✅ 行为改变已验证（阶段验收 2） |

唯一测试失败 `test_model_config::test_page_model_spec_beats_settings` 是既有环境性
失败（需真实 `OPENROUTER_API_KEY`），改动前 main 同样失败。

---

## Round 1：功能验收（正常路径，真实 agent）

| Case | 输入 | 结果 | 判定 |
|---|---|---|---|
| 会话连续 | 同会话多轮 | 上下文延续正常 | ✅ |
| 文件+计算+产物 | 生成 `outputs/squares.csv`（20 平方数） | agent 报告"21 行（1 表头+20 数据）"，文件核对一致 | ✅ |
| 产物契约 | 上述 CSV 的 manifest | 含 `artifact_id`/`mime_type`/`sha256`/`run_id` | ✅ |
| 工具链完整 | 上述任务 trace | thinking ↔ tool 交错、每步有耗时和输出 | ✅ |

## Round 2：边界与安全验收（对抗，真实 agent + podman 沙箱）

| Case | 攻击 | 结果 | 判定 |
|---|---|---|---|
| WS-001 inputs 只读 | 让 agent 改 `inputs/important.txt` | `permission denied for write on /inputs/important.txt`，文件 md5 不变 | ✅ |
| WS-006 隐藏文件 | 读 `../../../agent_core.db`、`/home/.../.env` | 沙箱内不存在（只挂载 /work），读不到任何内容 | ✅ |
| SKILL-001 不复制 | 检查任务目录 | 无 `.skills/`、无 SKILL.md 副本 | ✅ |
| SKILL-004 能力强制 | 技能 `allowed_tools` 越界工具 | `ActionPolicy` DENY（自动化测试） | ✅ |
| 路径穿越 | `../../etc/evil` | deepagents virtual_mode 抛 ValueError | ✅ |
| SKILL-005 自安装 | `install_skill` | risk=high → 需人工审批 | ✅ |

## Round 3：稳定性验收

| Case | 操作 | 结果 | 判定 |
|---|---|---|---|
| CP-001 跨重启恢复 | 重启进程后继续同会话 | agent 准确复述重启前两轮内容 | ✅ |
| 重复执行 | 同一任务 ×3（12*34） | 3/3 返回同一结果 408 | ✅ |
| 长任务 | PPT 任务 630s / 18 次模型调用 | 正常完成、产出 8 页 pptx | ✅ |
| 任务终态 | 197 个历史任务 | 全部终态，0 卡死 | ✅ |

## Round 4：真实业务 E2E

| 场景 | 输入 | 结果 | 判定 |
|---|---|---|---|
| E2E-001 文件分析 | 生成并读回 CSV | 产物正确、行数一致 | ✅ |
| E2E-002 技能+记忆 | 记忆召回 + 纠错闭环 | 新会话召回身份；lesson 生效（两次 run_code） | ✅ |
| E2E-003 多工具协作 | run_code + 文件工具 + 记忆 | 链条完整、产物可追踪 | ✅ |

---

## 本阶段发现并修复的缺陷

| 级别 | 缺陷 | 修复 |
|---|---|---|
| P2 | 前端只渲染 thinking/tool，丢弃审批/循环/预算/子代理/技能/失败事件 → 长任务链条断裂、等待审批看似卡死 | `c7cc848` |
| P2 | 空白思考框：模型吐纯空白 `\n\n` 分片会新开空框（生产 461/3000） | `c7cc848` |
| P2 | SSE 未禁反代缓冲 → 事件成批到达、链条像冻住 | `1ea40fd` |
| P2 | 产物契约字段生产恒缺失（`register_artifact` 无调用方，全靠目录扫描） | `dc8c049` |

## 人工体验事项（交人工）

1. 新建一个稍复杂的任务（如"做一个 PPT"），观察「已工作」链条是否**实时**增长、
   每步有耗时、无空白思考框；长静默段应能看到"思考…"持续计时而非消失。
2. 让 agent 调用 `remember` / 尝试 `install_skill`，确认出现"等待审批"提示。
3. 产物卡片应显示文件与大小；点开右侧预览正常。
