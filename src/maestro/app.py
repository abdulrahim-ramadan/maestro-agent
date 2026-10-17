from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from maestro.config import Settings
from maestro.core.agent import Agent
from maestro.core.trace import TraceEvent
from maestro.knowledge.store import ManualStore
from maestro.llm.client import LLMClient
from maestro.prompts import SYSTEM_PROMPT
from maestro.tools import ToolRegistry
from maestro.tools.factory import CalcDowntimeTool, LookupErrorCodeTool, ReadFaultLogTool
from maestro.tools.factory_data import FaultLogRepository, load_error_codes
from maestro.tools.manuals import ManualSearcher, SearchManualsTool

PROJECT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_DIR / "data"
MANUALS_DIR = DATA_DIR / "manuals"
ERROR_CODES_PATH = DATA_DIR / "error_codes.json"
CHROMA_DIR = Path("chroma_db")
SHIFT_START = datetime(2026, 10, 14, 6, 0)
SHIFT_END = datetime(2026, 10, 14, 14, 0)


def build_registry(
    repository: FaultLogRepository,
    error_codes: dict[str, dict[str, str]],
    manual_searcher: ManualSearcher,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFaultLogTool(repository))
    registry.register(LookupErrorCodeTool(error_codes))
    registry.register(SearchManualsTool(manual_searcher))
    registry.register(CalcDowntimeTool(repository))
    return registry


def open_manual_store(persist_dir: str | Path = CHROMA_DIR, manuals_dir: str | Path = MANUALS_DIR) -> ManualStore:
    store = ManualStore(persist_dir=persist_dir)
    if store.is_empty():
        store.index(manuals_dir)
    return store


def build_agent(
    settings: Settings,
    log_path: str | Path,
    on_token: Callable[[str], None] | None = None,
    on_event: Callable[[TraceEvent], None] | None = None,
) -> Agent:
    repository = FaultLogRepository(log_path, SHIFT_START, SHIFT_END)
    registry = build_registry(repository, load_error_codes(ERROR_CODES_PATH), open_manual_store())
    return Agent(LLMClient(settings), registry, SYSTEM_PROMPT, settings.max_steps, on_token=on_token, on_event=on_event)
