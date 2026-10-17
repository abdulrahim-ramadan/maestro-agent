from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from maestro import app
from maestro.config import ConfigError, Settings
from maestro.core.agent import AgentResult, StopReason
from maestro.core.trace import EventKind, Trace

UI_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "maestro" / "ui.py"
REPORT = "# Shift report\n\n## Summary\nAll machines checked."
TIMEOUT_SECONDS = 30


class FakeAgent:
    def __init__(self, on_token: Callable[[str], None], on_event: Callable[[Any], None]) -> None:
        self._on_token = on_token
        self._on_event = on_event

    def run(self, task: str) -> AgentResult:
        trace = Trace()
        self._on_event(trace.add(1, EventKind.TOOL_CALL, {"id": "c1", "name": "calc_downtime", "arguments": "{}"}))
        self._on_event(trace.add(1, EventKind.TOOL_RESULT, {"id": "c1", "name": "calc_downtime", "ok": True, "content": "{}"}))
        for token in REPORT.split(" "):
            self._on_token(token + " ")
        return AgentResult(REPORT, 2, StopReason.FINAL_ANSWER, trace.save())


def fake_build_agent(settings: Settings, log_path: Path, shift: Any, on_token: Any = None, on_event: Any = None) -> FakeAgent:
    return FakeAgent(on_token, on_event)


@pytest.fixture(autouse=True)
def isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
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
    assert "35k tokens" in page.sidebar.caption[0].value


def test_sample_data_run_shows_report_chart_and_download() -> None:
    page = generate_with_sample_data()

    assert not page.exception
    assert not page.error
    assert any("All machines checked." in markdown.value for markdown in page.markdown)
    assert any("calc_downtime" in markdown.value for markdown in page.markdown)
    assert page.get("arrow_vega_lite_chart") or page.get("vega_lite_chart")
    assert page.get("download_button")


def test_missing_config_shows_red_message_instead_of_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_config_error(cls: type) -> Settings:
        raise ConfigError("missing required environment variables: LLM_API_KEY")

    monkeypatch.setattr(Settings, "from_env", classmethod(raise_config_error))

    page = generate_with_sample_data()

    assert not page.exception
    assert page.error[0].value == "Configuration error: missing required environment variables: LLM_API_KEY"
