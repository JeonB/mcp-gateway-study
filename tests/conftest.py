"""Shared test fixtures.

Upstream MCP servers run in-process as ASGI apps, and the gateway reaches them
through an httpx client that mounts each upstream URL onto its app, so tests
need no open ports.
"""

from contextlib import AsyncExitStack
from typing import Any

import httpx
import pytest

from upstreams import math_server, notes_server, slow_server

PROTOCOL_VERSION = "2026-07-28"

# Gateway upstream config used in tests: name -> MCP endpoint URL.
UPSTREAMS = {
    "math": "http://127.0.0.1:9001/mcp",
    "notes": "http://127.0.0.1:9002/mcp",
    "slow": "http://127.0.0.1:9004/mcp",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def upstream_http():
    """httpx client that routes UPSTREAMS URLs to the in-process upstream apps."""
    apps = {
        "math": math_server.server.streamable_http_app(json_response=True),
        "notes": notes_server.server.streamable_http_app(json_response=True),
        "slow": slow_server.server.streamable_http_app(json_response=False),
    }
    async with AsyncExitStack() as stack:
        mounts = {}
        for name, app in apps.items():
            await stack.enter_async_context(app.router.lifespan_context(app))
            origin = str(httpx.URL(UPSTREAMS[name]).copy_with(path="/"))
            mounts[origin.rstrip("/")] = httpx.ASGITransport(app=app)
        client = await stack.enter_async_context(httpx.AsyncClient(mounts=mounts))
        yield client


def mcp_request(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    id: int | None = 1,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Build (headers, body) for a 2026-07-28 Streamable HTTP request.

    Pass id=None for a notification.
    """
    meta = {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "0"},
    }
    params = dict(params or {})
    params["_meta"] = {**meta, **params.get("_meta", {})}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if "name" in params:
        headers["Mcp-Name"] = params["name"]

    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
    if id is not None:
        body["id"] = id
    return headers, body
