import re
from datetime import time
from pathlib import Path

import pytest

from maestro.tools.factory import CalcDowntimeTool, ReadFaultLogTool
from maestro.tools.factory_data import FaultLogRepository, ShiftWindow

PROJECT_DIR = Path(__file__).resolve().parent.parent
SAMPLE_REPORT = PROJECT_DIR / "examples" / "sample_report_en.md"
FAULT_LOG = PROJECT_DIR / "data" / "fault_log.csv"
DOWNTIME_ROW = re.compile(r"^\|\s*([A-Z]{3}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|", re.MULTILINE)
EVENT_ID = re.compile(r"EV-\d{4}")
NON_ASCII_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-"})


def section(report: str, heading: str) -> str:
    start = report.index(f"## {heading}")
    end = report.find("\n## ", start + 1)
    return report[start : end if end != -1 else len(report)]


@pytest.fixture(scope="module")
def report() -> str:
    return SAMPLE_REPORT.read_text(encoding="utf-8").translate(NON_ASCII_HYPHENS)


@pytest.fixture(scope="module")
def repository() -> FaultLogRepository:
    shift = ShiftWindow.for_log(FAULT_LOG, time(6, 0), time(14, 0))
    return FaultLogRepository(FAULT_LOG, shift.start, shift.end)


def test_downtime_table_matches_calc_downtime(report: str, repository: FaultLogRepository) -> None:
    expected = {
        machine["machine_id"]: (machine["downtime_minutes"], machine["availability_percent"])
        for machine in CalcDowntimeTool(repository).run().data["machines"]
    }

    table = section(report, "Downtime per machine")
    reported = {machine: (float(minutes), float(percent)) for machine, minutes, percent in DOWNTIME_ROW.findall(table)}

    assert reported == expected


def test_critical_events_match_read_fault_log(report: str, repository: FaultLogRepository) -> None:
    fault_log = ReadFaultLogTool(repository).run().data
    expected = {event_id for group in fault_log["critical_groups"] for event_id in group["event_ids"]}

    reported = set(EVENT_ID.findall(section(report, "Critical issues and recommended actions")))

    assert reported == expected


def test_every_event_id_in_report_exists_in_the_log(report: str, repository: FaultLogRepository) -> None:
    known_ids = {event.event_id for event in repository.filter()}

    assert set(EVENT_ID.findall(report)) <= known_ids
