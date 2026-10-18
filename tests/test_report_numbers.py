import re
from datetime import time
from pathlib import Path

import pytest

from maestro.prompts import REPORT_LAYOUTS, ReportLanguage
from maestro.report_format import ReportFormatter
from maestro.tools.factory import CalcDowntimeTool, ReadFaultLogTool
from maestro.tools.factory_data import FaultLogRepository, ShiftWindow

PROJECT_DIR = Path(__file__).resolve().parent.parent
SAMPLE_REPORT = PROJECT_DIR / "examples" / "sample_report_en.md"
FAULT_LOG = PROJECT_DIR / "data" / "fault_log.csv"
NUMBER = r"\d+(?:[.,]\d+)?"
DOWNTIME_ROW = re.compile(rf"^\|\s*([A-Z]{{3}}-\d{{2}})\s*\|\s*({NUMBER})\s*\|\s*({NUMBER})\s*\|", re.MULTILINE)
EVENT_ID = re.compile(r"EV-\d{4}")
NON_ASCII_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-"})


def parse_number(text: str) -> float:
    return float(text.replace(",", "."))


def section(report: str, part: str) -> str:
    headings = [f"## {getattr(layout, part)}" for layout in REPORT_LAYOUTS.values()]
    start = min(report.index(heading) for heading in headings if heading in report)
    end = report.find("\n## ", start + 1)
    return report[start : end if end != -1 else len(report)]


def reported_downtime(report: str) -> dict[str, tuple[float, float]]:
    rows = DOWNTIME_ROW.findall(section(report, "downtime"))
    return {machine: (parse_number(minutes), parse_number(percent)) for machine, minutes, percent in rows}


def expected_downtime(repository: FaultLogRepository) -> dict[str, tuple[float, float]]:
    return {
        machine["machine_id"]: (machine["downtime_minutes"], machine["availability_percent"])
        for machine in CalcDowntimeTool(repository).run().data["machines"]
    }


def expected_critical_ids(repository: FaultLogRepository) -> set[str]:
    fault_log = ReadFaultLogTool(repository).run().data
    return {event_id for group in fault_log["critical_groups"] for event_id in group["event_ids"]}


@pytest.fixture(scope="module")
def report() -> str:
    return SAMPLE_REPORT.read_text(encoding="utf-8").translate(NON_ASCII_HYPHENS)


@pytest.fixture(scope="module")
def repository() -> FaultLogRepository:
    shift = ShiftWindow.for_log(FAULT_LOG, time(6, 0), time(14, 0))
    return FaultLogRepository(FAULT_LOG, shift.start, shift.end)


def german_report(repository: FaultLogRepository, replace: tuple[str, str] | None = None) -> str:
    formatter = ReportFormatter(ReportLanguage.GERMAN)
    downtime = CalcDowntimeTool(repository, formatter).run().data
    layout = REPORT_LAYOUTS[ReportLanguage.GERMAN]
    rows = "\n".join(
        f"| {machine['machine_id']} | {machine['downtime_text']} | {machine['availability_text']} |" for machine in downtime["machines"]
    )
    report = (
        f"# Schichtbericht 14.10.2026 06:00–14:00\n\n## {layout.summary}\n"
        f"Der Stillstand betrug insgesamt {downtime['total_downtime_text']} Minuten.\n\n"
        f"## {layout.downtime}\n| {' | '.join(layout.columns)} |\n|---|---|---|\n{rows}\n\n"
        f"## {layout.critical}\n{', '.join(sorted(expected_critical_ids(repository)))}\n\n"
        f"## {layout.open_points}\n- Keine\n"
    )
    return report.replace(*replace) if replace else report


@pytest.mark.parametrize("text, value", [("92", 92.0), ("92.0", 92.0), ("80,8", 80.8), ("80.8", 80.8)])
def test_parse_number_accepts_both_formats(text: str, value: float) -> None:
    assert parse_number(text) == value


def test_downtime_table_matches_calc_downtime(report: str, repository: FaultLogRepository) -> None:
    assert reported_downtime(report) == expected_downtime(repository)


def test_critical_events_match_read_fault_log(report: str, repository: FaultLogRepository) -> None:
    assert set(EVENT_ID.findall(section(report, "critical"))) == expected_critical_ids(repository)


def test_every_event_id_in_report_exists_in_the_log(report: str, repository: FaultLogRepository) -> None:
    known_ids = {event.event_id for event in repository.filter()}

    assert set(EVENT_ID.findall(report)) <= known_ids


def test_german_report_numbers_are_checked_the_same_way(repository: FaultLogRepository) -> None:
    report = german_report(repository)

    assert "| PRS-01 | 66 | 86,2 |" in report
    assert reported_downtime(report) == expected_downtime(repository)
    assert set(EVENT_ID.findall(section(report, "critical"))) == expected_critical_ids(repository)
    assert "insgesamt 311 Minuten" in section(report, "summary")


def test_a_wrong_german_number_is_caught(repository: FaultLogRepository) -> None:
    report = german_report(repository, replace=("| 86,2 |", "| 86,3 |"))

    assert reported_downtime(report) != expected_downtime(repository)
