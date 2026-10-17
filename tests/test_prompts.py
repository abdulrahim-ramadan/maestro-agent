from datetime import datetime

import pytest

from maestro.prompts import SYSTEM_PROMPT, ReportLanguage, report_task


@pytest.mark.parametrize(
    "section",
    ["## Summary", "## Downtime per machine", "## Critical issues and recommended actions", "## Open points for the next shift"],
)
def test_system_prompt_defines_report_sections(section: str) -> None:
    assert section in SYSTEM_PROMPT


@pytest.mark.parametrize("phrase", ["ONCE with ALL distinct error codes", "Never invent numbers", "truncated", "cite"])
def test_system_prompt_states_workflow_and_rules(phrase: str) -> None:
    assert phrase in SYSTEM_PROMPT


@pytest.mark.parametrize("language, name", [(ReportLanguage.ENGLISH, "English"), (ReportLanguage.GERMAN, "German")])
def test_report_task_names_shift_and_language(language: ReportLanguage, name: str) -> None:
    task = report_task(language, datetime(2026, 10, 14, 6, 0), datetime(2026, 10, 14, 14, 0))

    assert "2026-10-14 from 06:00 to 14:00" in task
    assert task.endswith(f"Report language: {name}.")
