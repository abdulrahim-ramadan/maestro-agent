from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from pathlib import Path

from openai import APIError, RateLimitError

from maestro.config import ConfigError
from maestro.core.trace import EventKind, TraceEvent
from maestro.display import redact_secrets, short_arguments, wait_message
from maestro.llm.client import QuotaExhaustedError
from maestro.prompts import ReportLanguage
from maestro.tools.factory import CalcDowntimeTool
from maestro.tools.factory_data import (
    FaultLogError,
    FaultLogRepository,
    ShiftWindow,
    load_fault_events,
)

RATE_LIMIT_SUMMARY = "The AI service limit was reached. Wait one minute and try again."
QUOTA_SUMMARY = "Today's quota is used up. Try again tomorrow."


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


@dataclass(frozen=True)
class WaitNotice:
    seconds: float
    reason: str

    def to_markdown(self) -> str:
        return f"🕒 {wait_message(self.seconds, self.reason)}"


class StepTracker:
    def __init__(self) -> None:
        self._entries: list[StepRow | WaitNotice] = []
        self._rows_by_call: dict[str, StepRow] = {}

    def on_event(self, event: TraceEvent) -> None:
        if event.kind is EventKind.TOOL_CALL:
            row = StepRow(
                step=event.step,
                tool=event.payload["name"],
                arguments=short_arguments(event.payload["arguments"]),
                status=StepStatus.RUNNING,
            )
            self._rows_by_call[event.payload["id"]] = row
            self._entries.append(row)
        elif event.kind is EventKind.TOOL_RESULT and event.payload["id"] in self._rows_by_call:
            self._rows_by_call[event.payload["id"]].status = StepStatus.OK if event.payload["ok"] else StepStatus.FAILED

    def on_wait(self, seconds: float, reason: str) -> None:
        self._entries.append(WaitNotice(seconds, reason))

    @property
    def rows(self) -> list[StepRow]:
        return [entry for entry in self._entries if isinstance(entry, StepRow)]

    def to_markdown(self) -> str:
        return "\n\n".join(entry.to_markdown() for entry in self._entries)


class ShiftPreset(Enum):
    EARLY = "Frühschicht"
    LATE = "Spätschicht"
    NIGHT = "Nachtschicht"
    CUSTOM = "Custom"


SHIFT_PRESET_TIMES = {
    ShiftPreset.EARLY: (time(6, 0), time(14, 0)),
    ShiftPreset.LATE: (time(14, 0), time(22, 0)),
    ShiftPreset.NIGHT: (time(22, 0), time(6, 0)),
}


def preset_label(preset: ShiftPreset) -> str:
    if preset is ShiftPreset.CUSTOM:
        return preset.value
    start, end = SHIFT_PRESET_TIMES[preset]
    return f"{preset.value} {start:%H:%M}–{end:%H:%M}"


def shift_times(preset: ShiftPreset, custom_start: time, custom_end: time) -> tuple[time, time]:
    return (custom_start, custom_end) if preset is ShiftPreset.CUSTOM else SHIFT_PRESET_TIMES[preset]


@dataclass(frozen=True)
class LogPreview:
    event_count: int
    machine_ids: list[str]
    first_event: datetime
    last_event: datetime
    events_in_shift: int
    shift: ShiftWindow


def preview_log(log_path: str | Path, start_time: time, end_time: time) -> LogPreview:
    events = load_fault_events(log_path)
    shift = ShiftWindow.for_events(events, start_time, end_time)
    repository = FaultLogRepository(log_path, shift.start, shift.end)
    return LogPreview(
        event_count=len(events),
        machine_ids=repository.machine_ids(),
        first_event=min(event.start_time for event in events),
        last_event=max(event.end_time or event.start_time for event in events),
        events_in_shift=len(repository.filter()),
        shift=shift,
    )


def downtime_by_machine(log_path: str | Path, shift: ShiftWindow) -> dict[str, float]:
    repository = FaultLogRepository(log_path, shift.start, shift.end)
    machines = CalcDowntimeTool(repository).run().data["machines"]
    return {machine["machine_id"]: machine["downtime_minutes"] for machine in machines}


def report_file_name(language: ReportLanguage, created_at: datetime) -> str:
    return f"shift_report_{created_at:%Y%m%d_%H%M%S}_{language.value}.md"


@dataclass(frozen=True)
class ErrorMessage:
    summary: str
    details: str | None = None


def describe_error(error: Exception) -> ErrorMessage:
    message = redact_secrets(str(error))
    if isinstance(error, RateLimitError):
        return ErrorMessage(RATE_LIMIT_SUMMARY, f"{type(error).__name__}: {message}")
    if isinstance(error, QuotaExhaustedError):
        return ErrorMessage(QUOTA_SUMMARY, f"{type(error).__name__}: {message}")
    if isinstance(error, ConfigError):
        label = "Configuration error"
    elif isinstance(error, FaultLogError):
        label = "Fault log error"
    elif isinstance(error, APIError):
        label = f"API error ({type(error).__name__})"
    elif isinstance(error, ValueError):
        label = "Invalid input"
    else:
        label = f"Unexpected error ({type(error).__name__})"
    return ErrorMessage(f"{label}: {message}")
