from enum import Enum
from typing import Any, Protocol

from maestro.knowledge.store import SearchHit
from maestro.tools.base import Tool, ToolResult

MAX_HITS = 3


class MachineType(Enum):
    WELDING_ROBOT = "welding_robot"
    CONVEYOR = "conveyor"
    PRESS = "press"
    SCREWDRIVING_STATION = "screwdriving_station"


class ManualSearcher(Protocol):
    def search(self, query: str, k: int = 3, source: str | None = None) -> list[SearchHit]: ...


class SearchManualsTool(Tool):
    name = "search_manuals"
    description = (
        "Search the maintenance manuals for symptoms, error codes, repair steps and safety notes. "
        "Returns matching sections with source manual and heading for citation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Problem description or error code, for example 'wire feed jam E101'"},
            "machine_type": {
                "type": ["string", "null"],
                "enum": [*(machine_type.value for machine_type in MachineType), None],
                "description": "Limit the search to one machine's manual; null searches all manuals",
            },
        },
        "required": ["query"],
    }

    def __init__(self, store: ManualSearcher) -> None:
        self._store = store

    def run(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult.failure("query must not be empty")

        machine_type = kwargs.get("machine_type")
        valid_types = [member.value for member in MachineType]
        if machine_type is not None and machine_type not in valid_types:
            return ToolResult.failure(f"unknown machine_type '{machine_type}'; valid types: {', '.join(valid_types)}")

        hits = self._store.search(query, k=MAX_HITS, source=machine_type)
        return ToolResult.success(
            {
                "query": query,
                "hits": [
                    {"source": f"{hit.source}.md", "heading": hit.heading, "score": hit.score, "text": hit.text}
                    for hit in hits
                ],
            }
        )
