from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from maestro import app, cli, display
from maestro.config import ConfigError, Settings
from maestro.core.agent import AgentResult, StopReason
from maestro.core.trace import EventKind, Trace
from maestro.llm.client import QuotaExhaustedError
from maestro.tools.factory_data import ShiftWindow

LOG = (
    "event_id,start_time,end_time,machine_id,error_code,severity,message\n"
    "EV-0001,2026-10-14 22:30:00,2026-10-14 23:00:00,CNV-01,E202,critical,Part jam\n"
    "EV-0002,2026-10-15 01:00:00,2026-10-15 01:20:00,CNV-01,E201,warning,Belt slip\n"
)
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
        self.on_wait: Callable[[float, str], None] | None = None

    def run(self, task: str) -> AgentResult:
        self.tasks.append(task)
        if self._error is not None:
            raise self._error
        trace = Trace()
        if self.on_wait is not None:
            self.on_wait(11.6, "token pacing")
        self._on_event(trace.add(1, EventKind.TOOL_CALL, {"id": "c1", "name": "lookup_error_code", "arguments": '{"codes": ["E101"]}'}))
        self._on_event(trace.add(1, EventKind.TOOL_RESULT, {"id": "c1", "name": "lookup_error_code", "ok": True, "content": "{}"}))
        for token in ["# Shift report\n\n", "## Summary\n", "All good."]:
            self._on_token(token)
        return AgentResult(REPORT, 2, self._stop_reason, trace.save())


class FakeAgentFactory:
    def __init__(self, **agent_options: Any) -> None:
        self._agent_options = agent_options
        self.agents: list[FakeAgent] = []
        self.log_paths: list[Path] = []
        self.shifts: list[ShiftWindow] = []

    def __call__(
        self,
        settings: Settings,
        log_path: Path,
        shift: ShiftWindow,
        on_token: Any = None,
        on_event: Any = None,
        on_wait: Any = None,
        language: Any = None,
    ) -> FakeAgent:
        self.log_paths.append(log_path)
        self.shifts.append(shift)
        agent = FakeAgent(on_token, on_event, **self._agent_options)
        agent.on_wait = on_wait
        self.agents.append(agent)
        return agent


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    (tmp_path / "my_log.csv").write_text(LOG, encoding="utf-8")
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings(api_key="sk-test", model="m", base_url=None)))


def test_report_saves_markdown_and_prints_summary(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeAgentFactory()

    exit_code = cli.main(["report", "--log", "my_log.csv", "--lang", "de", "--out", "out"], agent_factory=factory)

    assert exit_code == 0
    assert factory.log_paths == [Path("my_log.csv")]
    assert factory.agents[0].tasks[0].endswith("Report language: German.")
    reports = list((tmp_path / "out").glob("shift_report_*_de.md"))
    assert len(reports) == 1
    assert reports[0].read_text(encoding="utf-8") == REPORT + "\n"
    output = capsys.readouterr().out
    assert "waiting 12 s for the rate limit (token pacing)" in output
    assert "✓ step 1  lookup_error_code" in output
    assert '{"codes":["E101"]}' in output
    assert "All good." in output
    assert "Run summary" in output


def test_run_without_final_answer_exits_with_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeAgentFactory(stop_reason=StopReason.MAX_STEPS)

    exit_code = cli.main(["report", "--log", "my_log.csv"], agent_factory=factory)

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
    text = display.short_arguments('{"queries": ["' + "x" * 200 + '"]}')

    assert len(text) == display.MAX_ARGUMENT_CHARS
    assert text.endswith("...")


def test_missing_log_prints_message_and_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    factory = FakeAgentFactory()

    exit_code = cli.main(["report", "--log", "missing.csv"], agent_factory=factory)

    assert exit_code == 1
    assert factory.agents == []
    assert "Fault log not found: missing.csv" in capsys.readouterr().out


def test_default_shift_is_early_shift_on_log_date() -> None:
    factory = FakeAgentFactory()

    cli.main(["report", "--log", "my_log.csv"], agent_factory=factory)

    assert factory.shifts == [ShiftWindow(datetime(2026, 10, 14, 6, 0), datetime(2026, 10, 14, 14, 0))]
    assert "2026-10-14 from 06:00 to 14:00" in factory.agents[0].tasks[0]


def test_shift_options_reach_repository_and_task() -> None:
    factory = FakeAgentFactory()

    exit_code = cli.main(["report", "--log", "my_log.csv", "--shift-start", "22:00", "--shift-end", "06:00"], agent_factory=factory)

    assert exit_code == 0
    assert factory.shifts == [ShiftWindow(datetime(2026, 10, 14, 22, 0), datetime(2026, 10, 15, 6, 0))]
    assert "2026-10-14 from 22:00 to 06:00" in factory.agents[0].tasks[0]


def test_invalid_shift_time_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["report", "--shift-start", "6 Uhr"], agent_factory=FakeAgentFactory())

    assert exit_info.value.code == 2
    assert "'6 Uhr' is not a time in HH:MM format" in capsys.readouterr().err


def test_equal_shift_start_and_end_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(
        ["report", "--log", "my_log.csv", "--shift-start", "06:00", "--shift-end", "06:00"], agent_factory=FakeAgentFactory()
    )

    assert exit_code == 1
    assert "Invalid shift: shift start and end must differ" in capsys.readouterr().out


def test_quota_error_prints_message_and_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.main(["report"], agent_factory=FakeAgentFactory(error=QuotaExhaustedError("8m50.496s")))

    assert exit_code == 1
    output = " ".join(capsys.readouterr().out.split())
    assert "Quota exhausted:" in output
    assert "daily limit; it asks to try again in 8m50.496s" in output


@pytest.mark.parametrize(
    "secret",
    ["sk-abc123secret", "gsk_AbCdEf0123456789xyz", "AIzaSyA1b2C3d4E5f6G7h8I9j0KlMnOpQrStUv"],
)
def test_api_error_redacts_known_key_formats(secret: str, capsys: pytest.CaptureFixture[str]) -> None:
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    error = openai.APIStatusError(f"Invalid API Key: {secret}", response=httpx.Response(401, request=request), body=None)

    exit_code = cli.main(["report", "--log", "my_log.csv"], agent_factory=FakeAgentFactory(error=error))

    output = capsys.readouterr().out
    assert exit_code == 1
    assert secret not in output
    assert "<redacted>" in output


def test_api_error_redacts_exact_key_from_environment(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("LLM_API_KEY", "custom-provider-token-42")
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    error = openai.APIStatusError(
        "Key custom-provider-token-42 is not valid", response=httpx.Response(401, request=request), body=None
    )

    cli.main(["report", "--log", "my_log.csv"], agent_factory=FakeAgentFactory(error=error))

    output = capsys.readouterr().out
    assert "custom-provider-token-42" not in output
    assert "Key <redacted> is not valid" in output


def test_default_log_is_the_project_data_file_from_any_folder() -> None:
    factory = FakeAgentFactory()

    exit_code = cli.main(["report"], agent_factory=factory)

    assert exit_code == 0
    assert factory.log_paths == [app.DATA_DIR / "fault_log.csv"]
    assert factory.log_paths[0].is_absolute()


def test_chroma_dir_is_inside_the_project() -> None:
    assert app.CHROMA_DIR == app.PROJECT_DIR / "chroma_db"


def test_invalid_fault_log_prints_line_and_reason_and_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.csv").write_text(
        "event_id,start_time,end_time,machine_id,error_code,severity,message\n"
        "EV-0001,2026-10-14 07:00,2026-10-14 07:30,CNV-01,E202,fatal,x\n",
        encoding="utf-8",
    )
    factory = FakeAgentFactory()

    exit_code = cli.main(["report", "--log", "broken.csv"], agent_factory=factory)

    output = " ".join(capsys.readouterr().out.split())
    assert exit_code == 1
    assert factory.agents == []
    assert "Fault log error: broken.csv line 2: unknown severity 'fatal'" in output
    assert "Traceback" not in output


def test_out_path_that_is_a_file_exits_1_before_the_agent_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "reports.txt").write_text("not a folder", encoding="utf-8")
    factory = FakeAgentFactory()

    exit_code = cli.main(["report", "--log", "my_log.csv", "--out", "reports.txt"], agent_factory=factory)

    assert exit_code == 1
    assert factory.agents == []
    assert "Output path is not a directory: reports.txt" in capsys.readouterr().out


class RecordingRun:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], cwd: Path, check: bool) -> SimpleNamespace:
        self.calls.append((command, cwd))
        return SimpleNamespace(returncode=0)


def test_ui_command_starts_streamlit_from_the_project_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    run = RecordingRun()
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cli.subprocess, "run", run)

    exit_code = cli.main(["ui"])

    assert exit_code == 0
    command, cwd = run.calls[0]
    assert command[1:4] == ["-m", "streamlit", "run"]
    assert Path(command[4]) == app.PROJECT_DIR / "src" / "maestro" / "ui.py"
    assert cwd == app.PROJECT_DIR


def test_ui_command_without_streamlit_explains_how_to_install(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run = RecordingRun()
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(cli.subprocess, "run", run)

    exit_code = cli.main(["ui"])

    assert exit_code == 1
    assert run.calls == []
    assert 'Streamlit is not installed. Run: pip install -e ".[ui]"' in capsys.readouterr().out
