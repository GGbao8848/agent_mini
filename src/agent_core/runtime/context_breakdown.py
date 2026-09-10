"""Context-window accounting: which parts of a prompt consume how much.

The provider reports a single input-token number per call. To show the user
WHERE their context goes (messages vs tool schemas vs system prompt vs
skills) we estimate per-part sizes with a CJK-aware character heuristic and
anchor the sum to the provider-reported total — the "other" bucket absorbs
wrapping overhead and estimation error, so the displayed parts always add up
to the real number.
"""

from __future__ import annotations

import json
from typing import Any

from agent_core.domain.skill import SkillManifest
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.runtime.tooling import schema_to_pydantic
from agent_core.text.tokens import estimate_tokens

__all__ = ["estimate_tokens", "static_breakdown"]


def _definition_text(definition: ToolDefinition) -> str:
    """The JSON shape the model actually sees for one tool.

    Not the raw ``input_schema``: the LangChain tool is built from a pydantic
    args model (see :func:`agent_core.runtime.tooling.schema_to_pydantic`),
    which drops JSON-schema decorations like ``example``/``$schema`` and keeps
    only the parameters. Measuring the raw schema overstated every tool's cost
    (TinyFish's examples alone were ~500 tokens) and made the console's context
    breakdown disagree with what is really sent.
    """
    try:
        args = schema_to_pydantic(definition.name, definition.input_schema)
        parameters: Any = args.model_json_schema()
    except Exception:
        # A malformed schema must not break accounting; fall back to raw.
        parameters = definition.input_schema
    return json.dumps(
        {
            "name": definition.name,
            "description": definition.description,
            "parameters": parameters,
        },
        ensure_ascii=False,
        default=str,
    )


def _stub_text(definition: ToolDefinition) -> str:
    """The cheap stand-in shape a tiered cold tool is advertised as.

    Mirrors :meth:`agent_core.runtime.tool_tiering.ToolTieringMiddleware._stub`
    (name, first-sentence summary, permissive args) so the accounting matches
    what is actually sent.
    """
    from agent_core.runtime.tool_tiering import _summary

    return json.dumps(
        {
            "name": definition.name,
            "description": _summary(definition.description or "", 160)
            + "（调用后将加载完整参数说明）",
        },
        ensure_ascii=False,
    )


def static_breakdown(
    tools: list[ToolDefinition],
    skills: list[SkillManifest],
    *,
    cold_names: set[str] | None = None,
) -> dict[str, int]:
    """Estimate the per-build (static) prompt parts: tool schemas and skills.

    Tool schemas enter every request; skill *manifests* (name + description)
    are what the harness lists in the prompt — full skill bodies are read
    from disk on demand and don't sit in the context.

    ``cold_names`` are tools advertised as stubs this run (R20 §10 tiering);
    they are counted at their stub cost, not their full schema.
    """
    cold = cold_names or set()
    builtin = 0
    mcp = 0
    for definition in tools:
        text = _stub_text(definition) if definition.name in cold else _definition_text(definition)
        cost = estimate_tokens(text)
        if definition.source == ToolSource.MCP:
            mcp += cost
        else:
            builtin += cost
    skill_text = "\n".join(
        f"{manifest.name}: {manifest.description}" for manifest in skills
    )
    return {
        "builtin_tools": builtin,
        "mcp_tools": mcp,
        "skills": estimate_tokens(skill_text),
    }
