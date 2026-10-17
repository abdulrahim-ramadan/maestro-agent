from enum import Enum
from typing import Any, Protocol

from maestro.knowledge.store import SearchHit
from maestro.tools.base import Tool, ToolResult

MAX_HITS = 2
REPEATED_TEXT = "same section as in an earlier query result"
MAX_QUERIES = 5


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
        f"Pass up to {MAX_QUERIES} queries in one call. "
        "Returns the best matching manual section per query with source and heading for citation; "
        "a section already returned for an earlier query is not repeated."
    )
    parameters = {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_QUERIES,
                "description": "Problem descriptions or error codes, for example ['wire feed jam E101', 'part jam E202']",
            },
            "machine_type": {
                "type": ["string", "null"],
                "enum": [*(machine_type.value for machine_type in MachineType), None],
                "description": "Limit every query to one machine's manual; null searches all manuals",
            },
        },
        "required": ["queries"],
    }

    def __init__(self, store: ManualSearcher) -> None:
        self._store = store

    def run(self, **kwargs: Any) -> ToolResult:
        raw_queries = kwargs["queries"]
        if not isinstance(raw_queries, list) or not 1 <= len(raw_queries) <= MAX_QUERIES:
            return ToolResult.failure(f"queries must be a list of 1 to {MAX_QUERIES} strings")
        queries = [str(query).strip() for query in raw_queries]
        if not all(queries):
            return ToolResult.failure("queries must not contain empty strings")

        machine_type = kwargs.get("machine_type")
        valid_types = [member.value for member in MachineType]
        if machine_type is not None and machine_type not in valid_types:
            return ToolResult.failure(f"unknown machine_type '{machine_type}'; valid types: {', '.join(valid_types)}")

        sent_chunks: set[tuple[str, str, str]] = set()
        return ToolResult.success({"results": [self._search(query, machine_type, sent_chunks) for query in queries]})

    def _search(self, query: str, machine_type: str | None, sent_chunks: set[tuple[str, str, str]]) -> dict[str, Any]:
        found = self._store.search(query, k=MAX_HITS, source=machine_type)
        best_section = (found[0].source, found[0].heading) if found else None
        hits = []
        for hit in found:
            if (hit.source, hit.heading) != best_section:
                continue
            chunk = (hit.source, hit.heading, hit.text)
            text = REPEATED_TEXT if chunk in sent_chunks else hit.text
            sent_chunks.add(chunk)
            hits.append({"source": f"{hit.source}.md", "heading": hit.heading, "score": hit.score, "text": text})
        return {"query": query, "hits": hits}
