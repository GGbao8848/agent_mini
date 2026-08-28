"""Tiny demo MCP server (stdio) used by scripts/smoke_mcp.py and the examples.

Uses the mcp 2.x ``MCPServer`` API (FastMCP was renamed in 2.0).
Run: python examples/mcp_demo_server.py
"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the input text back."""
    return f"echo: {text}"


@mcp.tool()
def add(a: int, b: int) -> str:
    """Add two integers."""
    return f"{a} + {b} = {a + b}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
