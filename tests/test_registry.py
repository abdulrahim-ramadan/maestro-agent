import json
from typing import Any

import pytest

from maestro.tools import Tool, ToolRegistry, ToolResult


class EchoTool(Tool):
    name = "echo"
    description = "Echo the given text back."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        text = kwargs["text"]
        if text == "boom":
            raise RuntimeError("echo exploded")
        return ToolResult.success(text)


class PingTool(Tool):
    name = "ping"
    description = "Answer with pong."
    parameters = {"type": "object", "properties": {}}

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.success("pong")


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(EchoTool())
    return registry


def test_schema_uses_openai_function_format(registry: ToolRegistry) -> None:
    assert registry.schemas() == [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo the given text back.",
                "parameters": EchoTool.parameters,
            },
        }
    ]


def test_successful_call(registry: ToolRegistry) -> None:
    result = registry.execute("echo", '{"text": "Störung an Presse 3"}')

    assert result == ToolResult(ok=True, data="Störung an Presse 3")
    assert json.loads(result.to_message()) == {
        "ok": True,
        "data": "Störung an Presse 3",
        "error": None,
    }
    assert "Störung" in result.to_message()


def test_unknown_tool_lists_available_names(registry: ToolRegistry) -> None:
    result = registry.execute("missing", "{}")

    assert not result.ok
    assert "missing" in result.error
    assert "echo" in result.error


def test_invalid_json(registry: ToolRegistry) -> None:
    result = registry.execute("echo", "{not json")

    assert result == ToolResult.failure("invalid JSON arguments")


@pytest.mark.parametrize("raw_arguments", ["", "   ", "\n\t"])
def test_empty_arguments_are_treated_as_empty_object(raw_arguments: str) -> None:
    registry = ToolRegistry()
    registry.register(PingTool())

    result = registry.execute("ping", raw_arguments)

    assert result == ToolResult.success("pong")


def test_missing_required_parameter(registry: ToolRegistry) -> None:
    result = registry.execute("echo", "{}")

    assert not result.ok
    assert "text" in result.error


def test_exception_inside_run_becomes_failure(registry: ToolRegistry) -> None:
    result = registry.execute("echo", '{"text": "boom"}')

    assert result == ToolResult.failure("RuntimeError: echo exploded")


def test_duplicate_registration_raises(registry: ToolRegistry) -> None:
    with pytest.raises(ValueError):
        registry.register(EchoTool())
