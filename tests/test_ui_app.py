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
from maestro.ui_model import ShiftPreset

UI_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "maestro" / "ui.py"
REPORT = "# Shift report\n\n## Summary\nAll machines checked."
TIMEOUT_SECONDS = 30


class FakeAgent:
    error: Exception | None = None

    def __init__(self, on_token: Callable[[str], None], on_event: Callable[[Any], None], on_wait: Any) -> None:
        self._on_token = on_token
        self._on_event = on_event
        self._on_wait = on_wait

    def run(self, task: str) -> AgentResult:
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
    monkeypatch.setattr(app, "build_agent", fake_build_agent)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(api_key="sk-test", model="m", base_url=None)))


def generate_with_sample_data() -> AppTest:
    page = AppTest.from_file(str(UI_SCRIPT), default_timeout=TIMEOUT_SECONDS).run()
    page.sidebar.radio[0].set_value("Use sample data").run()
    page.sidebar.button[0].click().run()
    return page


def test_page_renders_with_disabled_button_until_a_log_is_chosen() -> None:
    page = AppTest.from_file(str(UI_SCRIPT), default_timeout=TIMEOUT_SECONDS).run()

    assert not page.exception
    assert page.sidebar.button[0].label == "Generate report"
    assert page.sidebar.button[0].disabled
    assert page.sidebar.caption[0].value == "About 5 reports per day are possible on the free plan."


def test_sample_data_run_shows_report_chart_and_download() -> None:
    page = generate_with_sample_data()

    assert not page.exception
    assert not page.error
    assert any("All machines checked." in markdown.value for markdown in page.markdown)
    assert any("calc_downtime" in markdown.value for markdown in page.markdown)
    assert any("waiting 12 s for the rate limit (token pacing)" in markdown.value for markdown in page.markdown)
    assert page.get("arrow_vega_lite_chart") or page.get("vega_lite_chart")
    assert page.get("download_button")


def test_missing_config_shows_red_message_instead_of_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_config_error(cls: type) -> Settings:
        raise ConfigError("missing required environment variables: LLM_API_KEY")

    monkeypatch.setattr(Settings, "from_env", classmethod(raise_config_error))

    page = generate_with_sample_data()

    assert not page.exception
    assert page.error[0].value == "Configuration error: missing required environment variables: LLM_API_KEY"


def choose_sample_data() -> AppTest:
    page = AppTest.from_file(str(UI_SCRIPT), default_timeout=TIMEOUT_SECONDS).run()
    page.sidebar.radio[0].set_value("Use sample data").run()
    return page


def test_preview_shows_events_machines_and_events_in_shift() -> None:
    page = choose_sample_data()

    assert not page.exception
    assert {metric.label: metric.value for metric in page.metric} == {"Events": "31", "Machines": "5", "In this shift": "31"}
    assert not page.sidebar.button[0].disabled


def test_late_shift_preset_updates_preview_without_time_inputs() -> None:
    page = choose_sample_data()
    page.sidebar.segmented_control[0].set_value(ShiftPreset.LATE).run()

    assert {metric.label: metric.value for metric in page.metric}["In this shift"] == "0"
    assert len(page.sidebar.time_input) == 0


def test_custom_preset_shows_time_inputs() -> None:
    page = choose_sample_data()
    page.sidebar.segmented_control[0].set_value(ShiftPreset.CUSTOM).run()

    assert [time_input.label for time_input in page.sidebar.time_input] == ["Shift start", "Shift end"]


def test_rate_limit_error_shows_plain_sentence_and_collapsed_details() -> None:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    FakeAgent.error = openai.RateLimitError(
        "Rate limit reached on tokens per minute (TPM)", response=httpx.Response(429, request=request), body=None
    )

    page = generate_with_sample_data()

    assert not page.exception
    assert page.error[0].value == "The AI service limit was reached. Wait one minute and try again."
    assert "Technical details" in [expander.label for expander in page.expander]
    assert any("tokens per minute" in code.value for code in page.code)
