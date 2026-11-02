"""Smoke tests for the M0 upstreams, run in-process (no ports needed)."""

import pytest
from fastapi.testclient import TestClient

from mcp import Client
from upstreams import math_server, notes_server, rest_api

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_math_tools():
    async with Client(math_server.server) as client:
        tools = await client.list_tools()
        assert [t.name for t in tools.tools] == ["add", "multiply"]

        result = await client.call_tool("add", {"a": 2, "b": 3})
        assert not result.is_error
        assert result.structured_content == {"result": 5.0}


async def test_math_invalid_arguments_is_tool_error():
    async with Client(math_server.server) as client:
        result = await client.call_tool("add", {"a": "x"})
        assert result.is_error


async def test_notes_create_then_list():
    async with Client(notes_server.server) as client:
        created = await client.call_tool("create_note", {"title": "t", "body": "b"})
        assert created.structured_content["title"] == "t"

        listed = await client.call_tool("list_notes", {})
        assert any(n["title"] == "t" for n in listed.structured_content["result"])


def test_rest_api():
    http = TestClient(rest_api.app)
    assert http.get("/weather/seoul").json()["condition"] == "clear"
    assert http.get("/weather/nowhere").status_code == 404

    created = http.post("/todos", json={"title": "write gateway"})
    assert created.status_code == 201
    assert http.get("/todos", params={"done": False}).json()[-1]["title"] == "write gateway"

    operation_ids = {
        op["operationId"]
        for path in http.get("/openapi.json").json()["paths"].values()
        for op in path.values()
    }
    assert operation_ids == {"get_weather", "list_todos", "create_todo"}
