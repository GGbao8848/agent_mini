# 阶段验收报告 2（Stage Acceptance 2）

验收轮次：第二批 R8–R13（Artifact 契约 / Conversation-Checkpoint / Memory / Error→Lesson / 对抗 / 多进程）
时间：2026-09-10
环境：见 `ENVIRONMENT.md`（commit `2f3c593` 部署运行）
运行 ID：AC-20260910-002

## 结论

**PASS（阶段通过）**，P0=0。运行时边界加固全部落地，Memory 用真实行为改变验证
（非仅 API 返回记录）。

## 单元 / 边界测试

| 套件 | 结果 |
|---|---|
| `tests/runtime_boundary/`（边界 10 + 产物 3 + 记忆 9 + Lesson 4 + 对抗 6 + 多进程 2 = 34） | 34 passed |
| 全量 `tests/unit` + boundary | 491 passed，1 failed |
| mypy strict | 11 errors（= 基线，无新增） |

唯一失败仍是既有的 `test_model_config` 环境性失败（依赖真实 OPENROUTER key），
在改动前 main 上同样失败。

## 真实 E2E（黑盒，HTTP API → 真实 agent → 真实文件 / 真实记忆）

| Case | 输入 | 观察 | 判定 |
|---|---|---|---|
| MEM-002/003 记忆召回（行为） | 全新会话问「我叫什么、在哪工作」 | 「你叫宋奎，在江苏北人工作」——无聊天历史，纯靠记忆检索 | ✅ |
| MEM-001 记忆写入 | 「记住：生成 PPT 前先确认文件存在」 | agent 调 `remember`（type=`error_fix`）落库 | ✅ |
| R11 行为改变闭环 | 新会话「生成一页 PPT」 | trace：先 run_code 生成，**再次 run_code 验证**（`28233 test.pptx`）后才报成功 | ✅ |
| ART-001 产物契约 | 检查 run 产物记录 | 含 path/size/mime_type/sha256（claims 优先于目录扫描） | ✅ |
| R7 控制面审批 | 工具列表 | `install_skill` risk=**high**（写入全局技能库需人工审批） | ✅ |
| 记忆去重 | 重复写入同一事实 | 旧系统同一条存了 3 份；新写入刷新不新增 | ✅ |

## 关键证据

- 记忆召回任务：全新 conversation → 正确答出用户身份
- Lesson 闭环任务：`fd5ec28f5a0c46208de48f03abb674a0`，产物
  `workspace/tasks/fd5ec28…/test.pptx`(28233B)；trace 两次 `run_code`
  （生成 + 验证），证明 lesson 生效
- 记忆面板：`GET /v1/memories` 返回带 scope/type 的条目

## 不变量覆盖

I-01/02/03/04/05/06/07/08/09/10/11 均有自动化测试或真实 E2E 覆盖（见 `CASES.md`）。

## 人工体验事项（交人工）

1. **记忆面板**：控制台应出现「记忆」视图；新增/编辑/删除；同一条重复提交应
   只保留一份。
2. **纠错提示**：说一句「以后…」「记住…」，agent 应在回复后调用 `remember`；
   普通闲聊不应触发。
3. **跨会话记忆**：新开会话问「我叫什么」类问题，应能答出（若面板中已有该记忆）。
4. 让 agent 尝试新建技能（install_skill），应进入**待审批**而非直接执行。
