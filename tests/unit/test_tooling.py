"""Unit tests for tool adapters (registry entry -> LangChain tool)."""

import pytest
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import ConfigurationError
from agent_core.runtime.tooling import make_direct_tool, schema_to_pydantic

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {
        "location": {"type": "string", "description": "City name"},
        "days": {"type": "integer", "description": "Forecast days"},
    },
    "required": ["location"],
}


def weather_definition() -> ToolDefinition:
    return ToolDefinition(
        name="get_weather",
        description="Look up the weather",
        input_schema=WEATHER_SCHEMA,
        source=ToolSource.PYTHON,
    )


class TestSchemaToPydantic:
    def test_builds_typed_model(self) -> None:
        model = schema_to_pydantic("get_weather", WEATHER_SCHEMA)

        assert issubclass(model, BaseModel)
        instance = model(location="Oslo")
        assert instance.location == "Oslo"
        assert instance.days is None

    def test_empty_schema_yields_empty_model(self) -> None:
        model = schema_to_pydantic("ping", {})

        assert issubclass(model, BaseModel)
        model()


class TestMakeDirectTool:
    async def test_sync_handler_receives_kwargs(self) -> None:
        tool = make_direct_tool(
            weather_definition(), lambda location, days=1: f"sun in {location} for {days}d"
        )

        assert isinstance(tool, BaseTool)
        assert await tool.ainvoke({"location": "Oslo"}) == "sun in Oslo for 1d"

    async def test_async_handler(self) -> None:
        async def handler(location: str) -> str:
            return f"rain in {location}"

        tool = make_direct_tool(weather_definition(), handler)

        assert await tool.ainvoke({"location": "Bergen"}) == "rain in Bergen"

    async def test_tool_without_args(self) -> None:
        definition = ToolDefinition(name="ping", description="Ping")
        tool = make_direct_tool(definition, lambda: "pong")

        assert await tool.ainvoke({}) == "pong"

    def test_missing_handler_raises(self) -> None:
        with pytest.raises(ConfigurationError) as excinfo:
            make_direct_tool(weather_definition(), None)
        assert excinfo.value.details["tool"] == "get_weather"
