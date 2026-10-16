import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from maestro.core.agent import MAX_TOOL_OUTPUT_CHARS, TRUNCATION_NOTE, Agent, StopReason
from maestro.core.trace import EventKind, TraceEvent
from maestro.llm.types import AssistantTurn, ToolCall
from maestro.tools import Tool, ToolRegistry, ToolResult


class ScriptedLLM:
    def __init__(self, turns: list[AssistantTurn | Exception]) -> None:
        self._turns = turns
        self.received_messages: list[list[dict[str, Any]]] = []

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> AssistantTurn:
        self.received_messages.append(list(messages))
        turn = self._turns[len(self.received_messages) - 1]
        if isinstance(turn, Exception):
            raise turn
        return turn


class AddNumbersTool(Tool):
    name = "add_numbers"
    description = "Add two numbers."
    parameters = {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.success(kwargs["a"] + kwargs["b"])


class BrokenSensorTool(Tool):
    name = "read_sensor"
    description = "Read a sensor value."
    parameters = {"type": "object", "properties": {}}

    def run(self, **kwargs: Any) -> ToolResult:
        raise ConnectionError("sensor offline")


class LongReportTool(Tool):
    name = "read_report"
    description = "Return a very long report."
    parameters = {"type": "object", "properties": {}}

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult.success("x" * 10_000)


def tool_turn(call_id: str, name: str, arguments: str) -> AssistantTurn:
    return AssistantTurn(content="", tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def final_turn(answer: str) -> AssistantTurn:
    return AssistantTurn(content=answer, tool_calls=[])


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def make_agent(llm: ScriptedLLM, tool: Tool, max_steps: int = 5, **callbacks: Any) -> Agent:
    registry = ToolRegistry()
    registry.register(tool)
    return Agent(llm, registry, system_prompt="You are a test agent.", max_steps=max_steps, **callbacks)


def test_tool_call_then_final_answer() -> None:
    llm = ScriptedLLM([tool_turn("call_1", "add_numbers", '{"a": 2, "b": 3}'), final_turn("The sum is 5.")])

    result = make_agent(llm, AddNumbersTool()).run("Add 2 and 3")

    assert result.answer == "The sum is 5."
    assert result.steps == 2
    assert result.stop_reason is StopReason.FINAL_ANSWER
    second_call_messages = llm.received_messages[1]
    assert second_call_messages[0] == {"role": "system", "content": "You are a test agent."}
    assert second_call_messages[1] == {"role": "user", "content": "Add 2 and 3"}
    assert second_call_messages[2]["tool_calls"][0]["id"] == "call_1"
    assert second_call_messages[3] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": ToolResult.success(5).to_message(),
    }


def test_failing_tool_error_reaches_model_and_run_finishes() -> None:
    llm = ScriptedLLM([tool_turn("call_1", "read_sensor", "{}"), final_turn("The sensor is offline.")])

    result = make_agent(llm, BrokenSensorTool()).run("Read the sensor")

    tool_message = llm.received_messages[1][-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"]) == {
        "ok": False,
        "data": None,
        "error": "ConnectionError: sensor offline",
    }
    assert result.stop_reason is StopReason.FINAL_ANSWER
    assert result.answer == "The sensor is offline."


def test_endless_tool_calls_stop_at_max_steps() -> None:
    endless = [tool_turn(f"call_{i}", "add_numbers", '{"a": 1, "b": 1}') for i in range(10)]
    llm = ScriptedLLM(endless)

    result = make_agent(llm, AddNumbersTool(), max_steps=3).run("Keep adding")

    assert result.stop_reason is StopReason.MAX_STEPS
    assert result.steps == 3
    assert len(llm.received_messages) == 3
    assert "3 steps" in result.answer


def test_long_tool_output_is_truncated_before_reaching_model() -> None:
    llm = ScriptedLLM([tool_turn("call_1", "read_report", "{}"), final_turn("done")])

    make_agent(llm, LongReportTool()).run("Read the report")

    content = llm.received_messages[1][-1]["content"]
    full_output = ToolResult.success("x" * 10_000).to_message()
    assert content == f"{full_output[:MAX_TOOL_OUTPUT_CHARS]}\n{TRUNCATION_NOTE}"
    assert len(content) == MAX_TOOL_OUTPUT_CHARS + len(TRUNCATION_NOTE) + 1


def test_trace_file_contains_every_event(tmp_path: Path) -> None:
    llm = ScriptedLLM([tool_turn("call_1", "add_numbers", '{"a": 2, "b": 3}'), final_turn("5")])
    emitted: list[TraceEvent] = []

    result = make_agent(llm, AddNumbersTool(), on_event=emitted.append).run("Add 2 and 3")

    assert result.trace_path.resolve().parent == (tmp_path / "runs").resolve()
    assert result.trace_path.name.startswith("trace_")
    saved = json.loads(result.trace_path.read_text(encoding="utf-8"))
    assert [(event["step"], event["kind"]) for event in saved] == [
        (0, "task"),
        (1, "assistant"),
        (1, "tool_call"),
        (1, "tool_result"),
        (2, "assistant"),
        (2, "final"),
    ]
    assert saved == [event.to_dict() for event in emitted]
    assert [event.kind for event in emitted][-1] is EventKind.FINAL


def test_failed_run_saves_trace_and_reraises(tmp_path: Path) -> None:
    llm = ScriptedLLM([tool_turn("call_1", "add_numbers", '{"a": 2, "b": 3}'), RuntimeError("provider down")])
    emitted: list[TraceEvent] = []

    with pytest.raises(RuntimeError, match="provider down"):
        make_agent(llm, AddNumbersTool(), on_event=emitted.append).run("Add 2 and 3")

    trace_files = list((tmp_path / "runs").glob("trace_*.json"))
    assert len(trace_files) == 1
    saved = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert [event["kind"] for event in saved] == ["task", "assistant", "tool_call", "tool_result", "error"]
    assert saved[-1]["step"] == 2
    assert saved[-1]["payload"] == {"stop_reason": "error", "error": "RuntimeError: provider down"}
    assert emitted[-1].kind is EventKind.ERROR


def test_failing_on_event_does_not_stop_the_run() -> None:
    llm = ScriptedLLM([tool_turn("call_1", "add_numbers", '{"a": 2, "b": 3}'), final_turn("5")])
    calls: list[TraceEvent] = []

    def broken_display(event: TraceEvent) -> None:
        calls.append(event)
        raise UnicodeEncodeError("charmap", " ", 0, 1, "character maps to <undefined>")

    result = make_agent(llm, AddNumbersTool(), on_event=broken_display).run("Add 2 and 3")

    assert result.answer == "5"
    assert result.stop_reason is StopReason.FINAL_ANSWER
    assert result.steps == 2
    assert len(calls) == 6
    saved = json.loads(result.trace_path.read_text(encoding="utf-8"))
    kinds = [event["kind"] for event in saved]
    assert kinds == [
        "task", "warning",
        "assistant", "warning",
        "tool_call", "warning",
        "tool_result", "warning",
        "assistant", "warning",
        "final", "warning",
    ]
    warning = saved[1]["payload"]
    assert warning["event_kind"] == "task"
    assert warning["error"].startswith("UnicodeEncodeError:")
