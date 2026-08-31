"""Tests for the Telegram notification channel, its builtin tools, and proxy env."""

from typing import Any

import httpx
import pytest

from agent_core.builtins.notify import (
    TELEGRAM_NOTIFY_TOOL,
    TELEGRAM_SEND_ARTIFACT_TOOL,
    make_telegram_notify,
    make_telegram_send_artifact,
)
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

    async def test_send_document_uploads_multipart(self, tmp_path: Any) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read()
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})

        file = tmp_path / "季度报告.pptx"
        file.write_bytes(b"PK fake pptx bytes")
        channel = mock_channel(handler)

        message_id = await channel.send_document(file, caption="给你")

        assert message_id == 11
        assert seen["url"] == f"{TELEGRAM_API_BASE_URL}/botTESTTOKEN/sendDocument"
        # multipart body: filename + chat_id + caption all present
        body = seen["body"].decode("utf-8", "replace")
        assert "季度报告.pptx" in body
        assert 'name="chat_id"' in body and 'name="document"' in body
        assert "给你" in body

    async def test_send_document_missing_file_raises(self, tmp_path: Any) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        channel = mock_channel(handler)
        with pytest.raises(ToolError):
            await channel.send_document(tmp_path / "nope.pdf")

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

    async def test_artifact_tool_sends_workspace_file(self, tmp_path: Any) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = request.read().decode("utf-8", "replace")
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 21}})

        channel = mock_channel(handler)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "album-2026.pptx").write_bytes(b"pptx-bytes")
        _, send_artifact = make_telegram_send_artifact(
            "T", "42", str(workspace), channel=channel
        )

        result = await send_artifact(path="album-2026.pptx")

        assert "Sent album-2026.pptx to chat 42 (message 21)" in result
        assert seen["url"].endswith("/botTESTTOKEN/sendDocument")
        assert "album-2026.pptx" in seen["body"]

    async def test_artifact_tool_rejects_path_escape(self, tmp_path: Any) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        channel = mock_channel(handler)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _, send_artifact = make_telegram_send_artifact(
            "T", "42", str(workspace), channel=channel
        )

        with pytest.raises(ToolError):
            await send_artifact(path="../outside.txt")
        with pytest.raises(ToolError):
            await send_artifact(path="/etc/passwd")
        with pytest.raises(ToolError):
            await send_artifact(path="missing.pptx")

    def test_registration_always_registers_but_flags_availability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_core.builtins.notify import register_builtin_tools

        registry = ToolRegistry()
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        # Registered (so the console can show it) but marked unavailable.
        assert set(register_builtin_tools(registry)) == {
            TELEGRAM_NOTIFY_TOOL,
            TELEGRAM_SEND_ARTIFACT_TOOL,
        }
        assert registry.get(TELEGRAM_NOTIFY_TOOL).metadata["available"] is False
        assert registry.get(TELEGRAM_SEND_ARTIFACT_TOOL).metadata["available"] is False

        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
        assert register_builtin_tools(registry) == [
            TELEGRAM_NOTIFY_TOOL,
            TELEGRAM_SEND_ARTIFACT_TOOL,
        ]
        assert registry.get(TELEGRAM_NOTIFY_TOOL).metadata["available"] is False  # still no chat
        assert registry.get(TELEGRAM_SEND_ARTIFACT_TOOL).metadata["available"] is False

        monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
        assert register_builtin_tools(registry) == [
            TELEGRAM_NOTIFY_TOOL,
            TELEGRAM_SEND_ARTIFACT_TOOL,
        ]
        assert registry.get(TELEGRAM_NOTIFY_TOOL).metadata["available"] is True
        assert registry.get(TELEGRAM_SEND_ARTIFACT_TOOL).metadata["available"] is True
        registry.handler_for(TELEGRAM_NOTIFY_TOOL)  # executable is attached
        registry.handler_for(TELEGRAM_SEND_ARTIFACT_TOOL)  # executable is attached


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
