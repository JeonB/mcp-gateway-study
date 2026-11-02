"""Plain REST API (:9003) that M4 turns into MCP tools.

The OpenAPI spec is served at /openapi.json.
"""

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Sample REST API", version="0.1.0")

_WEATHER = {
    "seoul": {"city": "seoul", "temp_c": 12.5, "condition": "clear"},
    "busan": {"city": "busan", "temp_c": 16.0, "condition": "cloudy"},
}


class TodoIn(BaseModel):
    title: str
    done: bool = False


class Todo(TodoIn):
    id: int


_todos: list[Todo] = []


@app.get("/weather/{city}", operation_id="get_weather")
def get_weather(city: str) -> dict:
    """Get the current weather for a city."""
    if city.lower() not in _WEATHER:
        raise HTTPException(404, f"unknown city: {city}")
    return _WEATHER[city.lower()]


@app.get("/todos", operation_id="list_todos")
def list_todos(done: bool | None = None) -> list[Todo]:
    """List todos, optionally filtered by completion state."""
    return [t for t in _todos if done is None or t.done == done]


@app.post("/todos", operation_id="create_todo", status_code=201)
def create_todo(todo: TodoIn) -> Todo:
    """Create a todo."""
    created = Todo(id=len(_todos) + 1, **todo.model_dump())
    _todos.append(created)
    return created


if __name__ == "__main__":
    uvicorn.run(app, port=9003)
