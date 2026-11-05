"""M1 acceptance tests: server-level pass-through proxy.

Contract the gateway must implement (see tasks/M1.md):

    gateway/main.py
        create_app(upstreams: dict[str, str], http: httpx.AsyncClient) -> ASGI app
        POST /proxy/{upstream}/mcp  -> forwards to upstreams[upstream]

Run: .venv/bin/pytest tests/m1 -v
These tests are skipped until gateway/main.py exists.
"""

import json
import logging

import httpx
import pytest

from tests.conftest import UPSTREAMS, mcp_request

gateway_main = pytest.importorskip("gateway.main", reason="M1 not started: gateway/main.py does not exist yet")

pytestmark = pytest.mark.anyio


@pytest.fixture
async def gateway(upstream_http):
    app = gateway_main.create_app(UPSTREAMS, upstream_http)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway.test") as client:
        yield client


async def post(client: httpx.AsyncClient, upstream: str, method: str, params=None, **kwargs) -> httpx.Response:
    headers, body = mcp_request(method, params, **kwargs)
    return await client.post(f"/proxy/{upstream}/mcp", headers=headers, json=body)


# --- 1. Basic forwarding ---------------------------------------------------


async def test_tools_call_through_proxy(gateway):
    r = await post(gateway, "math", "tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}})

    assert r.status_code == 200
    assert r.json()["result"]["structuredContent"] == {"result": 5.0}


async def test_routes_by_upstream_name(gateway):
    r = await post(gateway, "notes", "tools/list")

    assert r.status_code == 200
    assert [t["name"] for t in r.json()["result"]["tools"]] == ["create_note", "list_notes"]


async def test_unknown_upstream_is_404(gateway):
    r = await post(gateway, "nope", "tools/list")

    assert r.status_code == 404


# --- 2. Headers and status codes -------------------------------------------


async def test_does_not_forward_client_host_header(gateway):
    # The client talks to "gateway.test"; the upstream only accepts its own host.
    r = await post(gateway, "math", "tools/list")

    assert r.status_code != 421, "Host header was forwarded as-is; the upstream rejected it"
    assert r.status_code == 200


async def test_mcp_headers_are_forwarded(gateway):
    # Mcp-Name disagrees with the body, so the upstream must see the header to reject it.
    headers, body = mcp_request("tools/call", {"name": "add", "arguments": {"a": 1, "b": 1}})
    headers["Mcp-Name"] = "multiply"

    r = await gateway.post("/proxy/math/mcp", headers=headers, json=body)

    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020


async def test_upstream_status_code_is_preserved(gateway):
    r = await post(gateway, "math", "foo/bar")

    assert r.status_code == 404
    assert r.json()["error"]["code"] == -32601


async def test_notification_is_acknowledged_with_202(gateway):
    r = await post(gateway, "math", "notifications/cancelled", {"requestId": 1}, id=None)

    assert r.status_code == 202


# --- 3. SSE relay ----------------------------------------------------------


async def test_sse_response_is_relayed(gateway):
    r = await post(
        gateway,
        "slow",
        "tools/call",
        {"name": "count", "arguments": {"n": 3}, "_meta": {"progressToken": "p1"}},
    )

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    messages = [json.loads(line[len("data:") :]) for line in r.text.splitlines() if line.startswith("data:")]
    progress = [m for m in messages if m.get("method") == "notifications/progress"]
    final = [m for m in messages if "result" in m]
    assert len(progress) == 3
    assert final[0]["result"]["structuredContent"] == {"result": 3}


# --- 4. Header-based access log --------------------------------------------


async def test_access_log_records_method_and_tool_name(gateway, caplog):
    caplog.set_level(logging.INFO, logger="gateway.access")

    await post(gateway, "math", "tools/call", {"name": "add", "arguments": {"a": 1, "b": 2}})

    [record] = [r for r in caplog.records if r.name == "gateway.access"]
    message = record.getMessage()
    assert "math" in message
    assert "tools/call" in message
    assert "add" in message


async def test_access_log_does_not_need_the_body(gateway, caplog):
    # A body the gateway cannot parse: logging must still work from headers alone,
    # and the upstream (not the gateway) decides how to answer it.
    caplog.set_level(logging.INFO, logger="gateway.access")
    headers, _ = mcp_request("tools/call", {"name": "add"})

    r = await gateway.post("/proxy/math/mcp", headers=headers, content=b"{not json")

    assert r.status_code < 500
    [record] = [r for r in caplog.records if r.name == "gateway.access"]
    assert "tools/call" in record.getMessage()
