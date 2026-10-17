import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum
from pathlib import Path

EVENT_COLUMNS = ["event_id", "start_time", "end_time", "machine_id", "error_code", "severity", "message"]


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class FaultEvent:
    event_id: str
    start_time: datetime
    end_time: datetime
    machine_id: str
    error_code: str
    severity: Severity
    message: str

    def to_row(self) -> list[str]:
        return [
            self.event_id,
            f"{self.start_time:%Y-%m-%d %H:%M}",
            f"{self.end_time:%Y-%m-%d %H:%M}",
            self.machine_id,
            self.error_code,
            self.severity.value,
            self.message,
        ]


def load_fault_events(csv_path: str | Path) -> list[FaultEvent]:
    with Path(csv_path).open(encoding="utf-8", newline="") as file:
        return [
            FaultEvent(
                event_id=row["event_id"],
                start_time=datetime.fromisoformat(row["start_time"]),
                end_time=datetime.fromisoformat(row["end_time"]),
                machine_id=row["machine_id"],
                error_code=row["error_code"],
                severity=Severity(row["severity"]),
                message=row["message"],
            )
            for row in csv.DictReader(file)
        ]


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
        starts_in_shift = [start for start in event_starts if start.time() >= start_time]
        shift_date = (starts_in_shift or event_starts)[0].date()
        start = datetime.combine(shift_date, start_time)
        end = datetime.combine(shift_date, end_time)
        if end < start:
            end += timedelta(days=1)
        return cls(start, end)

    @classmethod
    def for_log(cls, csv_path: str | Path, start_time: time, end_time: time) -> "ShiftWindow":
        return cls.for_events(load_fault_events(csv_path), start_time, end_time)


class FaultLogRepository:
    def __init__(self, csv_path: str | Path, shift_start: datetime, shift_end: datetime) -> None:
        self.shift_start = shift_start
        self.shift_end = shift_end
        self._events = load_fault_events(csv_path)

    def filter(self, machine_id: str | None = None, severity: Severity | None = None) -> list[FaultEvent]:
        return [
            event
            for event in self._events
            if (machine_id is None or event.machine_id == machine_id)
            and (severity is None or event.severity is severity)
        ]

    def machine_ids(self) -> list[str]:
        return sorted({event.machine_id for event in self._events})


def load_error_codes(json_path: str | Path) -> dict[str, dict[str, str]]:
    return json.loads(Path(json_path).read_text(encoding="utf-8"))


def downtime_minutes(events: Iterable[FaultEvent], shift_start: datetime, shift_end: datetime) -> float:
    intervals = sorted(
        (max(event.start_time, shift_start), min(event.end_time, shift_end))
        for event in events
        if event.end_time > shift_start and event.start_time < shift_end
    )
    merged: list[tuple[datetime, datetime]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum((end - start).total_seconds() for start, end in merged) / 60
