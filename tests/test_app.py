from datetime import datetime
from pathlib import Path

import pytest

from maestro.app import build_registry, open_manual_store
from maestro.knowledge.store import SearchHit
from maestro.tools.factory_data import FaultLogRepository

LOG = """event_id,start_time,end_time,machine_id,error_code,severity,message
EV-0001,2026-10-14 07:00:00,2026-10-14 07:30:00,CNV-01,E202,critical,Part jam
"""


class EmptySearcher:
    def search(self, query: str, k: int = 3, source: str | None = None) -> list[SearchHit]:
        return []


def test_registry_holds_the_four_report_tools(tmp_path: Path) -> None:
    log_path = tmp_path / "fault_log.csv"
    log_path.write_text(LOG, encoding="utf-8")
    repository = FaultLogRepository(log_path, datetime(2026, 10, 14, 6, 0), datetime(2026, 10, 14, 14, 0))

    registry = build_registry(repository, {"E202": {"title": "Part jam"}}, EmptySearcher())

    assert registry.names() == ["read_fault_log", "lookup_error_code", "search_manuals", "calc_downtime"]


@pytest.mark.slow
def test_empty_store_is_indexed_automatically(tmp_path: Path) -> None:
    manuals_dir = tmp_path / "manuals"
    manuals_dir.mkdir()
    (manuals_dir / "conveyor.md").write_text("## Belt Slip\n\nTension the belt.\n", encoding="utf-8")

    store = open_manual_store(persist_dir=tmp_path / "chroma_db", manuals_dir=manuals_dir)

    assert not store.is_empty()
    assert store.search("belt slip", k=1)[0].heading == "Belt Slip"
