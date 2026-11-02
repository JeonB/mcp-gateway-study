"""Upstream MCP server `math` (Streamable HTTP, :9001/mcp)."""

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="math", version="0.1.0")


@server.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@server.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


if __name__ == "__main__":
    server.run("streamable-http", port=9001, json_response=True)
