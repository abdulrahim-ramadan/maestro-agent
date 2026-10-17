from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from openai import APIError

from maestro.config import ConfigError
from maestro.core.trace import EventKind, TraceEvent
from maestro.display import redact_secrets, short_arguments
from maestro.llm.client import QuotaExhaustedError
from maestro.prompts import ReportLanguage
from maestro.tools.factory import CalcDowntimeTool
from maestro.tools.factory_data import FaultLogError, FaultLogRepository, ShiftWindow


class StepStatus(Enum):
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"

    @property
    def icon(self) -> str:
        return {"running": "⏳", "ok": "✅", "failed": "❌"}[self.value]


@dataclass
class StepRow:
    step: int
    tool: str
    arguments: str
    status: StepStatus

    def to_markdown(self) -> str:
        arguments = self.arguments.replace("`", "'")
        return f"{self.status.icon} step {self.step} **{self.tool}** `{arguments}`"


class StepTracker:
    def __init__(self) -> None:
        self._rows: dict[str, StepRow] = {}

    def on_event(self, event: TraceEvent) -> None:
        if event.kind is EventKind.TOOL_CALL:
            self._rows[event.payload["id"]] = StepRow(
                step=event.step,
                tool=event.payload["name"],
                arguments=short_arguments(event.payload["arguments"]),
                status=StepStatus.RUNNING,
            )
        elif event.kind is EventKind.TOOL_RESULT and event.payload["id"] in self._rows:
            self._rows[event.payload["id"]].status = StepStatus.OK if event.payload["ok"] else StepStatus.FAILED

    @property
    def rows(self) -> list[StepRow]:
        return list(self._rows.values())

    def to_markdown(self) -> str:
        return "\n\n".join(row.to_markdown() for row in self.rows)


def downtime_by_machine(log_path: str | Path, shift: ShiftWindow) -> dict[str, float]:
    repository = FaultLogRepository(log_path, shift.start, shift.end)
    machines = CalcDowntimeTool(repository).run().data["machines"]
    return {machine["machine_id"]: machine["downtime_minutes"] for machine in machines}


def report_file_name(language: ReportLanguage, created_at: datetime) -> str:
    return f"shift_report_{created_at:%Y%m%d_%H%M%S}_{language.value}.md"


def describe_error(error: Exception) -> str:
    if isinstance(error, ConfigError):
        label = "Configuration error"
    elif isinstance(error, QuotaExhaustedError):
        label = "Quota exhausted"
    elif isinstance(error, FaultLogError):
        label = "Fault log error"
    elif isinstance(error, APIError):
        label = f"API error ({type(error).__name__})"
    elif isinstance(error, ValueError):
        label = "Invalid input"
    else:
        label = f"Unexpected error ({type(error).__name__})"
    return f"{label}: {redact_secrets(str(error))}"
