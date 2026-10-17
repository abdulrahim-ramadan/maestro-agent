from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

from maestro import cli
from maestro.config import ConfigError, Settings
from maestro.core.agent import AgentResult, StopReason
from maestro.core.trace import EventKind, Trace

REPORT = "# Shift report\n\n## Summary\nAll good."


class FakeAgent:
    def __init__(
        self,
        on_token: Callable[[str], None],
        on_event: Callable[[Any], None],
        stop_reason: StopReason = StopReason.FINAL_ANSWER,
        error: Exception | None = None,
    ) -> None:
        self._on_token = on_token
        self._on_event = on_event
        self._stop_reason = stop_reason
        self._error = error
        self.tasks: list[str] = []

    def run(self, task: str) -> AgentResult:
        self.tasks.append(task)
        if self._error is not None:
            raise self._error
        trace = Trace()
        self._on_event(trace.add(1, EventKind.TOOL_CALL, {"id": "c1", "name": "lookup_error_code", "arguments": '{"codes": ["E101"]}'}))
        self._on_event(trace.add(1, EventKind.TOOL_RESULT, {"id": "c1", "name": "lookup_error_code", "ok": True, "content": "{}"}))
        for token in ["# Shift report\n\n", "## Summary\n", "All good."]:
            self._on_token(token)
        return AgentResult(REPORT, 2, self._stop_reason, trace.save())


class FakeAgentFactory:
    def __init__(self, **agent_options: Any) -> None:
        self._agent_options = agent_options
        self.agents: list[FakeAgent] = []
        self.log_paths: list[str] = []

    def __call__(self, settings: Settings, log_path: str, on_token: Any = None, on_event: Any = None) -> FakeAgent:
        self.log_paths.append(log_path)
        agent = FakeAgent(on_token, on_event, **self._agent_options)
        self.agents.append(agent)
        return agent


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(api_key="sk-test", model="m", base_url=None)))


def test_report_saves_markdown_and_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeAgentFactory()

    exit_code = cli.main(["report", "--log", "my_log.csv", "--lang", "de", "--out", "out"], agent_factory=factory)

    assert exit_code == 0
    assert factory.log_paths == ["my_log.csv"]
    assert factory.agents[0].tasks[0].endswith("Report language: German.")
    reports = list((tmp_path / "out").glob("shift_report_*_de.md"))
    assert len(reports) == 1
    assert reports[0].read_text(encoding="utf-8") == REPORT + "\n"
    output = capsys.readouterr().out
    assert "✓ step 1  lookup_error_code" in output
    assert '{"codes":["E101"]}' in output
    assert "All good." in output
    assert "Run summary" in output


def test_run_without_final_answer_exits_with_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeAgentFactory(stop_reason=StopReason.MAX_STEPS)

    exit_code = cli.main(["report"], agent_factory=factory)

    assert exit_code == 1
    assert not (tmp_path / "reports").exists()
    assert "Run stopped without a report" in capsys.readouterr().out


def test_config_error_prints_message_and_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def raise_config_error(cls: type) -> Settings:
        raise ConfigError("missing required environment variables: LLM_API_KEY")

    monkeypatch.setattr(Settings, "from_env", classmethod(raise_config_error))

    exit_code = cli.main(["report"], agent_factory=FakeAgentFactory())

    assert exit_code == 1
    assert "Configuration error: missing required environment variables: LLM_API_KEY" in capsys.readouterr().out


def test_api_error_prints_message_without_key(capsys: pytest.CaptureFixture[str]) -> None:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    error = openai.APIStatusError(
        "Incorrect API key provided: sk-abc123secret",
        response=httpx.Response(401, request=request),
        body=None,
    )

    exit_code = cli.main(["report"], agent_factory=FakeAgentFactory(error=error))

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "API error (APIStatusError)" in output
    assert "sk-abc123secret" not in output
    assert "<redacted>" in output


def test_short_arguments_are_truncated() -> None:
    text = cli._short_arguments('{"queries": ["' + "x" * 200 + '"]}')

    assert len(text) == cli.MAX_ARGUMENT_CHARS
    assert text.endswith("...")
