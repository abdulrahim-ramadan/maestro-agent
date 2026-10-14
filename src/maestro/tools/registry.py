import json
from typing import Any

from maestro.tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(self, name: str, raw_arguments: str) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            available = ", ".join(self.names()) or "none"
            return ToolResult.failure(f"unknown tool '{name}'; available tools: {available}")

        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, TypeError):
            return ToolResult.failure("invalid JSON arguments")
        if not isinstance(arguments, dict):
            return ToolResult.failure("invalid JSON arguments")

        required = tool.parameters.get("required", [])
        missing = [param for param in required if param not in arguments]
        if missing:
            return ToolResult.failure(f"missing required parameters: {', '.join(missing)}")

        try:
            return tool.run(**arguments)
        except Exception as exc:
            return ToolResult.failure(f"{type(exc).__name__}: {exc}")
