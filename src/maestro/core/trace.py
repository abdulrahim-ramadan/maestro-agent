import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class EventKind(Enum):
    TASK = "task"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"
    STOPPED = "stopped"


@dataclass(frozen=True)
class TraceEvent:
    step: int
    kind: EventKind
    payload: dict[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "kind": self.kind.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class Trace:
    def __init__(self) -> None:
        self._events: list[TraceEvent] = []

    def add(self, step: int, kind: EventKind, payload: dict[str, Any]) -> TraceEvent:
        event = TraceEvent(step=step, kind=kind, payload=payload, timestamp=datetime.now().isoformat())
        self._events.append(event)
        return event

    @property
    def events(self) -> list[TraceEvent]:
        return list(self._events)

    def save(self, directory: str | Path = "runs") -> Path:
        target_directory = Path(directory)
        target_directory.mkdir(parents=True, exist_ok=True)
        path = target_directory / f"trace_{datetime.now():%Y%m%d_%H%M%S}.json"
        content = json.dumps([event.to_dict() for event in self._events], ensure_ascii=False, indent=2, default=str)
        path.write_text(content, encoding="utf-8")
        return path
