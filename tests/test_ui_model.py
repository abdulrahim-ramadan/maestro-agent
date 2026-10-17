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
    ErrorMessage,
    LogSource,
    ShiftPreset,
    StepStatus,
    StepTracker,
    can_generate,
    describe_error,
    downtime_by_machine,
    log_source_label,
    preset_label,
    preview_log,
    report_file_name,
    shift_times,
)

DATA_LOG = Path(__file__).resolve().parent.parent / "data" / "fault_log.csv"
DE = ReportLanguage.GERMAN
EN = ReportLanguage.ENGLISH


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
    assert tracker.to_markdown(DE) == ""


def test_step_markdown_has_icon_tool_and_safe_arguments() -> None:
    trace = Trace()
    tracker = StepTracker()
    tool_call(trace, 3, "c1", "search_manuals", '{"queries": ["wire `feed` jam"]}')
    tool_result(trace, 3, "c1", "search_manuals", ok=True)
    for event in trace.events:
        tracker.on_event(event)

    assert tracker.to_markdown(EN) == "✅ step 3 **search_manuals** `{\"queries\":[\"wire 'feed' jam\"]}`"
    assert tracker.to_markdown(DE) == "✅ Schritt 3 **search_manuals** `{\"queries\":[\"wire 'feed' jam\"]}`"


def test_downtime_by_machine_matches_calc_downtime_on_sample_data() -> None:
    shift = ShiftWindow.for_log(DATA_LOG, time(6, 0), time(14, 0))

    assert downtime_by_machine(DATA_LOG, shift) == {
        "CNV-01": 92.0,
        "PRS-01": 66.0,
        "ROB-01": 106.0,
        "ROB-02": 30.0,
        "SCR-01": 17.0,
    }


@pytest.mark.parametrize(
    "lang, expected",
    [(DE, "schichtbericht_20261017_090507.md"), (EN, "shift_report_20261017_090507.md")],
)
def test_report_file_name_follows_language(lang: ReportLanguage, expected: str) -> None:
    assert report_file_name(lang, datetime(2026, 10, 17, 9, 5, 7)) == expected


@pytest.mark.parametrize(
    "error, german, english",
    [
        (ConfigError("LLM_API_KEY missing"), "Konfigurationsfehler: LLM_API_KEY missing", "Configuration error: LLM_API_KEY missing"),
        (
            FaultLogError("export.csv", 3, "invalid start_time 'x'"),
            "Fehler im Störungsprotokoll: export.csv line 3: invalid start_time 'x'",
            "Fault log error: export.csv line 3: invalid start_time 'x'",
        ),
        (ValueError("shift start and end must differ"), "Ungültige Eingabe: shift start and end must differ", "Invalid input: shift start and end must differ"),
        (RuntimeError("disk full"), "Unerwarteter Fehler (RuntimeError): disk full", "Unexpected error (RuntimeError): disk full"),
    ],
)
def test_describe_error_labels_each_failure(error: Exception, german: str, english: str) -> None:
    assert describe_error(error, DE) == ErrorMessage(german)
    assert describe_error(error, EN) == ErrorMessage(english)


def rate_limit_error(text: str) -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    return openai.RateLimitError(text, response=httpx.Response(429, request=request), body=None)


def test_rate_limit_gets_one_plain_sentence_and_technical_details() -> None:
    error = rate_limit_error("Rate limit reached on tokens per minute (TPM): Limit 8000, Used 4495")
    message = describe_error(error, EN)

    assert describe_error(error, DE).summary == "Das Limit des KI-Dienstes ist erreicht. Bitte eine Minute warten und erneut versuchen."
    assert message.summary == "The AI service limit was reached. Wait one minute and try again."
    assert message.details == "RateLimitError: Rate limit reached on tokens per minute (TPM): Limit 8000, Used 4495"


def test_quota_gets_one_plain_sentence_and_technical_details() -> None:
    message = describe_error(QuotaExhaustedError("8m50s"), EN)

    assert describe_error(QuotaExhaustedError("8m50s"), DE).summary == "Das Tageskontingent ist aufgebraucht. Bitte morgen erneut versuchen."
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

    assert describe_error(error, EN).summary == "API error (APIStatusError): Invalid key <redacted> or <redacted>"
    assert describe_error(error, DE).summary == "Fehler des KI-Dienstes (APIStatusError): Invalid key <redacted> or <redacted>"
    assert "gsk_" not in (describe_error(rate_limit_error("key gsk_AbCdEf0123456789xyz"), DE).details or "")


def test_wait_notices_appear_between_steps() -> None:
    trace = Trace()
    tracker = StepTracker()
    tool_call(trace, 1, "c1", "read_fault_log", "{}")
    tracker.on_event(trace.events[0])
    tracker.on_wait(11.6, "token pacing")

    assert tracker.to_markdown(EN) == "⏳ step 1 **read_fault_log** `{}`\n\n🕒 waiting 12 s for the rate limit (token pacing)"
    assert tracker.to_markdown(DE) == "⏳ Schritt 1 **read_fault_log** `{}`\n\n🕒 Warte 12 s wegen des Ratenlimits (Token-Taktung)"
    assert [row.tool for row in tracker.rows] == ["read_fault_log"]


@pytest.mark.parametrize(
    "preset, german, english, expected_times",
    [
        (ShiftPreset.EARLY, "Frühschicht 06:00–14:00", "Early shift (Frühschicht) 06:00–14:00", (time(6, 0), time(14, 0))),
        (ShiftPreset.LATE, "Spätschicht 14:00–22:00", "Late shift (Spätschicht) 14:00–22:00", (time(14, 0), time(22, 0))),
        (ShiftPreset.NIGHT, "Nachtschicht 22:00–06:00", "Night shift (Nachtschicht) 22:00–06:00", (time(22, 0), time(6, 0))),
        (ShiftPreset.CUSTOM, "Benutzerdefiniert", "Custom", (time(7, 30), time(15, 30))),
    ],
)
def test_shift_presets(preset: ShiftPreset, german: str, english: str, expected_times: tuple[time, time]) -> None:
    assert preset_label(preset, DE) == german
    assert preset_label(preset, EN) == english
    assert shift_times(preset, time(7, 30), time(15, 30)) == expected_times


@pytest.mark.parametrize(
    "source, german, english",
    [(LogSource.UPLOAD, "CSV hochladen", "Upload CSV"), (LogSource.SAMPLE, "Beispieldaten verwenden", "Use sample data")],
)
def test_log_source_labels(source: LogSource, german: str, english: str) -> None:
    assert log_source_label(source, DE) == german
    assert log_source_label(source, EN) == english


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


def test_preview_details_in_both_languages() -> None:
    preview = preview_log(DATA_LOG, time(6, 0), time(14, 0))

    assert preview.details(DE) == (
        "Maschinen: CNV-01, PRS-01, ROB-01, ROB-02, SCR-01 · erstes Ereignis 14.10.2026 05:40, "
        "letztes Ereignis 14.10.2026 13:36 · Schicht 14.10.2026 06:00 bis 14.10.2026 14:00"
    )
    assert preview.details(EN) == (
        "Machines: CNV-01, PRS-01, ROB-01, ROB-02, SCR-01 · first event 2026-10-14 05:40, "
        "last event 2026-10-14 13:36 · shift 2026-10-14 06:00 to 2026-10-14 14:00"
    )


@pytest.mark.parametrize(
    "start, end, confirmed, expected",
    [
        (time(6, 0), time(14, 0), False, True),
        (time(14, 0), time(22, 0), False, False),
        (time(14, 0), time(22, 0), True, True),
    ],
)
def test_empty_shift_needs_confirmation(start: time, end: time, confirmed: bool, expected: bool) -> None:
    preview = preview_log(DATA_LOG, start, end)

    assert can_generate(preview, confirmed) is expected


def test_no_preview_means_no_report() -> None:
    assert can_generate(None, empty_report_confirmed=True) is False
