"""Upstream MCP server `notes` (Streamable HTTP, :9002/mcp).

Notes live in memory, so they reset whenever the server restarts.
"""

from pydantic import BaseModel

from mcp.server.mcpserver import MCPServer

server = MCPServer(name="notes", version="0.1.0")


class Note(BaseModel):
    id: int
    title: str
    body: str


_notes: list[Note] = []


@server.tool()
def create_note(title: str, body: str) -> Note:
    """Create a note and return it."""
    note = Note(id=len(_notes) + 1, title=title, body=body)
    _notes.append(note)
    return note


@server.tool()
def list_notes() -> list[Note]:
    """List all notes."""
    return _notes


if __name__ == "__main__":
    server.run("streamable-http", port=9002, json_response=True)
