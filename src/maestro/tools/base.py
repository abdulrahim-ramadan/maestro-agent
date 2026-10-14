import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None

    @classmethod
    def success(cls, data: Any = None) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, error: str) -> "ToolResult":
        return cls(ok=False, error=error)

    def to_message(self) -> str:
        payload = {"ok": self.ok, "data": self.data, "error": self.error}
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters: ClassVar[dict[str, Any]]

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult: ...

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
