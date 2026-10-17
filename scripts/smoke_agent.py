import json
from typing import Any, ClassVar

from maestro.config import Settings
from maestro.core.agent import Agent
from maestro.core.trace import TraceEvent
from maestro.llm.client import LLMClient
from maestro.tools import Tool, ToolRegistry, ToolResult

MAX_LINE_CHARS = 100


class AddNumbersTool(Tool):
    name = "add_numbers"
    description = "Add two numbers and return the sum."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "a": {"type": "number", "description": "First number"},
            "b": {"type": "number", "description": "Second number"},
        },
        "required": ["a", "b"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.success(kwargs["a"] + kwargs["b"])


def print_event(event: TraceEvent) -> None:
    summary = json.dumps(event.payload, ensure_ascii=False)
    if len(summary) > MAX_LINE_CHARS:
        summary = summary[:MAX_LINE_CHARS] + "..."
    print(f"[step {event.step}] {event.kind.value:<11} {summary}")


def main() -> None:
    settings = Settings.from_env()
    registry = ToolRegistry()
    registry.register(AddNumbersTool())
    agent = Agent(
        LLMClient(settings),
        registry,
        system_prompt="You are a precise assistant. Use the available tools when asked.",
        max_steps=settings.max_steps,
        on_event=print_event,
    )

    result = agent.run("What is 1234 + 5678? Use the tool.")

    print()
    print(f"Answer: {result.answer}")
    print(f"Stop reason: {result.stop_reason.value}, steps: {result.steps}, trace: {result.trace_path}")


if __name__ == "__main__":
    main()
