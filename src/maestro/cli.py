import argparse
import importlib.util
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from datetime import time as clock_time
from pathlib import Path

from openai import APIError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from maestro.app import CHROMA_DIR, DATA_DIR, MANUALS_DIR, PROJECT_DIR, build_agent
from maestro.config import ConfigError, Settings
from maestro.core.agent import Agent, StopReason
from maestro.core.trace import EventKind, TraceEvent
from maestro.display import redact_secrets, short_arguments, wait_message
from maestro.knowledge.store import ManualStore
from maestro.llm.client import QuotaExhaustedError
from maestro.prompts import ReportLanguage, report_task
from maestro.tools.factory_data import FaultLogError, ShiftWindow

UI_SCRIPT = Path(__file__).with_name("ui.py")
DEFAULT_SHIFT_START = "06:00"
DEFAULT_SHIFT_END = "14:00"

AgentFactory = Callable[..., Agent]


class LiveStepView:
    def __init__(self, console: Console) -> None:
        self._console = console
        self._arguments: dict[str, str] = {}
        self._streaming = False

    def on_event(self, event: TraceEvent) -> None:
        if event.kind is EventKind.TOOL_CALL:
            self._arguments[event.payload["id"]] = event.payload["arguments"]
        elif event.kind is EventKind.TOOL_RESULT:
            self._print_tool_line(event)
        elif event.kind is EventKind.ERROR:
            self._console.print(f"[red]✗ step {event.step}  run failed[/red]")

    def on_wait(self, seconds: float, reason: str) -> None:
        self._console.print(f"[yellow]… {escape(wait_message(seconds, reason))}[/yellow]", highlight=False)

    def on_token(self, text: str) -> None:
        if not self._streaming:
            self._streaming = True
            self._console.rule("Report")
        self._console.print(text, end="", markup=False, highlight=False, soft_wrap=True)

    def finish(self) -> None:
        if self._streaming:
            self._console.print()
            self._console.rule()

    def _print_tool_line(self, event: TraceEvent) -> None:
        icon = "[green]✓[/green]" if event.payload["ok"] else "[red]✗[/red]"
        arguments = escape(short_arguments(self._arguments.pop(event.payload["id"], "")))
        name = escape(event.payload["name"])
        self._console.print(f"{icon} step {event.step}  [bold]{name}[/bold]  [dim]{arguments}[/dim]", highlight=False)


def save_report(report: str, out_dir: str | Path, language: ReportLanguage) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"shift_report_{datetime.now():%Y%m%d_%H%M%S}_{language.value}.md"
    path.write_text(report.strip() + "\n", encoding="utf-8")
    return path


def run_report(args: argparse.Namespace, console: Console, agent_factory: AgentFactory) -> int:
    log_path = Path(args.log)
    if not log_path.is_file():
        console.print(f"[bold red]Fault log not found:[/bold red] {escape(str(log_path))}", highlight=False)
        return 1
    out_dir = Path(args.out)
    if out_dir.exists() and not out_dir.is_dir():
        console.print(f"[bold red]Output path is not a directory:[/bold red] {escape(str(out_dir))}", highlight=False)
        return 1
    try:
        shift = ShiftWindow.for_log(log_path, args.shift_start, args.shift_end)
    except FaultLogError as error:
        console.print(f"[bold red]Fault log error:[/bold red] {escape(str(error))}", highlight=False)
        return 1
    except ValueError as error:
        console.print(f"[bold red]Invalid shift:[/bold red] {escape(str(error))}", highlight=False)
        return 1

    language = ReportLanguage(args.lang)
    view = LiveStepView(console)
    agent = agent_factory(
        Settings.from_env(),
        log_path,
        shift,
        on_token=view.on_token,
        on_event=view.on_event,
        on_wait=view.on_wait,
        language=language,
    )
    console.print(f"[bold]Shift report[/bold] {shift.start:%Y-%m-%d %H:%M} to {shift.end:%Y-%m-%d %H:%M}, language: {language.value}")

    started = time.perf_counter()
    try:
        result = agent.run(report_task(language, shift.start, shift.end))
    finally:
        view.finish()
    duration = time.perf_counter() - started

    if result.stop_reason is not StopReason.FINAL_ANSWER:
        console.print(f"[bold red]Run stopped without a report:[/bold red] {escape(result.answer)}")
        console.print(f"Trace: {result.trace_path}")
        return 1

    report_path = save_report(result.answer, args.out, language)
    table = Table(title="Run summary")
    table.add_column("Steps", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Report")
    table.add_column("Trace")
    table.add_row(str(result.steps), f"{duration:.1f} s", str(report_path), str(result.trace_path))
    console.print(table)
    return 0


def run_index(console: Console) -> int:
    store = ManualStore(persist_dir=CHROMA_DIR)
    chunk_count = store.index(MANUALS_DIR)
    console.print(f"Indexed [bold]{chunk_count}[/bold] chunks from {MANUALS_DIR}")
    return 0


def run_ui(console: Console) -> int:
    if importlib.util.find_spec("streamlit") is None:
        console.print('[bold red]Streamlit is not installed.[/bold red] Run: pip install -e ".\\[ui]"', highlight=False)
        return 1
    try:
        return subprocess.run([sys.executable, "-m", "streamlit", "run", str(UI_SCRIPT)], cwd=PROJECT_DIR, check=False).returncode
    except KeyboardInterrupt:
        return 0


def _clock_time(value: str) -> clock_time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a time in HH:MM format") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maestro", description="Shift report agent for production line maintenance")
    commands = parser.add_subparsers(dest="command", required=True)

    report = commands.add_parser("report", help="analyze the fault log and write a shift report")
    report.add_argument("--log", default=str(DATA_DIR / "fault_log.csv"), help="path to the fault log CSV")
    report.add_argument("--lang", choices=[language.value for language in ReportLanguage], default="en")
    report.add_argument("--out", default="reports", help="directory for the saved report")
    report.add_argument("--shift-start", type=_clock_time, default=DEFAULT_SHIFT_START, help="shift start as HH:MM")
    report.add_argument("--shift-end", type=_clock_time, default=DEFAULT_SHIFT_END, help="shift end as HH:MM")

    commands.add_parser("index", help="build or refresh the maintenance manual index")
    commands.add_parser("ui", help="start the Streamlit web interface")
    return parser


def _redact(message: str) -> str:
    return escape(redact_secrets(message))


def main(argv: Sequence[str] | None = None, agent_factory: AgentFactory = build_agent) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    console = Console()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "index":
            return run_index(console)
        if args.command == "ui":
            return run_ui(console)
        return run_report(args, console, agent_factory)
    except ConfigError as error:
        console.print(f"[bold red]Configuration error:[/bold red] {_redact(str(error))}", highlight=False)
    except QuotaExhaustedError as error:
        console.print(f"[bold red]Quota exhausted:[/bold red] {_redact(str(error))}", highlight=False)
    except APIError as error:
        console.print(f"[bold red]API error ({type(error).__name__}):[/bold red] {_redact(str(error))}", highlight=False)
    return 1
