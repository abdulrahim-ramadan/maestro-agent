import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from openai import APIError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from maestro.app import CHROMA_DIR, MANUALS_DIR, SHIFT_END, SHIFT_START, build_agent
from maestro.config import ConfigError, Settings
from maestro.core.agent import Agent, StopReason
from maestro.core.trace import EventKind, TraceEvent
from maestro.knowledge.store import ManualStore
from maestro.prompts import ReportLanguage, report_task

MAX_ARGUMENT_CHARS = 70
SECRET_PATTERN = re.compile(r"sk-[\w*\-]+")

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
        arguments = escape(_short_arguments(self._arguments.pop(event.payload["id"], "")))
        name = escape(event.payload["name"])
        self._console.print(f"{icon} step {event.step}  [bold]{name}[/bold]  [dim]{arguments}[/dim]", highlight=False)


def _short_arguments(raw_arguments: str) -> str:
    try:
        text = json.dumps(json.loads(raw_arguments or "{}"), ensure_ascii=False, separators=(",", ":"))
    except json.JSONDecodeError:
        text = raw_arguments
    return text if len(text) <= MAX_ARGUMENT_CHARS else text[: MAX_ARGUMENT_CHARS - 3] + "..."


def save_report(report: str, out_dir: str | Path, language: ReportLanguage) -> Path:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"shift_report_{datetime.now():%Y%m%d_%H%M%S}_{language.value}.md"
    path.write_text(report.strip() + "\n", encoding="utf-8")
    return path


def run_report(args: argparse.Namespace, console: Console, agent_factory: AgentFactory) -> int:
    language = ReportLanguage(args.lang)
    view = LiveStepView(console)
    agent = agent_factory(Settings.from_env(), args.log, on_token=view.on_token, on_event=view.on_event)
    console.print(f"[bold]Shift report[/bold] {SHIFT_START:%Y-%m-%d %H:%M}-{SHIFT_END:%H:%M}, language: {language.value}")

    started = time.perf_counter()
    try:
        result = agent.run(report_task(language, SHIFT_START, SHIFT_END))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maestro", description="Shift report agent for production line maintenance")
    commands = parser.add_subparsers(dest="command", required=True)

    report = commands.add_parser("report", help="analyze the fault log and write a shift report")
    report.add_argument("--log", default="data/fault_log.csv", help="path to the fault log CSV")
    report.add_argument("--lang", choices=[language.value for language in ReportLanguage], default="en")
    report.add_argument("--out", default="reports", help="directory for the saved report")

    commands.add_parser("index", help="build or refresh the maintenance manual index")
    return parser


def _redact(message: str) -> str:
    return escape(SECRET_PATTERN.sub("<redacted>", message))


def main(argv: Sequence[str] | None = None, agent_factory: AgentFactory = build_agent) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    console = Console()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "index":
            return run_index(console)
        return run_report(args, console, agent_factory)
    except ConfigError as error:
        console.print(f"[bold red]Configuration error:[/bold red] {_redact(str(error))}", highlight=False)
    except APIError as error:
        console.print(f"[bold red]API error ({type(error).__name__}):[/bold red] {_redact(str(error))}", highlight=False)
    return 1
