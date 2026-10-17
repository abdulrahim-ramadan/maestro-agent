import difflib
from typing import Any, ClassVar

from maestro.tools.base import Tool, ToolResult
from maestro.tools.factory_data import EVENT_COLUMNS, FaultEvent, FaultLogRepository, Severity, downtime_minutes

MAX_EVENTS = 40
MAX_CLOSE_MATCHES = 3


def _unknown_machine(repository: FaultLogRepository, machine_id: str) -> ToolResult:
    return ToolResult.failure(f"unknown machine_id '{machine_id}'; valid IDs: {', '.join(repository.machine_ids())}")


def _critical_groups(events: list[FaultEvent]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for event in events:
        if event.severity is Severity.CRITICAL:
            groups.setdefault((event.machine_id, event.error_code), []).append(event.event_id)
    return [
        {"machine_id": machine_id, "error_code": error_code, "event_ids": event_ids}
        for (machine_id, error_code), event_ids in groups.items()
    ]


class ReadFaultLogTool(Tool):
    name = "read_fault_log"
    description = (
        "Read fault events of the current shift, optionally filtered by machine and severity. "
        "Each event is a row in the order given by columns; "
        "critical_groups lists the critical event IDs per machine and error code."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "machine_id": {"type": ["string", "null"], "description": "Machine ID, for example ROB-01; null for all machines"},
            "severity": {"type": ["string", "null"], "enum": [*(severity.value for severity in Severity), None]},
        },
    }

    def __init__(self, repository: FaultLogRepository) -> None:
        self._repository = repository

    def run(self, **kwargs: Any) -> ToolResult:
        machine_id = kwargs.get("machine_id")
        if machine_id is not None and machine_id not in self._repository.machine_ids():
            return _unknown_machine(self._repository, machine_id)

        severity_value = kwargs.get("severity")
        valid_severities = [severity.value for severity in Severity]
        if severity_value is not None and severity_value not in valid_severities:
            return ToolResult.failure(f"unknown severity '{severity_value}'; valid values: {', '.join(valid_severities)}")
        severity = Severity(severity_value) if severity_value is not None else None

        events = self._repository.filter(machine_id=machine_id, severity=severity)
        counts = {value: sum(event.severity.value == value for event in events) for value in valid_severities}
        return ToolResult.success(
            {
                "columns": EVENT_COLUMNS,
                "events": [event.to_row() for event in events[:MAX_EVENTS]],
                "counts": counts,
                "critical_groups": _critical_groups(events),
                "total": len(events),
                "truncated": len(events) > MAX_EVENTS,
            }
        )


class LookupErrorCodeTool(Tool):
    name = "lookup_error_code"
    description = (
        "Look up one or more error codes in one call: title, category, likely cause and severity. "
        "Pass every code you need at once."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "codes": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Error codes, for example [\"E101\", \"E202\"]",
            }
        },
        "required": ["codes"],
    }

    def __init__(self, error_codes: dict[str, dict[str, str]]) -> None:
        self._error_codes = error_codes

    def run(self, **kwargs: Any) -> ToolResult:
        raw_codes = kwargs["codes"]
        if not isinstance(raw_codes, list) or not raw_codes:
            return ToolResult.failure("codes must be a non-empty list of strings")

        codes = list(dict.fromkeys(str(code).strip().upper() for code in raw_codes))
        entries = [{"code": code, **self._error_codes[code]} for code in codes if code in self._error_codes]
        unknown = [
            {"code": code, "close_matches": difflib.get_close_matches(code, list(self._error_codes), n=MAX_CLOSE_MATCHES)}
            for code in codes
            if code not in self._error_codes
        ]
        return ToolResult.success({"entries": entries, "unknown": unknown})


class CalcDowntimeTool(Tool):
    name = "calc_downtime"
    description = (
        "Calculate downtime minutes and availability percent per machine for the current shift. "
        "Overlapping faults are counted once."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"machine_id": {"type": ["string", "null"], "description": "Machine ID; omit or null for all machines"}},
    }

    def __init__(self, repository: FaultLogRepository) -> None:
        self._repository = repository

    def run(self, **kwargs: Any) -> ToolResult:
        machine_id = kwargs.get("machine_id")
        if machine_id is not None and machine_id not in self._repository.machine_ids():
            return _unknown_machine(self._repository, machine_id)

        shift_start, shift_end = self._repository.shift_start, self._repository.shift_end
        shift_minutes = (shift_end - shift_start).total_seconds() / 60
        machine_ids = [machine_id] if machine_id is not None else self._repository.machine_ids()
        machines = []
        for current_id in machine_ids:
            downtime = downtime_minutes(self._repository.filter(machine_id=current_id), shift_start, shift_end)
            machines.append(
                {
                    "machine_id": current_id,
                    "downtime_minutes": round(downtime, 1),
                    "availability_percent": round((shift_minutes - downtime) / shift_minutes * 100, 1),
                }
            )
        return ToolResult.success({"machines": machines})
