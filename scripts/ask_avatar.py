"""Give the avatar a task from the command line — the everyday entry point.

Usage:
  uv run --env-file .env python scripts/ask_avatar.py "把 workspace/album 的图片压缩一半"
  uv run --env-file .env python scripts/ask_avatar.py --task-file task.txt
  uv run --env-file .env python scripts/ask_avatar.py "..." --quiet   # no live events

The avatar runs with the full toolset (sandboxed code execution, image
generation/viewing, Telegram reporting) and the sandboxed workspace as its
persistent file area. Live tool activity is echoed to the terminal unless
--quiet is given; the final answer is always printed.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
from pathlib import Path
from typing import Any

from agent_core.application.bootstrap import default_service
from agent_core.observability.stream import EventStream

from e2e_autonomy import avatar_spec  # same spec as the long-task harness


async def echo_events(service: Any, run_id: str) -> None:
    """Echo tool activity live (deduped; replays anything already emitted)."""
    stream: EventStream = service.subscribe_events(run_id)
    seen: set[str] = set()
    try:
        for event in service.trace_events(run_id):
            seen.add(event.id)
        async for event in stream.events():
            if event.id in seen:
                continue
            seen.add(event.id)
            kind = event.event_type.value
            if kind in ("tool_started",):
                print(f"  ▶ {event.tool}")
            elif kind == "tool_failed":
                print(f"  ✗ {event.tool}: {str(event.error)[:80]}")
            elif kind == "run_failed":
                print(f"  ✗ run failed: {event.error}")
    finally:
        service.unsubscribe_events(stream)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Give the avatar a task")
    parser.add_argument("task", nargs="?", help="task description in quotes")
    parser.add_argument("--task-file", type=Path, help="read the task from a file")
    parser.add_argument("--quiet", action="store_true", help="hide live tool activity")
    args = parser.parse_args()

    task = args.task or (args.task_file.read_text() if args.task_file else None)
    if not task:
        parser.error("provide a task or --task-file")

    service = default_service()
    if "avatar" not in service.runtime.agents:
        service.runtime.agents.register(avatar_spec())

    run = await service.submit_run("avatar", task, wait=False)
    print(f"run {run.id[:8]} started — Ctrl-C to cancel\n")

    echoer = None if args.quiet else asyncio.create_task(echo_events(service, run.id))
    try:
        while not run.status.is_terminal:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        service.cancel_run(run.id)
        print("\ncancelling...")
    finally:
        if echoer is not None:
            with contextlib.suppress(asyncio.CancelledError):
                echoer.cancel()

    if run.usage:
        print(
            f"\n[{run.status.value}] {run.usage.total_tokens} tokens, "
            f"{run.usage.model_calls} model calls, {run.usage.tool_calls} tool calls"
        )
    output = service.final_output(run.id)
    print(f"\n{output if output else '(no text output — check workspace files)'}")


if __name__ == "__main__":
    asyncio.run(main())
