from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from maestro.core.trace import EventKind, Trace, TraceEvent
from maestro.llm.types import AssistantTurn, ToolCall
from maestro.tools.registry import ToolRegistry

MAX_TOOL_OUTPUT_CHARS = 4000
TRUNCATION_NOTE = "[truncated]"


class LLMLike(Protocol):
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> AssistantTurn: ...


class StopReason(Enum):
    FINAL_ANSWER = "final_answer"
    MAX_STEPS = "max_steps"


@dataclass
class AgentResult:
    answer: str
    steps: int
    stop_reason: StopReason
    trace_path: Path


class Agent:
    def __init__(
        self,
        llm: LLMLike,
        registry: ToolRegistry,
        system_prompt: str,
        max_steps: int,
        on_token: Callable[[str], None] | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._on_token = on_token
        self._on_event = on_event

    def run(self, task: str) -> AgentResult:
        trace = Trace()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": task},
        ]
        self._record(trace, 0, EventKind.TASK, {"task": task})

        for step in range(1, self._max_steps + 1):
            turn = self._llm.stream(messages, self._registry.schemas(), self._on_token)
            messages.append(turn.to_message())
            self._record(trace, step, EventKind.ASSISTANT, {"content": turn.content, "tool_calls": len(turn.tool_calls)})

            if not turn.has_tool_calls:
                self._record(trace, step, EventKind.FINAL, {"answer": turn.content})
                return AgentResult(turn.content, step, StopReason.FINAL_ANSWER, trace.save())

            for call in turn.tool_calls:
                messages.append(self._execute(trace, step, call))

        answer = f"Stopped: reached the limit of {self._max_steps} steps without a final answer."
        self._record(trace, self._max_steps, EventKind.STOPPED, {"reason": answer})
        return AgentResult(answer, self._max_steps, StopReason.MAX_STEPS, trace.save())

    def _execute(self, trace: Trace, step: int, call: ToolCall) -> dict[str, Any]:
        self._record(trace, step, EventKind.TOOL_CALL, {"id": call.id, "name": call.name, "arguments": call.arguments})
        result = self._registry.execute(call.name, call.arguments)
        content = _truncate(result.to_message())
        self._record(trace, step, EventKind.TOOL_RESULT, {"id": call.id, "name": call.name, "ok": result.ok, "content": content})
        return {"role": "tool", "tool_call_id": call.id, "content": content}

    def _record(self, trace: Trace, step: int, kind: EventKind, payload: dict[str, Any]) -> None:
        event = trace.add(step, kind, payload)
        if self._on_event is not None:
            self._on_event(event)


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    return f"{text[:MAX_TOOL_OUTPUT_CHARS]}\n{TRUNCATION_NOTE}"
