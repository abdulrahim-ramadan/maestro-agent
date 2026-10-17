import csv
import json
from datetime import datetime, time
from pathlib import Path

import pytest

from maestro.tools import ToolRegistry
from maestro.tools.factory import (
    CalcDowntimeTool,
    LookupErrorCodeTool,
    ReadFaultLogTool,
)
from maestro.tools.factory_data import (
    FaultEvent,
    FaultLogRepository,
    Severity,
    ShiftWindow,
    downtime_minutes,
    load_error_codes,
)

SHIFT_START = datetime(2026, 10, 14, 6, 0)
SHIFT_END = datetime(2026, 10, 14, 14, 0)

ROWS = [
    ("EV-0001", "05:40", "06:25", "PRS-01", "E301", "critical", "Hydraulic pressure low"),
    ("EV-0002", "09:00", "09:30", "ROB-01", "E101", "critical", "Wire feed jam"),
    ("EV-0003", "09:15", "09:45", "ROB-01", "E103", "critical", "Torch collision detected"),
    ("EV-0004", "10:00", "10:03", "ROB-01", "E102", "warning", "Weld current out of tolerance"),
    ("EV-0005", "11:00", "11:00", "ROB-01", "E104", "info", "Tip dressing overdue"),
    ("EV-0006", "13:50", "14:20", "CNV-01", "E202", "critical", "Part jam at transfer point"),
]

ERROR_CODES = {
    "E101": {"title": "Wire feed jam", "category": "mechanical", "likely_cause": "Worn feed rollers", "severity": "critical"},
    "E102": {"title": "Weld current out of tolerance", "category": "process", "likely_cause": "Dirty contact tip", "severity": "warning"},
    "E103": {"title": "Torch collision detected", "category": "safety", "likely_cause": "Misplaced part", "severity": "critical"},
    "E104": {"title": "Tip dressing overdue", "category": "maintenance", "likely_cause": "Skipped cycle", "severity": "info"},
    "E301": {"title": "Hydraulic pressure low", "category": "hydraulic", "likely_cause": "Leak", "severity": "critical"},
}


def write_log(path: Path, rows: list[tuple[str, ...]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(["event_id", "start_time", "end_time", "machine_id", "error_code", "severity", "message"])
        for event_id, start, end, *rest in rows:
            writer.writerow([event_id, f"2026-10-14 {start}:00", f"2026-10-14 {end}:00", *rest])
    return path


@pytest.fixture
def repository(tmp_path: Path) -> FaultLogRepository:
    return FaultLogRepository(write_log(tmp_path / "fault_log.csv", ROWS), SHIFT_START, SHIFT_END)


def event(start: str, end: str) -> FaultEvent:
    return FaultEvent(
        event_id="EV-TEST",
        start_time=datetime.fromisoformat(f"2026-10-14 {start}"),
        end_time=datetime.fromisoformat(f"2026-10-14 {end}"),
        machine_id="ROB-01",
        error_code="E101",
        severity=Severity.CRITICAL,
        message="test",
    )


def test_overlapping_intervals_are_merged() -> None:
    events = [event("09:00", "09:30"), event("09:15", "09:45"), event("09:20", "09:25")]

    assert downtime_minutes(events, SHIFT_START, SHIFT_END) == 45


def test_touching_and_separate_intervals() -> None:
    events = [event("10:00", "10:10"), event("10:10", "10:20"), event("11:00", "11:05")]

    assert downtime_minutes(events, SHIFT_START, SHIFT_END) == 25


def test_intervals_are_clipped_to_the_shift() -> None:
    events = [event("05:40", "06:25"), event("13:50", "14:20"), event("04:00", "05:00")]

    assert downtime_minutes(events, SHIFT_START, SHIFT_END) == 35


def test_availability_math(repository: FaultLogRepository) -> None:
    result = CalcDowntimeTool(repository).run()

    machines = {machine["machine_id"]: machine for machine in result.data["machines"]}
    assert result.ok
    assert machines["ROB-01"] == {"machine_id": "ROB-01", "downtime_minutes": 48.0, "availability_percent": 90.0}
    assert machines["PRS-01"] == {"machine_id": "PRS-01", "downtime_minutes": 25.0, "availability_percent": 94.8}
    assert machines["CNV-01"] == {"machine_id": "CNV-01", "downtime_minutes": 10.0, "availability_percent": 97.9}


def test_calc_downtime_for_one_machine(repository: FaultLogRepository) -> None:
    result = CalcDowntimeTool(repository).run(machine_id="PRS-01")

    assert result.data == {"machines": [{"machine_id": "PRS-01", "downtime_minutes": 25.0, "availability_percent": 94.8}]}


def test_repository_filters(repository: FaultLogRepository) -> None:
    assert repository.machine_ids() == ["CNV-01", "PRS-01", "ROB-01"]
    assert [e.event_id for e in repository.filter(machine_id="ROB-01")] == ["EV-0002", "EV-0003", "EV-0004", "EV-0005"]
    assert [e.event_id for e in repository.filter(severity=Severity.WARNING)] == ["EV-0004"]
    assert [e.event_id for e in repository.filter(machine_id="ROB-01", severity=Severity.CRITICAL)] == ["EV-0002", "EV-0003"]


def test_read_fault_log_filters_and_counts(repository: FaultLogRepository) -> None:
    result = ReadFaultLogTool(repository).run(machine_id="ROB-01", severity="critical")

    assert result.ok
    assert [row[0] for row in result.data["events"]] == ["EV-0002", "EV-0003"]
    assert result.data["counts"] == {"info": 0, "warning": 0, "critical": 2}


def test_read_fault_log_returns_at_most_40_events(tmp_path: Path) -> None:
    rows = [(f"EV-{n:04d}", "07:00", "07:05", "ROB-01", "E102", "warning", "x") for n in range(1, 46)]
    repository = FaultLogRepository(write_log(tmp_path / "many.csv", rows), SHIFT_START, SHIFT_END)

    result = ReadFaultLogTool(repository).run()

    assert len(result.data["events"]) == 40
    assert result.data["counts"] == {"info": 0, "warning": 45, "critical": 0}
    assert result.data["total"] == 45
    assert result.data["truncated"] is True


def test_read_fault_log_returns_compact_rows(repository: FaultLogRepository) -> None:
    result = ReadFaultLogTool(repository).run(machine_id="PRS-01")

    assert result.data["columns"] == [
        "event_id", "start_time", "end_time", "machine_id", "error_code", "severity", "message", "open"
    ]
    assert result.data["events"] == [
        ["EV-0001", "2026-10-14 05:40", "2026-10-14 06:25", "PRS-01", "E301", "critical", "Hydraulic pressure low", False]
    ]


def test_read_fault_log_groups_critical_events(repository: FaultLogRepository) -> None:
    result = ReadFaultLogTool(repository).run()

    assert result.data["critical_groups"] == [
        {"machine_id": "PRS-01", "error_code": "E301", "event_ids": ["EV-0001"]},
        {"machine_id": "ROB-01", "error_code": "E101", "event_ids": ["EV-0002"]},
        {"machine_id": "ROB-01", "error_code": "E103", "event_ids": ["EV-0003"]},
        {"machine_id": "CNV-01", "error_code": "E202", "event_ids": ["EV-0006"]},
    ]


def test_read_fault_log_not_truncated_below_limit(repository: FaultLogRepository) -> None:
    result = ReadFaultLogTool(repository).run()

    assert len(result.data["events"]) == 6
    assert result.data["total"] == 6
    assert result.data["truncated"] is False


def test_null_optional_arguments_mean_no_filter(repository: FaultLogRepository) -> None:
    registry = ToolRegistry()
    registry.register(ReadFaultLogTool(repository))
    registry.register(CalcDowntimeTool(repository))

    read_result = registry.execute("read_fault_log", '{"machine_id": null, "severity": null}')
    calc_result = registry.execute("calc_downtime", '{"machine_id": null}')

    assert read_result.ok and read_result.data["total"] == 6
    assert calc_result.ok and len(calc_result.data["machines"]) == 3


def test_read_fault_log_rejects_unknown_severity(repository: FaultLogRepository) -> None:
    result = ReadFaultLogTool(repository).run(severity="fatal")

    assert not result.ok
    assert "info, warning, critical" in result.error


@pytest.mark.parametrize("tool_class", [ReadFaultLogTool, CalcDowntimeTool])
def test_unknown_machine_lists_valid_ids(repository: FaultLogRepository, tool_class: type) -> None:
    result = tool_class(repository).run(machine_id="ROB-99")

    assert not result.ok
    assert "ROB-99" in result.error
    assert "CNV-01, PRS-01, ROB-01" in result.error


def test_load_error_codes(tmp_path: Path) -> None:
    path = tmp_path / "error_codes.json"
    path.write_text(json.dumps(ERROR_CODES), encoding="utf-8")

    assert load_error_codes(path) == ERROR_CODES


def test_lookup_known_code() -> None:
    result = LookupErrorCodeTool(ERROR_CODES).run(codes=[" e101 "])

    assert result.data == {"entries": [{"code": "E101", **ERROR_CODES["E101"]}], "unknown": []}


def test_lookup_several_codes_in_one_call() -> None:
    result = LookupErrorCodeTool(ERROR_CODES).run(codes=["E301", "e101", "E301"])

    assert result.ok
    assert [entry["code"] for entry in result.data["entries"]] == ["E301", "E101"]
    assert result.data["unknown"] == []


def test_unknown_code_lists_up_to_three_close_matches() -> None:
    result = LookupErrorCodeTool(ERROR_CODES).run(codes=["E101", "E10"])

    assert result.ok
    assert [entry["code"] for entry in result.data["entries"]] == ["E101"]
    unknown = result.data["unknown"]
    assert [item["code"] for item in unknown] == ["E10"]
    assert 1 <= len(unknown[0]["close_matches"]) <= 3
    assert all(match.startswith("E10") for match in unknown[0]["close_matches"])


def test_unknown_code_without_close_matches() -> None:
    result = LookupErrorCodeTool(ERROR_CODES).run(codes=["XYZ-999"])

    assert result.data == {"entries": [], "unknown": [{"code": "XYZ-999", "close_matches": []}]}


@pytest.mark.parametrize("codes", [[], "E101"])
def test_lookup_rejects_empty_or_non_list_codes(codes: object) -> None:
    result = LookupErrorCodeTool(ERROR_CODES).run(codes=codes)

    assert result == result.failure("codes must be a non-empty list of strings")


def test_shift_window_uses_date_of_first_event_in_shift() -> None:
    events = [event("05:40", "06:25"), event("09:00", "09:30")]

    shift = ShiftWindow.for_events(events, time(6, 0), time(14, 0))

    assert shift == ShiftWindow(datetime(2026, 10, 14, 6, 0), datetime(2026, 10, 14, 14, 0))


def test_night_shift_ends_on_the_next_day() -> None:
    events = [event("22:30", "23:00")]

    shift = ShiftWindow.for_events(events, time(22, 0), time(6, 0))

    assert shift == ShiftWindow(datetime(2026, 10, 14, 22, 0), datetime(2026, 10, 15, 6, 0))


def test_night_shift_with_only_events_after_midnight_started_the_day_before() -> None:
    events = [event("01:00", "01:30"), event("04:10", "04:40")]

    shift = ShiftWindow.for_events(events, time(22, 0), time(6, 0))

    assert shift == ShiftWindow(datetime(2026, 10, 13, 22, 0), datetime(2026, 10, 14, 6, 0))


def test_shift_window_falls_back_to_first_event_date() -> None:
    shift = ShiftWindow.for_events([event("04:00", "04:30")], time(6, 0), time(14, 0))

    assert shift == ShiftWindow(datetime(2026, 10, 14, 6, 0), datetime(2026, 10, 14, 14, 0))


@pytest.mark.parametrize(
    "events, start, end, message",
    [
        ([], time(6, 0), time(14, 0), "no events"),
        ([event("09:00", "09:30")], time(6, 0), time(6, 0), "must differ"),
    ],
)
def test_shift_window_rejects_invalid_input(events: list[FaultEvent], start: time, end: time, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ShiftWindow.for_events(events, start, end)


def test_shift_window_for_log(tmp_path: Path) -> None:
    path = write_log(tmp_path / "fault_log.csv", ROWS)

    assert ShiftWindow.for_log(path, time(6, 0), time(14, 0)) == ShiftWindow(SHIFT_START, SHIFT_END)


LATE_SHIFT_START = datetime(2026, 10, 14, 14, 0)
LATE_SHIFT_END = datetime(2026, 10, 14, 22, 0)
DATA_LOG = Path(__file__).resolve().parent.parent / "data" / "fault_log.csv"


def test_repository_only_returns_events_overlapping_the_shift(tmp_path: Path) -> None:
    repository = FaultLogRepository(write_log(tmp_path / "fault_log.csv", ROWS), LATE_SHIFT_START, LATE_SHIFT_END)

    assert [e.event_id for e in repository.filter()] == ["EV-0006"]
    assert repository.machine_ids() == ["CNV-01", "PRS-01", "ROB-01"]


def test_read_fault_log_uses_only_events_in_the_shift(tmp_path: Path) -> None:
    repository = FaultLogRepository(write_log(tmp_path / "fault_log.csv", ROWS), LATE_SHIFT_START, LATE_SHIFT_END)

    result = ReadFaultLogTool(repository).run()

    assert [row[0] for row in result.data["events"]] == ["EV-0006"]
    assert result.data["counts"] == {"info": 0, "warning": 0, "critical": 1}
    assert result.data["critical_groups"] == [{"machine_id": "CNV-01", "error_code": "E202", "event_ids": ["EV-0006"]}]
    assert result.data["total"] == 1
    assert result.data["truncated"] is False


def test_truncation_counts_only_events_in_the_shift(tmp_path: Path) -> None:
    rows = [(f"EV-{n:04d}", "04:00", "04:05", "ROB-01", "E102", "warning", "x") for n in range(1, 46)]
    rows.append(("EV-0046", "07:00", "07:05", "ROB-01", "E102", "warning", "x"))
    repository = FaultLogRepository(write_log(tmp_path / "many.csv", rows), SHIFT_START, SHIFT_END)

    result = ReadFaultLogTool(repository).run()

    assert result.data["total"] == 1
    assert result.data["truncated"] is False


def test_late_shift_on_project_log_has_no_events_but_lists_every_machine() -> None:
    repository = FaultLogRepository(DATA_LOG, LATE_SHIFT_START, LATE_SHIFT_END)

    fault_log = ReadFaultLogTool(repository).run().data
    downtime = CalcDowntimeTool(repository).run().data["machines"]

    assert fault_log["total"] == 0
    assert fault_log["events"] == []
    assert fault_log["critical_groups"] == []
    assert [machine["machine_id"] for machine in downtime] == ["CNV-01", "PRS-01", "ROB-01", "ROB-02", "SCR-01"]
    assert all(machine["downtime_minutes"] == 0 for machine in downtime)
