"""Tool-schema compaction tests (R20 §10).

Tool schemas ride on EVERY model call, so a verbose description is a per-step
tax. These tests pin that compaction bounds the prose while leaving the calling
convention — types, required lists, defaults, enums, structure — untouched.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.bootstrap import tool_schema_compactor
from agent_core.config.settings import Settings
from agent_core.domain.tool import (
    ToolDefinition,
    compact_definition,
    compact_json_schema,
)
from agent_core.runtime.context_breakdown import static_breakdown
from agent_core.text.tokens import estimate_tokens


def definition(**overrides: Any) -> ToolDefinition:
    base: dict[str, Any] = {
        "name": "demo",
        "description": "x" * 2000,
        "input_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "y" * 1000, "example": "hi"},
                "mode": {
                    "type": "string",
                    "enum": ["a", "b"],
                    "default": "a",
                    "description": "short",
                },
                "opts": {
                    "type": "object",
                    "properties": {"n": {"type": "integer", "default": 3}},
                },
            },
            "required": ["query"],
        },
    }
    base.update(overrides)
    return ToolDefinition(**base)


# ------------------------------------------------------------- primitives


def test_truncates_tool_description() -> None:
    compacted = compact_definition(definition(), tool_description_limit=100)
    assert len(compacted.description) <= 101  # limit + the ellipsis
    assert compacted.description.endswith("…")


def test_truncates_param_description() -> None:
    compacted = compact_definition(definition(), param_description_limit=50)
    props = compacted.input_schema["properties"]
    assert len(props["query"]["description"]) <= 51


def test_drops_schema_decorations() -> None:
    compacted = compact_definition(definition(), param_description_limit=100)
    assert "$schema" not in compacted.input_schema
    assert "example" not in compacted.input_schema["properties"]["query"]


def test_preserves_calling_convention() -> None:
    """Types, required, enums, defaults and nesting must survive intact."""
    compacted = compact_definition(
        definition(), tool_description_limit=10, param_description_limit=10
    )
    schema = compacted.input_schema
    assert schema["required"] == ["query"]
    props = schema["properties"]
    assert props["query"]["type"] == "string"
    assert props["mode"]["enum"] == ["a", "b"]
    assert props["mode"]["default"] == "a"
    assert props["opts"]["properties"]["n"]["default"] == 3
    # short descriptions are left alone
    assert props["mode"]["description"] == "short"


def test_zero_limit_is_a_noop() -> None:
    original = definition()
    assert compact_definition(original) is original


def test_compaction_is_idempotent() -> None:
    once = compact_definition(definition(), tool_description_limit=100, param_description_limit=50)
    twice = compact_definition(once, tool_description_limit=100, param_description_limit=50)
    assert twice.description == once.description
    assert twice.input_schema == once.input_schema


def test_compact_json_schema_handles_lists() -> None:
    schema = {"type": "array", "items": [{"type": "string", "example": "z"}]}
    out = compact_json_schema(schema, description_limit=10)
    assert out["items"] == [{"type": "string"}]


# ------------------------------------------------------------- compactor


def test_compactor_noop_when_disabled() -> None:
    compact = tool_schema_compactor(Settings(_env_file=None, tool_schema_compaction=False))
    original = definition()
    assert compact(original) is original


def test_compactor_uses_configured_limits() -> None:
    compact = tool_schema_compactor(
        Settings(
            _env_file=None,
            tool_schema_compaction=True,
            tool_description_max_chars=80,
            tool_param_description_max_chars=40,
        )
    )
    compacted = compact(definition())
    assert len(compacted.description) <= 81
    assert len(compacted.input_schema["properties"]["query"]["description"]) <= 41


# --------------------------------------------------------- measured effect


def test_compaction_measurably_cuts_cost() -> None:
    """The whole point: the model-facing cost drops, and it is a big drop."""
    original = definition()
    compacted = compact_definition(
        original, tool_description_limit=500, param_description_limit=400
    )
    before = static_breakdown([original], [])["builtin_tools"]
    after = static_breakdown([compacted], [])["builtin_tools"]
    assert after < before
    assert after <= before * 0.6  # a verbose tool loses >40% of its footprint


def test_real_mcp_style_tool_shrinks_but_stays_usable() -> None:
    """A TinyFish-shaped tool (long desc + example-heavy props) compacts hard."""
    big = ToolDefinition(
        name="fetch",
        description="d " * 1000,
        input_schema={
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "u " * 600,
                    "example": ["https://example.com"],
                }
            },
        },
    )
    compacted = compact_definition(big, tool_description_limit=500, param_description_limit=400)
    assert estimate_tokens(compacted.description) < estimate_tokens(big.description) / 3
    assert compacted.input_schema["properties"]["urls"]["type"] == "array"
