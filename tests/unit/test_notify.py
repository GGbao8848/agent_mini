"""Tests for the Telegram notification channel, its builtin tool, and proxy env."""

from typing import Any

import httpx
import pytest

from agent_core.builtins.notify import TELEGRAM_NOTIFY_TOOL, make_telegram_notify
from agent_core.config.settings import Settings, apply_proxy
from agent_core.errors.exceptions import ConfigurationError, ToolError
from agent_core.notify.telegram import TELEGRAM_API_BASE_URL, TelegramChannel
from agent_core.registries import ToolRegistry


def mock_channel(handler: Any, chat_id: str = "42") -> TelegramChannel:
    transport = httpx.MockTransport(handler)
    return TelegramChannel("TESTTOKEN", chat_id, transport=transport)


class TestTelegramChannel:
    async def test_send_message_posts_to_bot_api(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["json"] = request.read().decode()
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

        channel = mock_channel(handler)
        message_id = await channel.send_message("hello")

        assert message_id == 7
        assert seen["url"] == f"{TELEGRAM_API_BASE_URL}/botTESTTOKEN/sendMessage"
        assert '"chat_id":"42"' in seen["json"].replace(" ", "")
        assert "hello" in seen["json"]

    async def test_send_message_without_chat_id_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        channel = TelegramChannel("T", None, transport=httpx.MockTransport(handler))
        with pytest.raises(ConfigurationError):
            await channel.send_message("hello")

    async def test_verify_parses_bot_info(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"ok": True, "result": {"username": "my_avatar_bot"}}
            )

        bot = await mock_channel(handler).verify()
        assert bot["username"] == "my_avatar_bot"

    async def test_telegram_error_response_raises_tool_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ok": False, "description": "Unauthorized"})

        with pytest.raises(ToolError) as excinfo:
            await mock_channel(handler).verify()
        assert "Unauthorized" in excinfo.value.message

    async def test_network_failure_raises_retryable_tool_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route")

        with pytest.raises(ToolError) as excinfo:
            await mock_channel(handler).verify()
        assert excinfo.value.retryable is True


class TestTelegramBuiltinTool:
    async def test_tool_sends_through_channel(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read().decode()
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

        channel = mock_channel(handler)
        _, notify = make_telegram_notify("T", "42", channel=channel)

        result = await notify(message="run finished")

        assert "Delivered to chat 42 (message 9)" in result
        assert seen["url"].endswith("/botTESTTOKEN/sendMessage")
        assert "run finished" in seen["body"]

    def test_registration_requires_token_and_chat(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_core.builtins.notify import register_builtin_tools

        registry = ToolRegistry()
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        assert register_builtin_tools(registry) == []

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
        assert register_builtin_tools(registry) == []  # token alone is not enough

        monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
        assert register_builtin_tools(registry) == [TELEGRAM_NOTIFY_TOOL]
        registry.handler_for(TELEGRAM_NOTIFY_TOOL)  # executable is attached


class TestProxyEnv:
    def test_proxy_and_default_no_proxy_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy"):
            monkeypatch.delenv(var, raising=False)
        settings = Settings(_env_file=None, proxy_url="http://10.10.10.214:7890")

        apply_proxy(settings)

        import os

        assert os.environ["HTTPS_PROXY"] == "http://10.10.10.214:7890"
        assert "localhost" in os.environ["NO_PROXY"]
        assert "127.0.0.1" in os.environ["NO_PROXY"]

    def test_custom_no_proxy_hosts_are_appended(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy"):
            monkeypatch.delenv(var, raising=False)
        settings = Settings(
            _env_file=None,
            proxy_url="http://10.10.10.214:7890",
            no_proxy="10.10.10.146,10.10.10.169",
        )

        apply_proxy(settings)

        import os

        no_proxy = os.environ["NO_PROXY"]
        assert "10.10.10.146" in no_proxy and "10.10.10.169" in no_proxy
        assert "localhost" in no_proxy

    def test_no_proxy_without_proxy_url_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy"):
            monkeypatch.delenv(var, raising=False)
        settings = Settings(_env_file=None, no_proxy="10.10.10.146")

        apply_proxy(settings)

        import os

        assert "NO_PROXY" not in os.environ
        assert "HTTPS_PROXY" not in os.environ
