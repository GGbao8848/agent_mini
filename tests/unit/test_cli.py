"""CLI tests: parser wiring and API-client commands over ASGI (no server)."""

from typing import Any

import httpx
import pytest

from agent_core.api.app import create_app
from agent_core.cli import dispatch, parse_args


@pytest.fixture()
def client_factory() -> Any:
    app = create_app()

    def factory(base_url: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url=base_url)

    return factory


async def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    from agent_core import __version__

    assert await dispatch(parse_args(["version"]), lambda _url: None) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_run_command_parses_flags() -> None:
    args = parse_args(["run", "helper", "hello", "--no-wait", "--api", "http://x"])
    assert args.command == "run"
    assert args.agent_id == "helper"
    assert args.input == "hello"
    assert args.no_wait is True
    assert args.api == "http://x"


async def test_agents_command_lists_over_asgi(client_factory: Any) -> None:
    args = parse_args(["agents"])
    assert await dispatch(args, client_factory) == 0


async def test_unknown_run_maps_to_error_exit_code(client_factory: Any) -> None:
    args = parse_args(["cancel", "ghost"])
    assert await dispatch(args, client_factory) == 1


async def test_resolve_edited_requires_key_value_syntax(client_factory: Any) -> None:
    args = parse_args(["resolve", "a1", "--decision", "edited"])
    # Missing edited arguments fail at the schema level (422), not in the CLI.
    assert await dispatch(args, client_factory) == 1
