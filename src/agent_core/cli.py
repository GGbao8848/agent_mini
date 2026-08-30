"""Command-line interface: boot the server, drive it, or run a local demo.

Three modes:
- ``serve`` — start the HTTP API (uvicorn).
- API client commands (``agents``, ``tools``, ``skills``, ``tasks``, ``run``,
  ``cancel``, ``approvals``, ``resolve``, ``mcp-connect``,
  ``mcp-disconnect``, ``events``) — thin wrappers over the API of a running
  server; state lives in that process, so the client stays stateless.
- ``demo`` — self-contained local run (registries + a local tool + the real
  model) to verify an installation without a server.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from typing import Any

import httpx

DEFAULT_API = "http://127.0.0.1:8000"
ClientFactory = Callable[[str], Any]


def build_parser() -> argparse.ArgumentParser:
    # ``--api`` is accepted before or after the subcommand. The subcommand-level
    # occurrence uses a separate dest because argparse subparsers clobber
    # namespace attributes with their own defaults; main() reconciles them.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api", dest="api_sub", default=None, help=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(
        prog="agent-core",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "--api", default=DEFAULT_API, help=f"Agent Core server URL (default {DEFAULT_API})"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", parents=[common], help="Print the installed version")
    serve = sub.add_parser("serve", parents=[common], help="Start the HTTP API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    demo = sub.add_parser(
        "demo", parents=[common], help="Self-contained local run with the real model"
    )
    demo.add_argument("--question", default="What time is it right now? Use the tool.")

    for name, help_text in (
        ("agents", "List registered agents"),
        ("tools", "List registered tools"),
        ("skills", "List registered skills"),
        ("tasks", "List conversations"),
        ("approvals", "List pending approvals"),
    ):
        command = sub.add_parser(name, parents=[common], help=help_text)
        if name == "tasks":
            command.add_argument("--agent", default=None, help="Filter by agent id")

    run = sub.add_parser("run", parents=[common], help="Start a conversation via the API")
    run.add_argument("agent_id")
    run.add_argument("input")
    run.add_argument("--no-wait", action="store_true", help="Do not wait for completion")

    events = sub.add_parser("events", parents=[common], help="Stream live events (Ctrl-C to stop)")
    events.add_argument("run_id", nargs="?", default=None)

    cancel = sub.add_parser("cancel", parents=[common], help="Cancel a conversation")
    cancel.add_argument("task_id")

    resolve = sub.add_parser("resolve", parents=[common], help="Resolve a pending approval")
    resolve.add_argument("approval_id")
    resolve.add_argument(
        "--decision", required=True, choices=["approved", "rejected", "edited", "cancelled"]
    )
    resolve.add_argument("--by", default="user", help="Who resolved it")
    resolve.add_argument(
        "--edit",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Edited argument (repeatable, requires --decision edited)",
    )

    for name, help_text in (
        ("mcp-connect", "Connect an MCP server"),
        ("mcp-disconnect", "Disconnect"),
    ):
        command = sub.add_parser(name, parents=[common], help=help_text)
        command.add_argument("server_id")
    return parser


async def dispatch(args: argparse.Namespace, client_factory: ClientFactory) -> int:
    if args.command == "version":
        from agent_core import __version__

        print(__version__)
        return 0
    if args.command == "serve":
        import uvicorn

        uvicorn.run("agent_core.api.app:app", host=args.host, port=args.port)
        return 0
    if args.command == "demo":
        return await _demo(args.question)
    async with client_factory(args.api) as client:
        return await _api_command(args, client)


async def _api_command(args: argparse.Namespace, client: Any) -> int:
    name = args.command
    if name == "agents":
        return _show(await client.get("/v1/agents"))
    if name == "tools":
        return _show(await client.get("/v1/tools"))
    if name == "skills":
        return _show(await client.get("/v1/skills"))
    if name == "tasks":
        params = {"agent_id": args.agent} if args.agent else None
        return _show(await client.get("/v1/tasks", params=params))
    if name == "approvals":
        return _show(await client.get("/v1/approvals/pending"))
    if name == "run":
        return _show(
            await client.post(
                "/v1/tasks",
                params={"wait": "false" if args.no_wait else "true"},
                json={"agent_id": args.agent_id, "input": args.input},
            )
        )
    if name == "cancel":
        return _show(await client.post(f"/v1/tasks/{args.task_id}/cancel"))
    if name == "mcp-connect":
        return _show(await client.post(f"/v1/mcp/servers/{args.server_id}/connect"))
    if name == "mcp-disconnect":
        return _show(await client.post(f"/v1/mcp/servers/{args.server_id}/disconnect"))
    if name == "resolve":
        edited = _parse_edits(args.edit)
        return _show(
            await client.post(
                f"/v1/approvals/{args.approval_id}/resolve",
                json={
                    "decision": args.decision,
                    "resolved_by": args.by,
                    "edited_arguments": edited,
                },
            )
        )
    if name == "events":
        return await _stream(client, args.run_id)
    raise AssertionError(f"unhandled command {name}")  # pragma: no cover


def _show(response: Any) -> int:
    print(response.json())
    if response.is_error:
        return 1
    return 0


def _parse_edits(pairs: list[str]) -> dict[str, str]:
    edited: dict[str, str] = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if not _:
            raise SystemExit(f"--edit expects KEY=VALUE, got '{pair}'")
        edited[key] = value
    return edited


async def _stream(client: Any, run_id: str | None) -> int:
    path = f"/v1/runs/{run_id}/events" if run_id else "/v1/events"
    try:
        async with client.stream("GET", path) as response:
            if response.is_error:
                print((await response.aread()).decode())
                return 1
            async for line in response.aiter_lines():
                if line.startswith("event: ") or line.startswith("data: "):
                    print(line)
    except KeyboardInterrupt:
        print("\n(disconnected)")
    return 0


async def _demo(question: str) -> int:
    from datetime import datetime

    from agent_core.application.bootstrap import default_service
    from agent_core.config.settings import get_settings
    from agent_core.domain.agent import AgentSpec
    from agent_core.domain.tool import ToolDefinition

    settings = get_settings()

    def current_time() -> str:
        return datetime.now().isoformat(timespec="seconds")

    service = default_service()
    service.runtime.tools.register(
        ToolDefinition(
            name="current_time",
            description="Returns the current local time as an ISO timestamp.",
            input_schema={"type": "object", "properties": {}},
        ),
        handler=current_time,
    )
    service.runtime.agents.register(
        AgentSpec(
            id="assistant",
            name="Assistant",
            model=settings.model,
            system_prompt="Answer briefly. Use the current_time tool for time questions.",
            tools=["current_time"],
        )
    )
    conversation = await service.submit_run("assistant", question, wait=True)
    run = service.runtime.task_active_run(conversation.id)
    if run is None:
        print("error: no run was created")
        return 1
    print(f"status: {run.status.value}")
    if run.error:
        print(f"error: {run.error}")
        return 1
    print(f"output: {service.final_output(run.id)}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse and reconcile ``--api`` given before vs. after the subcommand."""
    args = build_parser().parse_args(argv)
    if getattr(args, "api_sub", None) is not None:
        args.api = args.api_sub
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    def client_factory(base_url: str) -> Any:
        # trust_env=False: the CLI talks to a specific Agent Core server (usually
        # localhost) and must not be hijacked by ambient HTTP(S)_PROXY settings.
        return httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(300.0), trust_env=False
        )

    try:
        return asyncio.run(dispatch(args, client_factory))
    except KeyboardInterrupt:
        return 130
    except httpx.HTTPError as exc:
        print(f"cannot reach Agent Core server at {args.api}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
