from datetime import datetime

import pytest

from maestro.prompts import ReportLanguage
from maestro.report_format import ReportFormatter

GERMAN = ReportFormatter(ReportLanguage.GERMAN)
ENGLISH = ReportFormatter(ReportLanguage.ENGLISH)


@pytest.mark.parametrize(
    "value, german, english",
    [(92.0, "92", "92.0"), (80.8, "80,8", "80.8"), (0.0, "0", "0.0"), (100.0, "100", "100.0"), (311.0, "311", "311.0"), (2.45, "2,5", "2.5")],
)
def test_numbers(value: float, german: str, english: str) -> None:
    assert GERMAN.number(value) == german
    assert ENGLISH.number(value) == english


def test_timestamps_and_dates() -> None:
    moment = datetime(2026, 10, 14, 5, 40)

    assert GERMAN.timestamp(moment) == "14.10.2026 05:40"
    assert ENGLISH.timestamp(moment) == "2026-10-14 05:40"
    assert GERMAN.date(moment) == "14.10.2026"
    assert ENGLISH.date(moment) == "2026-10-14"


def test_default_formatter_is_english() -> None:
    assert ReportFormatter().number(80.8) == "80.8"
