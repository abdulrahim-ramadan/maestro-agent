from dataclasses import dataclass, field
from typing import Any

from maestro.llm.types import AssistantTurn, TokenUsage, ToolCall


@dataclass
class _PartialToolCall:
    id: str = ""
    name: str = ""
    argument_parts: list[str] = field(default_factory=list)


class StreamAccumulator:
    def __init__(self) -> None:
        self._text_parts: list[str] = []
        self._tool_calls: dict[int, _PartialToolCall] = {}
        self.usage: TokenUsage | None = None

    def feed(self, chunk: Any) -> str:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self.usage = TokenUsage(prompt_tokens=usage.prompt_tokens, total_tokens=usage.total_tokens)
        if not chunk.choices:
            return ""
        delta = chunk.choices[0].delta

        for tool_call_delta in getattr(delta, "tool_calls", None) or []:
            partial = self._tool_calls.setdefault(tool_call_delta.index, _PartialToolCall())
            if tool_call_delta.id:
                partial.id = tool_call_delta.id
            function = getattr(tool_call_delta, "function", None)
            if function is not None:
                if function.name:
                    partial.name = function.name
                if function.arguments:
                    partial.argument_parts.append(function.arguments)

        text = getattr(delta, "content", None) or ""
        if text:
            self._text_parts.append(text)
        return text

    def result(self) -> AssistantTurn:
        tool_calls = [
            ToolCall(id=partial.id, name=partial.name, arguments="".join(partial.argument_parts))
            for _, partial in sorted(self._tool_calls.items())
        ]
        return AssistantTurn(content="".join(self._text_parts), tool_calls=tool_calls)
