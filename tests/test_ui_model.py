from datetime import datetime, time
from pathlib import Path

import httpx
import openai
import pytest

from maestro.config import ConfigError
from maestro.core.trace import EventKind, Trace
from maestro.llm.client import QuotaExhaustedError
from maestro.prompts import ReportLanguage
from maestro.tools.factory_data import FaultLogError, ShiftWindow
from maestro.ui_model import (
    StepStatus,
    StepTracker,
    describe_error,
    downtime_by_machine,
    report_file_name,
)

DATA_LOG = Path(__file__).resolve().parent.parent / "data" / "fault_log.csv"


def tool_call(trace: Trace, step: int, call_id: str, name: str, arguments: str) -> None:
    trace.add(step, EventKind.TOOL_CALL, {"id": call_id, "name": name, "arguments": arguments})


def tool_result(trace: Trace, step: int, call_id: str, name: str, ok: bool) -> None:
    trace.add(step, EventKind.TOOL_RESULT, {"id": call_id, "name": name, "ok": ok, "content": "{}"})


def test_tracker_shows_running_then_final_status() -> None:
    trace = Trace()
    tracker = StepTracker()
    tool_call(trace, 1, "c1", "read_fault_log", "{}")
    tool_call(trace, 2, "c2", "lookup_error_code", '{"codes": ["E101", "E999"]}')
    for event in trace.events:
        tracker.on_event(event)

    assert [row.status for row in tracker.rows] == [StepStatus.RUNNING, StepStatus.RUNNING]

    tool_result(trace, 1, "c1", "read_fault_log", ok=True)
    tool_result(trace, 2, "c2", "lookup_error_code", ok=False)
    for event in trace.events[2:]:
        tracker.on_event(event)

    assert [(row.step, row.tool, row.status) for row in tracker.rows] == [
        (1, "read_fault_log", StepStatus.OK),
        (2, "lookup_error_code", StepStatus.FAILED),
    ]
    assert tracker.rows[1].arguments == '{"codes":["E101","E999"]}'


def test_tracker_ignores_other_events_and_unknown_results() -> None:
    trace = Trace()
    tracker = StepTracker()
    trace.add(1, EventKind.ASSISTANT, {"content": "", "tool_calls": 1})
    tool_result(trace, 1, "unknown", "read_fault_log", ok=True)
    for event in trace.events:
        tracker.on_event(event)

    assert tracker.rows == []
    assert tracker.to_markdown() == ""


def test_step_markdown_has_icon_tool_and_safe_arguments() -> None:
    trace = Trace()
    tracker = StepTracker()
    tool_call(trace, 3, "c1", "search_manuals", '{"queries": ["wire `feed` jam"]}')
    tool_result(trace, 3, "c1", "search_manuals", ok=True)
    for event in trace.events:
        tracker.on_event(event)

    assert tracker.to_markdown() == "✅ step 3 **search_manuals** `{\"queries\":[\"wire 'feed' jam\"]}`"


def test_downtime_by_machine_matches_calc_downtime_on_sample_data() -> None:
    shift = ShiftWindow.for_log(DATA_LOG, time(6, 0), time(14, 0))

    assert downtime_by_machine(DATA_LOG, shift) == {
        "CNV-01": 92.0,
        "PRS-01": 66.0,
        "ROB-01": 106.0,
        "ROB-02": 30.0,
        "SCR-01": 17.0,
    }


def test_report_file_name() -> None:
    assert report_file_name(ReportLanguage.GERMAN, datetime(2026, 10, 17, 9, 5, 7)) == "shift_report_20261017_090507_de.md"


@pytest.mark.parametrize(
    "error, expected",
    [
        (ConfigError("missing required environment variables: LLM_API_KEY"), "Configuration error: missing required"),
        (QuotaExhaustedError("8m50s"), "Quota exhausted: the provider token quota is exhausted"),
        (FaultLogError("export.csv", 3, "invalid start_time 'x'"), "Fault log error: export.csv line 3: invalid start_time 'x'"),
        (ValueError("shift start and end must differ"), "Invalid input: shift start and end must differ"),
        (RuntimeError("disk full"), "Unexpected error (RuntimeError): disk full"),
    ],
)
def test_describe_error_labels_each_failure(error: Exception, expected: str) -> None:
    assert describe_error(error).startswith(expected)


def test_describe_error_redacts_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "custom-provider-token-42")
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    error = openai.APIStatusError(
        "Invalid key gsk_AbCdEf0123456789xyz or custom-provider-token-42",
        response=httpx.Response(401, request=request),
        body=None,
    )

    message = describe_error(error)

    assert message == "API error (APIStatusError): Invalid key <redacted> or <redacted>"
