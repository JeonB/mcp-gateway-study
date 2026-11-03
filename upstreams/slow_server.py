"""Upstream MCP server `slow` (Streamable HTTP in SSE mode, :9004/mcp).

`count` sends one progress notification per step, which pushes the response onto
`text/event-stream`. Use it to check that the gateway relays SSE.
"""

import anyio

from mcp.server.mcpserver import Context, MCPServer

server = MCPServer(name="slow", version="0.1.0")


@server.tool()
async def count(n: int, ctx: Context, delay: float = 0.0) -> int:
    """Count to n, reporting progress at each step."""
    for i in range(n):
        await ctx.report_progress(i, n, f"step {i + 1}/{n}")
        await anyio.sleep(delay)
    return n


if __name__ == "__main__":
    server.run("streamable-http", port=9004, json_response=False)
