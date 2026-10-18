from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from maestro import app
from maestro.config import ConfigError, Settings
from maestro.core.agent import AgentResult, StopReason
from maestro.core.trace import EventKind, Trace
from maestro.ui_model import LogSource, ShiftPreset

UI_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "maestro" / "ui.py"
REPORT = "# Shift report\n\n## Summary\nAll machines checked."
TIMEOUT_SECONDS = 30


class FakeAgent:
    error: Exception | None = None
    runs: int = 0

    def __init__(self, on_token: Callable[[str], None], on_event: Callable[[Any], None], on_wait: Any) -> None:
        self._on_token = on_token
        self._on_event = on_event
        self._on_wait = on_wait

    def run(self, task: str) -> AgentResult:
        FakeAgent.runs += 1
        if FakeAgent.error is not None:
            raise FakeAgent.error
        trace = Trace()
        self._on_wait(11.6, "token pacing")
        self._on_event(trace.add(1, EventKind.TOOL_CALL, {"id": "c1", "name": "calc_downtime", "arguments": "{}"}))
        self._on_event(trace.add(1, EventKind.TOOL_RESULT, {"id": "c1", "name": "calc_downtime", "ok": True, "content": "{}"}))
        for token in REPORT.split(" "):
            self._on_token(token + " ")
        return AgentResult(REPORT, 2, StopReason.FINAL_ANSWER, trace.save())


def fake_build_agent(
    settings: Settings, log_path: Path, shift: Any, on_token: Any = None, on_event: Any = None, on_wait: Any = None
) -> FakeAgent:
    return FakeAgent(on_token, on_event, on_wait)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(FakeAgent, "error", None)
    monkeypatch.setattr(FakeAgent, "runs", 0)
    monkeypatch.setattr(app, "build_agent", fake_build_agent)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(api_key="sk-test", model="m", base_url=None)))


def open_page() -> AppTest:
    return AppTest.from_file(str(UI_SCRIPT), default_timeout=TIMEOUT_SECONDS).run()


def choose_sample_data(page: AppTest | None = None) -> AppTest:
    page = page or open_page()
    page.radio(key="log_source").set_value(LogSource.SAMPLE).run()
    return page


def switch_language(page: AppTest, choice: str) -> AppTest:
    page.segmented_control(key="ui_language").set_value(choice).run()
    return page


def generate(page: AppTest) -> AppTest:
    page.button(key="generate_report").click().run()
    return page


def markdown_text(page: AppTest) -> str:
    return "\n".join(markdown.value for markdown in page.markdown)


def metrics(page: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in page.metric}


def test_page_starts_in_german_with_disabled_button() -> None:
    page = open_page()

    assert not page.exception
    assert page.segmented_control(key="ui_language").value == "Deutsch"
    assert page.segmented_control(key="ui_language").label == "Sprache / Language"
    assert page.title[0].value == "Maestro Schichtbericht"
    assert page.radio(key="log_source").label == "Störungsprotokoll"
    assert page.radio(key="log_source").options == ["CSV hochladen", "Beispieldaten verwenden"]
    assert page.button(key="generate_report").label == "Bericht erstellen"
    assert page.button(key="generate_report").disabled
    assert page.sidebar.caption[0].value == "Im kostenlosen Tarif sind etwa 5 Berichte pro Tag möglich."
    assert page.info[0].value.startswith("Bitte wählen Sie in der Seitenleiste ein Störungsprotokoll")


def test_no_separate_report_language_widget() -> None:
    page = open_page()

    assert [radio.key for radio in page.radio] == ["log_source"]


def test_switching_language_translates_keeps_selection_and_starts_no_report() -> None:
    page = choose_sample_data()
    switch_language(page, "English")

    assert not page.exception
    assert FakeAgent.runs == 0
    assert page.radio(key="log_source").value is LogSource.SAMPLE
    assert page.title[0].value == "Maestro shift report"
    assert page.button(key="generate_report").label == "Generate report"
    assert page.segmented_control(key="shift_preset").options[0] == "Early shift (Frühschicht) 06:00–14:00"
    assert metrics(page) == {"Events": "31", "Machines": "5", "In this shift": "31"}


def test_german_run_shows_german_steps_report_chart_and_download() -> None:
    page = generate(choose_sample_data())

    assert not page.exception
    assert not page.error
    assert FakeAgent.runs == 1
    text = markdown_text(page)
    assert "All machines checked." in text
    assert "Schritt 1 **calc_downtime**" in text
    assert "Warte 12 s wegen des Ratenlimits (Token-Limit pro Minute)" in text
    assert page.get("arrow_vega_lite_chart") or page.get("vega_lite_chart")
    assert page.get("download_button")


def test_finished_run_rerenders_in_the_new_language_without_a_new_run() -> None:
    page = generate(choose_sample_data())
    switch_language(page, "English")

    assert FakeAgent.runs == 1
    text = markdown_text(page)
    assert "step 1 **calc_downtime**" in text
    assert "waiting 12 s for the rate limit (token pacing)" in text
    assert "All machines checked." in text
    assert "Agent steps" in [expander.label for expander in page.expander]


def test_missing_config_shows_german_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_config_error(cls: type) -> Settings:
        raise ConfigError("missing required environment variables: LLM_API_KEY")

    monkeypatch.setattr(Settings, "from_env", classmethod(raise_config_error))

    page = generate(choose_sample_data())

    assert not page.exception
    assert page.error[0].value == "Konfigurationsfehler: missing required environment variables: LLM_API_KEY"


def test_preview_shows_german_metrics() -> None:
    page = choose_sample_data()

    assert not page.exception
    assert metrics(page) == {"Ereignisse": "31", "Maschinen": "5", "In dieser Schicht": "31"}
    assert page.caption[0].value.startswith("Maschinen: CNV-01, PRS-01, ROB-01, ROB-02, SCR-01 · erstes Ereignis 14.10.2026 05:40")
    assert not page.button(key="generate_report").disabled
    assert not page.warning


def test_empty_shift_warns_and_needs_confirmation() -> None:
    page = choose_sample_data()
    page.segmented_control(key="shift_preset").set_value(ShiftPreset.LATE).run()

    assert metrics(page)["In dieser Schicht"] == "0"
    assert page.warning[0].value.startswith("Keine Ereignisse in dieser Schicht.")
    assert page.button(key="generate_report").disabled

    page.checkbox(key="confirm_empty_report").check().run()

    assert not page.button(key="generate_report").disabled
    assert FakeAgent.runs == 0


def test_empty_shift_warning_in_english() -> None:
    page = switch_language(choose_sample_data(), "English")
    page.segmented_control(key="shift_preset").set_value(ShiftPreset.LATE).run()

    assert page.warning[0].value.startswith("No events in this shift.")
    assert page.checkbox(key="confirm_empty_report").label == "I want to create a report without events anyway"


def test_custom_preset_shows_german_time_inputs() -> None:
    page = choose_sample_data()
    page.segmented_control(key="shift_preset").set_value(ShiftPreset.CUSTOM).run()

    assert [time_input.label for time_input in page.sidebar.time_input] == ["Schichtbeginn", "Schichtende"]


def test_rate_limit_error_shows_german_sentence_and_collapsed_details() -> None:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    FakeAgent.error = openai.RateLimitError(
        "Rate limit reached on tokens per minute (TPM)", response=httpx.Response(429, request=request), body=None
    )

    page = generate(choose_sample_data())

    assert not page.exception
    assert page.error[0].value == "Das Limit des KI-Dienstes ist erreicht. Bitte eine Minute warten und erneut versuchen."
    assert "Technische Details" in [expander.label for expander in page.expander]
    assert any("tokens per minute" in code.value for code in page.code)
