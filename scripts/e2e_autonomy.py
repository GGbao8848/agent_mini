"""End-to-end autonomy run: two long multimodal tasks executed by the avatar.

Task A: a 30-slide Chinese pptx about AI history, with 10+ generated images
Task B: an illustrated 4-seasons China web album, with 12 generated images

Both run concurrently through the full stack (local qwen model, txt2img,
view_image checks, run_code for python-pptx, telegram_notify milestones).
Every trace event is streamed to a per-task log for post-run analysis.

Usage: uv run --env-file .env python scripts/e2e_autonomy.py   (Ctrl-C to abort)
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from agent_core.application.bootstrap import default_service
from agent_core.domain.agent import AgentLimits, AgentSpec
from agent_core.domain.autonomy import AutonomyPolicy, LoopGuardPolicy, RunBudget
from agent_core.domain.resilience import ResiliencePolicy, SummarizationPolicy

LOG_DIR = Path("logs/e2e")

AVATAR_SYSTEM_PROMPT = """你是用户的个人 AI 分身，独立完成长任务。工作约定：
- 工作目录：所有文件都写在 workspace 下（文件工具的根目录就是它）；
  文件工具一律用相对路径（如 ppt/build.py），不要用绝对路径；
  run_code 在同一目录执行 bash。
- 生成图片：调用 generate_image 后会返回图片的绝对路径；
  重要的图用 view_image 亲自查看确认。
- 写代码：用文件工具写脚本，再用 run_code 执行（`python xxx.py`）。
  沙箱已预装常用库（numpy/pandas/matplotlib/python-pptx/python-docx/openpyxl/
  requests/beautifulsoup4/jieba/Pillow/plotly/reportlab 等）；遇到没有的库，
  直接 `pip install xxx && python xxx.py` 拼在一条命令里（有缓存，重装很快）。
  命令失败时读错误信息、修好再跑，不要原样重试。
- 汇报：开始时、完成一半时、结束时各用 telegram_notify 给主人发一条简短进展（中文）。
- 交付物必须是真实落盘的文件；结束前用 run_code 验证文件存在且尺寸合理。"""


TASK_A = """任务：制作一份 30 页的中文 PPT《人工智能简史与未来》，保存到 workspace/ppt/。

要求：
1. 先规划 30 页的结构（封面、目录、4-6 个章节、时间线、总结、致谢）；
2. 用 generate_image 生成至少 10 张配图（图灵与早期计算机、神经网络、
   深度学习、大模型对话、机器人、自动驾驶、未来城市等主题，风格统一），
   每张生成后用 view_image 确认不跑偏，不满意就换 prompt 重新生成；
3. 用文件工具写一个 Python 脚本（python-pptx），生成 ppt/ai_history.pptx：
   - 恰好 30 页，含标题页、目录、章节过渡页、内容页、总结页
   - 每页有标题和 2-4 行正文；10+ 张生成图插入对应页面
4. 用 run_code 执行脚本生成 pptx；再用 run_code 验证：页数=30、文件大于 1MB；
5. 全程用 telegram_notify 至少汇报 3 次（开始/中途/完成），
   完成消息里写清文件路径和页数。"""


TASK_B = """任务：制作一份图文并茂的网页画册《四季·中国》，保存到 workspace/album/。

要求：
1. 用 generate_image 生成 12 张图：春/夏/秋/冬各 3 张
   （风景、美食、人文各一，中国意象，风格统一的水彩风）；
2. 用 view_image 至少抽查 6 张，确认季节和主题对得上，不对就重新生成；
3. 把图片整理进 album/images/（可用 run_code 复制改名，如 spring-1.png）；
4. 用文件工具写 album/index.html：图文并茂，四季分四个板块，
   每张图配一句中文说明，简洁美观的内联 CSS；
5. 用 run_code 验证：12 张图都在、index.html 引用的每个图片文件都存在
   （写个小脚本检查）；
6. 用 telegram_notify 至少汇报 3 次（开始/中途/完成），
   完成消息里写清路径和你的自评。"""


def avatar_spec() -> AgentSpec:
    return AgentSpec(
        id="avatar",
        name="Avatar",
        tools=["generate_image", "view_image", "telegram_notify", "run_code"],
        system_prompt=AVATAR_SYSTEM_PROMPT,
        limits=AgentLimits(timeout_seconds=5400),
        resilience=ResiliencePolicy(
            summarization=SummarizationPolicy(trigger_messages=60, keep_messages=20),
        ),
        autonomy=AutonomyPolicy(
            budget=RunBudget(max_model_calls=400, max_total_tokens=4_000_000),
            loop_guard=LoopGuardPolicy(max_identical_calls=4, max_consecutive_failures=5),
        ),
    )


async def log_stream(service: Any, run_id: str, log_path: Path) -> None:
    """Write every event of one run to its log file."""
    stream = service.subscribe_events(run_id)
    seen: set[str] = set()

    def write(event: Any) -> None:
        seen.add(event.id)
        line = (
            f"{event.timestamp:%H:%M:%S} {event.event_type.value:<18} "
            f"{event.tool or ''} {str(event.output or event.error or '')[:120]}"
        )
        with log_path.open("a") as fh:
            fh.write(line + "\n")

    try:
        with log_path.open("w"):
            pass
        for event in service.trace_events(run_id):  # replay history, dedupe live
            write(event)
        async for event in stream.events():
            if event.id not in seen:
                write(event)
            if event.event_type.value in ("run_finished", "run_failed", "run_cancelled"):
                break
    finally:
        service.unsubscribe_events(stream)


async def run_task(service: Any, task_input: str, log_path: Path) -> Any:
    run = await service.submit_run("avatar", task_input, wait=False)
    logger = asyncio.create_task(log_stream(service, run.id, log_path))
    while not run.status.is_terminal:
        await asyncio.sleep(2)
    with contextlib.suppress(asyncio.CancelledError):
        await logger
    return run


async def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    service = default_service()
    service.runtime.agents.register(avatar_spec())

    print("launching task A (30-slide pptx) and task B (web album) concurrently...")
    finished_a, finished_b = await asyncio.gather(
        run_task(service, TASK_A, LOG_DIR / "task-a.log"),
        run_task(service, TASK_B, LOG_DIR / "task-b.log"),
    )

    for name, run in (("A pptx", finished_a), ("B album", finished_b)):
        print(f"\n=== task {name}: {run.status.value} (usage: {run.usage})")
        if run.error:
            print(f"error: {run.error}")
        if run.metadata.get("verification"):
            print(f"verification: {run.metadata['verification']}")
        output = service.final_output(run.id)
        print(f"final output: {str(output)[:600]}")


if __name__ == "__main__":
    asyncio.run(main())
