import json
import sys
from datetime import datetime
from pathlib import Path

from maestro.config import Settings
from maestro.core.agent import Agent
from maestro.core.trace import TraceEvent
from maestro.llm.client import LLMClient
from maestro.tools import ToolRegistry
from maestro.tools.factory import (
    CalcDowntimeTool,
    LookupErrorCodeTool,
    ReadFaultLogTool,
)
from maestro.tools.factory_data import FaultLogRepository, load_error_codes

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SHIFT_START = datetime(2026, 10, 14, 6, 0)
SHIFT_END = datetime(2026, 10, 14, 14, 0)
MAX_LINE_CHARS = 100
TASK = "Which machine had the most downtime in this shift, and what were its critical faults?"
SYSTEM_PROMPT = (
    "You are a maintenance assistant for a production line. "
    "The current shift is the early shift on 2026-10-14 from 06:00 to 14:00. "
    "Use the tools to read the fault log, calculate downtime and look up error codes. "
    "Base every statement on tool results."
)


def print_event(event: TraceEvent) -> None:
    summary = json.dumps(event.payload, ensure_ascii=False)
    if len(summary) > MAX_LINE_CHARS:
        summary = summary[:MAX_LINE_CHARS] + "..."
    print(f"[step {event.step}] {event.kind.value:<11} {summary}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    settings = Settings.from_env()
    repository = FaultLogRepository(DATA_DIR / "fault_log.csv", SHIFT_START, SHIFT_END)
    registry = ToolRegistry()
    registry.register(ReadFaultLogTool(repository))
    registry.register(LookupErrorCodeTool(load_error_codes(DATA_DIR / "error_codes.json")))
    registry.register(CalcDowntimeTool(repository))
    agent = Agent(LLMClient(settings), registry, SYSTEM_PROMPT, settings.max_steps, on_event=print_event)

    result = agent.run(TASK)

    print()
    print(f"Answer:\n{result.answer}")
    print()
    print(f"Stop reason: {result.stop_reason.value}, steps: {result.steps}, trace: {result.trace_path}")


if __name__ == "__main__":
    main()
