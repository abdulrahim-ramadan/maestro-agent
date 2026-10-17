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
    ShiftPreset,
    StepStatus,
    StepTracker,
    describe_error,
    downtime_by_machine,
    preset_label,
    preview_log,
    report_file_name,
    shift_times,
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
        (FaultLogError("export.csv", 3, "invalid start_time 'x'"), "Fault log error: export.csv line 3: invalid start_time 'x'"),
        (ValueError("shift start and end must differ"), "Invalid input: shift start and end must differ"),
        (RuntimeError("disk full"), "Unexpected error (RuntimeError): disk full"),
    ],
)
def test_describe_error_labels_each_failure(error: Exception, expected: str) -> None:
    message = describe_error(error)

    assert message.summary.startswith(expected)
    assert message.details is None


def rate_limit_error(text: str) -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    return openai.RateLimitError(text, response=httpx.Response(429, request=request), body=None)


def test_rate_limit_gets_one_plain_sentence_and_technical_details() -> None:
    message = describe_error(rate_limit_error("Rate limit reached on tokens per minute (TPM): Limit 8000, Used 4495"))

    assert message.summary == "The AI service limit was reached. Wait one minute and try again."
    assert message.details == "RateLimitError: Rate limit reached on tokens per minute (TPM): Limit 8000, Used 4495"


def test_quota_gets_one_plain_sentence_and_technical_details() -> None:
    message = describe_error(QuotaExhaustedError("8m50s"))

    assert message.summary == "Today's quota is used up. Try again tomorrow."
    assert message.details is not None and "8m50s" in message.details


def test_describe_error_redacts_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "custom-provider-token-42")
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    error = openai.APIStatusError(
        "Invalid key gsk_AbCdEf0123456789xyz or custom-provider-token-42",
        response=httpx.Response(401, request=request),
        body=None,
    )

    assert describe_error(error).summary == "API error (APIStatusError): Invalid key <redacted> or <redacted>"
    assert "gsk_" not in (describe_error(rate_limit_error("key gsk_AbCdEf0123456789xyz")).details or "")


def test_wait_notices_appear_between_steps() -> None:
    trace = Trace()
    tracker = StepTracker()
    tool_call(trace, 1, "c1", "read_fault_log", "{}")
    tracker.on_event(trace.events[0])
    tracker.on_wait(11.6, "token pacing")

    assert tracker.to_markdown() == (
        "⏳ step 1 **read_fault_log** `{}`\n\n🕒 waiting 12 s for the rate limit (token pacing)"
    )
    assert [row.tool for row in tracker.rows] == ["read_fault_log"]


@pytest.mark.parametrize(
    "preset, expected_label, expected_times",
    [
        (ShiftPreset.EARLY, "Frühschicht 06:00–14:00", (time(6, 0), time(14, 0))),
        (ShiftPreset.LATE, "Spätschicht 14:00–22:00", (time(14, 0), time(22, 0))),
        (ShiftPreset.NIGHT, "Nachtschicht 22:00–06:00", (time(22, 0), time(6, 0))),
        (ShiftPreset.CUSTOM, "Custom", (time(7, 30), time(15, 30))),
    ],
)
def test_shift_presets(preset: ShiftPreset, expected_label: str, expected_times: tuple[time, time]) -> None:
    assert preset_label(preset) == expected_label
    assert shift_times(preset, time(7, 30), time(15, 30)) == expected_times


@pytest.mark.parametrize(
    "start, end, in_shift, shift_start",
    [
        (time(6, 0), time(14, 0), 31, datetime(2026, 10, 14, 6, 0)),
        (time(14, 0), time(22, 0), 0, datetime(2026, 10, 14, 14, 0)),
        (time(22, 0), time(6, 0), 1, datetime(2026, 10, 13, 22, 0)),
    ],
)
def test_preview_of_sample_log(start: time, end: time, in_shift: int, shift_start: datetime) -> None:
    preview = preview_log(DATA_LOG, start, end)

    assert preview.event_count == 31
    assert preview.machine_ids == ["CNV-01", "PRS-01", "ROB-01", "ROB-02", "SCR-01"]
    assert preview.first_event == datetime(2026, 10, 14, 5, 40)
    assert preview.last_event == datetime(2026, 10, 14, 13, 36)
    assert preview.events_in_shift == in_shift
    assert preview.shift.start == shift_start


def test_preview_raises_fault_log_error_for_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.csv"
    path.write_text("event_id,start_time\nEV-1,2026-10-14 07:00\n", encoding="utf-8")

    with pytest.raises(FaultLogError, match="missing columns"):
        preview_log(path, time(6, 0), time(14, 0))
