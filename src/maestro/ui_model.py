import math
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum, auto
from pathlib import Path

from openai import APIError, RateLimitError

from maestro.config import ConfigError
from maestro.core.trace import EventKind, TraceEvent
from maestro.display import redact_secrets, short_arguments
from maestro.llm.client import QuotaExhaustedError, WaitReason
from maestro.prompts import ReportLanguage
from maestro.tools.factory import CalcDowntimeTool
from maestro.tools.factory_data import (
    FaultLogError,
    FaultLogRepository,
    ShiftWindow,
    load_fault_events,
)
from maestro.ui_texts import Text, t


class StepStatus(Enum):
    RUNNING = auto()
    OK = auto()
    FAILED = auto()

    @property
    def icon(self) -> str:
        return STEP_ICONS[self]


STEP_ICONS = {StepStatus.RUNNING: "⏳", StepStatus.OK: "✅", StepStatus.FAILED: "❌"}
WAIT_REASON_TEXTS = {WaitReason.PACING.value: Text.WAIT_REASON_PACING, WaitReason.RETRY_HINT.value: Text.WAIT_REASON_RETRY_HINT}


@dataclass
class StepRow:
    step: int
    tool: str
    arguments: str
    status: StepStatus

    def to_markdown(self, lang: ReportLanguage) -> str:
        arguments = self.arguments.replace("`", "'")
        return t(Text.STEP_LINE, lang, icon=self.status.icon, step=self.step, tool=self.tool, arguments=arguments)


@dataclass(frozen=True)
class WaitNotice:
    seconds: float
    reason: str

    def to_markdown(self, lang: ReportLanguage) -> str:
        reason_text = WAIT_REASON_TEXTS.get(self.reason)
        reason = t(reason_text, lang) if reason_text is not None else self.reason
        return t(Text.WAIT_LINE, lang, seconds=math.ceil(self.seconds), reason=reason)


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

    def to_markdown(self, lang: ReportLanguage) -> str:
        return "\n\n".join(entry.to_markdown(lang) for entry in self._entries)


class LogSource(Enum):
    UPLOAD = auto()
    SAMPLE = auto()


LOG_SOURCE_TEXTS = {LogSource.UPLOAD: Text.SOURCE_UPLOAD, LogSource.SAMPLE: Text.SOURCE_SAMPLE}


def log_source_label(source: LogSource, lang: ReportLanguage) -> str:
    return t(LOG_SOURCE_TEXTS[source], lang)


class ShiftPreset(Enum):
    EARLY = auto()
    LATE = auto()
    NIGHT = auto()
    CUSTOM = auto()


SHIFT_PRESET_TIMES = {
    ShiftPreset.EARLY: (time(6, 0), time(14, 0)),
    ShiftPreset.LATE: (time(14, 0), time(22, 0)),
    ShiftPreset.NIGHT: (time(22, 0), time(6, 0)),
}
SHIFT_PRESET_TEXTS = {
    ShiftPreset.EARLY: Text.SHIFT_EARLY,
    ShiftPreset.LATE: Text.SHIFT_LATE,
    ShiftPreset.NIGHT: Text.SHIFT_NIGHT,
    ShiftPreset.CUSTOM: Text.SHIFT_CUSTOM,
}
CLOCK_FORMAT = "%H:%M"


def preset_label(preset: ShiftPreset, lang: ReportLanguage) -> str:
    if preset is ShiftPreset.CUSTOM:
        return t(Text.SHIFT_CUSTOM, lang)
    start, end = SHIFT_PRESET_TIMES[preset]
    return t(SHIFT_PRESET_TEXTS[preset], lang, start=start.strftime(CLOCK_FORMAT), end=end.strftime(CLOCK_FORMAT))


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

    @property
    def shift_is_empty(self) -> bool:
        return self.events_in_shift == 0

    def details(self, lang: ReportLanguage) -> str:
        date_format = t(Text.DATE_TIME_FORMAT, lang)
        return t(
            Text.PREVIEW_DETAILS,
            lang,
            machines=", ".join(self.machine_ids),
            first=self.first_event.strftime(date_format),
            last=self.last_event.strftime(date_format),
            start=self.shift.start.strftime(date_format),
            end=self.shift.end.strftime(date_format),
        )


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


def can_generate(preview: LogPreview | None, empty_report_confirmed: bool) -> bool:
    return preview is not None and (not preview.shift_is_empty or empty_report_confirmed)


def downtime_by_machine(log_path: str | Path, shift: ShiftWindow) -> dict[str, float]:
    repository = FaultLogRepository(log_path, shift.start, shift.end)
    machines = CalcDowntimeTool(repository).run().data["machines"]
    return {machine["machine_id"]: machine["downtime_minutes"] for machine in machines}


FILE_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"


def report_file_name(language: ReportLanguage, created_at: datetime) -> str:
    return t(Text.REPORT_FILE_NAME, language, timestamp=created_at.strftime(FILE_TIMESTAMP_FORMAT))


@dataclass(frozen=True)
class ErrorMessage:
    summary: str
    details: str | None = None


def describe_error(error: Exception, lang: ReportLanguage) -> ErrorMessage:
    message = redact_secrets(str(error))
    error_type = type(error).__name__
    if isinstance(error, RateLimitError):
        return ErrorMessage(t(Text.RATE_LIMIT_SUMMARY, lang), f"{error_type}: {message}")
    if isinstance(error, QuotaExhaustedError):
        return ErrorMessage(t(Text.QUOTA_SUMMARY, lang), f"{error_type}: {message}")
    if isinstance(error, ConfigError):
        return ErrorMessage(t(Text.CONFIG_ERROR, lang, message=message))
    if isinstance(error, FaultLogError):
        return ErrorMessage(t(Text.FAULT_LOG_ERROR, lang, message=message))
    if isinstance(error, APIError):
        return ErrorMessage(t(Text.API_ERROR, lang, error_type=error_type, message=message))
    if isinstance(error, ValueError):
        return ErrorMessage(t(Text.INVALID_INPUT, lang, message=message))
    return ErrorMessage(t(Text.UNEXPECTED_ERROR, lang, error_type=error_type, message=message))
