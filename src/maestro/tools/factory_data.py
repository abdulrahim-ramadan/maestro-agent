import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


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

    def to_dict(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "start_time": self.start_time.isoformat(sep=" "),
            "end_time": self.end_time.isoformat(sep=" "),
            "machine_id": self.machine_id,
            "error_code": self.error_code,
            "severity": self.severity.value,
            "message": self.message,
        }


class FaultLogRepository:
    def __init__(self, csv_path: str | Path, shift_start: datetime, shift_end: datetime) -> None:
        self.shift_start = shift_start
        self.shift_end = shift_end
        self._events = self._load(Path(csv_path))

    @staticmethod
    def _load(csv_path: Path) -> list[FaultEvent]:
        with csv_path.open(encoding="utf-8", newline="") as file:
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

    def filter(self, machine_id: str | None = None, severity: Severity | None = None) -> list[FaultEvent]:
        return [
            event
            for event in self._events
            if (machine_id is None or event.machine_id == machine_id)
            and (severity is None or event.severity is severity)
        ]

    def machine_ids(self) -> list[str]:
        return sorted({event.machine_id for event in self._events})


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
