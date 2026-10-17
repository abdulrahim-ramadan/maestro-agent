from datetime import datetime
from pathlib import Path

import pytest

from maestro.tools.factory import CalcDowntimeTool, ReadFaultLogTool
from maestro.tools.factory_data import (
    FaultLogError,
    FaultLogRepository,
    Severity,
    load_fault_events,
)

HEADER = "event_id,start_time,end_time,machine_id,error_code,severity,message"
SHIFT_START = datetime(2026, 10, 14, 6, 0)
SHIFT_END = datetime(2026, 10, 14, 14, 0)


def write_bytes(tmp_path: Path, content: bytes) -> Path:
    path = tmp_path / "export.csv"
    path.write_bytes(content)
    return path


def write_text(tmp_path: Path, *lines: str) -> Path:
    return write_bytes(tmp_path, ("\n".join(lines) + "\n").encode("utf-8"))


def test_utf8_file_with_byte_order_mark_loads(tmp_path: Path) -> None:
    content = f"{HEADER}\nEV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,critical,Störung am Übergabepunkt\n"
    path = write_bytes(tmp_path, content.encode("utf-8-sig"))

    events = load_fault_events(path)

    assert [event.event_id for event in events] == ["EV-0001"]
    assert events[0].message == "Störung am Übergabepunkt"


def test_cp1252_file_falls_back_from_utf8(tmp_path: Path) -> None:
    content = f"{HEADER}\nEV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,critical,Störung – Förderband\n"
    path = write_bytes(tmp_path, content.encode("cp1252"))

    events = load_fault_events(path)

    assert events[0].message == "Störung – Förderband"


def test_semicolon_delimiter_is_detected(tmp_path: Path) -> None:
    path = write_text(
        tmp_path,
        HEADER.replace(",", ";"),
        "EV-0001;2026-10-14 07:00;2026-10-14 07:30;CNV-01;E202;critical;Part jam, guide rail bent",
    )

    events = load_fault_events(path)

    assert events[0].machine_id == "CNV-01"
    assert events[0].message == "Part jam, guide rail bent"


@pytest.mark.parametrize(
    "start, end",
    [
        ("14.10.2026 06:10", "14.10.2026 06:40"),
        ("14.10.2026 06:10:00", "14.10.2026 06:40:00"),
        ("2026-10-14T06:10:00", "2026-10-14 06:40"),
    ],
)
def test_iso_and_german_dates_are_accepted(tmp_path: Path, start: str, end: str) -> None:
    path = write_text(tmp_path, HEADER, f"EV-0001,{start},{end},PRS-01,E301,critical,Pressure low")

    event = load_fault_events(path)[0]

    assert (event.start_time, event.end_time) == (datetime(2026, 10, 14, 6, 10), datetime(2026, 10, 14, 6, 40))


def test_severity_is_case_insensitive(tmp_path: Path) -> None:
    path = write_text(
        tmp_path,
        HEADER,
        "EV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,CRITICAL,Part jam",
        "EV-0002,2026-10-14 08:00,2026-10-14 08:05,CNV-01,E201, Warning ,Belt slip",
    )

    assert [event.severity for event in load_fault_events(path)] == [Severity.CRITICAL, Severity.WARNING]


def test_open_fault_lasts_until_shift_end_and_is_flagged(tmp_path: Path) -> None:
    path = write_text(
        tmp_path,
        HEADER,
        "EV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,critical,Part jam",
        "EV-0002,2026-10-14 13:00,,PRS-01,E301,critical,Pressure low",
    )
    repository = FaultLogRepository(path, SHIFT_START, SHIFT_END)

    fault_log = ReadFaultLogTool(repository).run().data
    downtime = {machine["machine_id"]: machine["downtime_minutes"] for machine in CalcDowntimeTool(repository).run().data["machines"]}

    open_column = fault_log["columns"].index("open")
    assert [row[open_column] for row in fault_log["events"]] == [False, True]
    assert fault_log["events"][1][2] == "2026-10-14 14:00"
    assert downtime == {"CNV-01": 30.0, "PRS-01": 60.0}


@pytest.mark.parametrize(
    "lines, expected_message",
    [
        (
            ["event_id,start_time,machine_id,error_code,severity,message", "EV-0001,2026-10-14 07:00,CNV-01,E202,critical,x"],
            "line 1: missing columns: end_time",
        ),
        (
            [HEADER, "EV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,critical,x", "EV-0002,yesterday,2026-10-14 08:00,CNV-01,E202,critical,x"],
            "line 3: invalid start_time 'yesterday'",
        ),
        (
            [HEADER, "EV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,fatal,x"],
            "line 2: unknown severity 'fatal'; valid values: info, warning, critical",
        ),
        (
            [HEADER, "EV-0001,2026-10-14 08:00,2026-10-14 07:30,CNV-01,E202,critical,x"],
            "line 2: end_time 2026-10-14 07:30 is before start_time 2026-10-14 08:00",
        ),
        (
            [
                HEADER,
                "EV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,critical,x",
                "EV-0001,2026-10-14 09:00,2026-10-14 09:30,CNV-01,E202,critical,x",
            ],
            "line 3: duplicate event_id 'EV-0001' (first seen on line 2)",
        ),
    ],
)
def test_invalid_rows_raise_fault_log_error_with_line_number(tmp_path: Path, lines: list[str], expected_message: str) -> None:
    path = write_text(tmp_path, *lines)

    with pytest.raises(FaultLogError) as error_info:
        load_fault_events(path)

    assert str(error_info.value) == f"{path.name} {expected_message}"
