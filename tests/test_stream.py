from types import SimpleNamespace
from typing import Any

from maestro.llm.stream import StreamAccumulator
from maestro.llm.types import AssistantTurn, ToolCall


def text_chunk(text: str) -> SimpleNamespace:
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def tool_chunk(index: int, id: str | None = None, name: str | None = None, arguments: str | None = None) -> SimpleNamespace:
    tool_call = SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments))
    delta = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def feed_all(accumulator: StreamAccumulator, chunks: list[Any]) -> list[str]:
    return [accumulator.feed(chunk) for chunk in chunks]


def test_text_only_stream() -> None:
    accumulator = StreamAccumulator()

    deltas = feed_all(accumulator, [text_chunk("Guten "), text_chunk("Morgen"), text_chunk("!")])
    turn = accumulator.result()

    assert deltas == ["Guten ", "Morgen", "!"]
    assert turn == AssistantTurn(content="Guten Morgen!", tool_calls=[])
    assert not turn.has_tool_calls
    assert turn.to_message() == {"role": "assistant", "content": "Guten Morgen!"}


def test_single_tool_call_split_across_chunks() -> None:
    accumulator = StreamAccumulator()

    deltas = feed_all(
        accumulator,
        [
            tool_chunk(0, id="call_1", name="read_log"),
            tool_chunk(0, arguments='{"mach'),
            tool_chunk(0, arguments='ine": "P'),
            tool_chunk(0, arguments='3"}'),
        ],
    )
    turn = accumulator.result()

    assert deltas == ["", "", "", ""]
    assert turn.has_tool_calls
    assert turn.tool_calls == [ToolCall(id="call_1", name="read_log", arguments='{"machine": "P3"}')]
    assert turn.to_message() == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_log", "arguments": '{"machine": "P3"}'},
            }
        ],
    }


def test_two_parallel_tool_calls() -> None:
    accumulator = StreamAccumulator()

    feed_all(
        accumulator,
        [
            tool_chunk(0, id="call_a", name="read_log"),
            tool_chunk(1, id="call_b", name="search_manual"),
            tool_chunk(1, arguments='{"query": '),
            tool_chunk(0, arguments='{"machine": "P3"}'),
            tool_chunk(1, arguments='"E-104"}'),
        ],
    )
    turn = accumulator.result()

    assert turn.tool_calls == [
        ToolCall(id="call_a", name="read_log", arguments='{"machine": "P3"}'),
        ToolCall(id="call_b", name="search_manual", arguments='{"query": "E-104"}'),
    ]
