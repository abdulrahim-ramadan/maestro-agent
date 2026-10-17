import csv
import io
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from enum import Enum
from pathlib import Path

CSV_COLUMNS = ["event_id", "start_time", "end_time", "machine_id", "error_code", "severity", "message"]
EVENT_COLUMNS = [*CSV_COLUMNS, "open"]
FALLBACK_ENCODING = "cp1252"
DELIMITERS = ",;"
SNIFF_SAMPLE_CHARS = 4096
GERMAN_DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M")


class FaultLogError(Exception):
    def __init__(self, source: str, line: int, reason: str) -> None:
        super().__init__(f"{source} line {line}: {reason}")
        self.line = line
        self.reason = reason


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class FaultEvent:
    event_id: str
    start_time: datetime
    end_time: datetime | None
    machine_id: str
    error_code: str
    severity: Severity
    message: str
    is_open: bool = False

    def to_row(self) -> list[str | bool]:
        return [
            self.event_id,
            f"{self.start_time:%Y-%m-%d %H:%M}",
            "" if self.end_time is None else f"{self.end_time:%Y-%m-%d %H:%M}",
            self.machine_id,
            self.error_code,
            self.severity.value,
            self.message,
            self.is_open,
        ]

    def until_shift_end(self, shift_end: datetime) -> "FaultEvent":
        return replace(self, end_time=shift_end) if self.end_time is None else self


def _read_text(path: Path) -> str:
    content = path.read_bytes()
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode(FALLBACK_ENCODING)


def _detect_dialect(text: str) -> type[csv.Dialect] | csv.Dialect:
    try:
        return csv.Sniffer().sniff(text[:SNIFF_SAMPLE_CHARS], delimiters=DELIMITERS)
    except csv.Error:
        return csv.excel


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass
    for date_format in GERMAN_DATE_FORMATS:
        try:
            return datetime.strptime(value, date_format)
        except ValueError:
            continue
    return None


def load_fault_events(csv_path: str | Path) -> list[FaultEvent]:
    path = Path(csv_path)
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=_detect_dialect(text))
    reader.fieldnames = [name.strip() for name in reader.fieldnames or []]
    missing = [column for column in CSV_COLUMNS if column not in reader.fieldnames]
    if missing:
        raise FaultLogError(path.name, 1, f"missing columns: {', '.join(missing)}")

    events: list[FaultEvent] = []
    first_lines: dict[str, int] = {}
    for row in reader:
        line = reader.line_num
        values = {column: (row.get(column) or "").strip() for column in CSV_COLUMNS}
        event = _parse_event(values, lambda reason, line=line: FaultLogError(path.name, line, reason))
        if event.event_id in first_lines:
            raise FaultLogError(path.name, line, f"duplicate event_id '{event.event_id}' (first seen on line {first_lines[event.event_id]})")
        first_lines[event.event_id] = line
        events.append(event)
    return events


def _parse_event(values: dict[str, str], error: Callable[[str], FaultLogError]) -> FaultEvent:
    start_time = _parse_timestamp(values["start_time"])
    if start_time is None:
        raise error(f"invalid start_time '{values['start_time']}'")
    end_time = _parse_timestamp(values["end_time"]) if values["end_time"] else None
    if values["end_time"] and end_time is None:
        raise error(f"invalid end_time '{values['end_time']}'")
    if end_time is not None and end_time < start_time:
        raise error(f"end_time {end_time:%Y-%m-%d %H:%M} is before start_time {start_time:%Y-%m-%d %H:%M}")
    try:
        severity = Severity(values["severity"].lower())
    except ValueError:
        valid = ", ".join(member.value for member in Severity)
        raise error(f"unknown severity '{values['severity']}'; valid values: {valid}") from None
    return FaultEvent(
        event_id=values["event_id"],
        start_time=start_time,
        end_time=end_time,
        machine_id=values["machine_id"],
        error_code=values["error_code"],
        severity=severity,
        message=values["message"],
        is_open=end_time is None,
    )


@dataclass(frozen=True)
class ShiftWindow:
    start: datetime
    end: datetime

    @classmethod
    def for_events(cls, events: Iterable[FaultEvent], start_time: time, end_time: time) -> "ShiftWindow":
        if start_time == end_time:
            raise ValueError("shift start and end must differ")
        event_starts = sorted(event.start_time for event in events)
        if not event_starts:
            raise ValueError("the fault log has no events to date the shift")
        crosses_midnight = end_time < start_time
        shift_dates = [
            event_start.date() - timedelta(days=1) if crosses_midnight and event_start.time() < end_time else event_start.date()
            for event_start in event_starts
            if event_start.time() >= start_time or (crosses_midnight and event_start.time() < end_time)
        ]
        shift_date = shift_dates[0] if shift_dates else event_starts[0].date()
        start = datetime.combine(shift_date, start_time)
        end = datetime.combine(shift_date + timedelta(days=1) if crosses_midnight else shift_date, end_time)
        return cls(start, end)

    @classmethod
    def for_log(cls, csv_path: str | Path, start_time: time, end_time: time) -> "ShiftWindow":
        return cls.for_events(load_fault_events(csv_path), start_time, end_time)


class FaultLogRepository:
    def __init__(self, csv_path: str | Path, shift_start: datetime, shift_end: datetime) -> None:
        self.shift_start = shift_start
        self.shift_end = shift_end
        all_events = [event.until_shift_end(shift_end) for event in load_fault_events(csv_path)]
        self._machine_ids = sorted({event.machine_id for event in all_events})
        self._events = [event for event in all_events if event.end_time > shift_start and event.start_time < shift_end]

    def filter(self, machine_id: str | None = None, severity: Severity | None = None) -> list[FaultEvent]:
        return [
            event
            for event in self._events
            if (machine_id is None or event.machine_id == machine_id)
            and (severity is None or event.severity is severity)
        ]

    def machine_ids(self) -> list[str]:
        return list(self._machine_ids)


def load_error_codes(json_path: str | Path) -> dict[str, dict[str, str]]:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))


def downtime_minutes(events: Iterable[FaultEvent], shift_start: datetime, shift_end: datetime) -> float:
    resolved_events = [event.until_shift_end(shift_end) for event in events]
    intervals = sorted(
        (max(event.start_time, shift_start), min(event.end_time, shift_end))
        for event in resolved_events
        if event.end_time > shift_start and event.start_time < shift_end
    )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum((end - start).total_seconds() for start, end in merged) / 60
