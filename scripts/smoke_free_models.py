"""Smoke-test free OpenRouter models against the Agent Core stack.

Tests two capabilities per model: plain completion and tool calling.
Usage: uv run --env-file .env python scripts/smoke_free_models.py
"""

from __future__ import annotations

import os
import sys
import time

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from agent_core.config.settings import get_settings

get_settings()  # applies AGENT_CORE_PROXY_URL to HTTP(S)_PROXY for all outbound calls

MODELS = [
    "minimax/minimax-m3:free",
    "dots-studio/dots-3-note-preview:free",
]


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"{city}: 22°C, sunny"


def make_model(model_id: str) -> ChatOpenAI:
    return ChatOpenAI(
        model=model_id,
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
        temperature=0,
        timeout=90,
    )


def test_completion(model_id: str) -> float:
    start = time.monotonic()
    response = make_model(model_id).invoke("用一句话回答：1+1等于几？")
    elapsed = time.monotonic() - start
    content = str(response.content).strip().replace("\n", " ")[:80]
    print(f"  completion  OK  {elapsed:5.1f}s  ->  {content}")
    return elapsed


def test_tool_call(model_id: str) -> bool:
    start = time.monotonic()
    llm = make_model(model_id).bind_tools([get_weather])
    response = llm.invoke("北京今天天气怎么样？必须调用工具查询。")
    elapsed = time.monotonic() - start
    tool_calls = response.tool_calls if hasattr(response, "tool_calls") else []
    if not tool_calls:
        print(f"  tool_call   FAIL  {elapsed:5.1f}s  ->  no tool call in response")
        return False
    call = tool_calls[0]
    print(
        f"  tool_call   OK  {elapsed:5.1f}s  ->  "
        f"{call['name']}({call['args']})"
    )
    return True


def main() -> int:
    failures = 0
    for model_id in MODELS:
        print(f"\n=== {model_id} ===")
        try:
            test_completion(model_id)
            if not test_tool_call(model_id):
                failures += 1
        except Exception as exc:  # noqa: BLE001 — smoke test must report, not crash
            failures += 1
            print(f"  ERROR: {type(exc).__name__}: {str(exc)[:200]}")
    print(f"\n{'PASS' if failures == 0 else f'{failures} FAILURES'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
