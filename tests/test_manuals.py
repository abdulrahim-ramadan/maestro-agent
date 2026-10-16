from pathlib import Path

from maestro.knowledge.chunker import MarkdownChunker
from maestro.knowledge.store import SearchHit
from maestro.tools.factory_data import load_error_codes
from maestro.tools.manuals import MachineType, SearchManualsTool

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class FakeManualStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    def search(self, query: str, k: int = 3, source: str | None = None) -> list[SearchHit]:
        self.calls.append((query, k, source))
        return [SearchHit(text="## Belt Slip\n\nTension the belt.", source="conveyor", heading="Belt Slip", score=0.81)]


def test_returns_hits_with_citation_fields() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(query=" belt slipping ", machine_type="conveyor")

    assert result.ok
    assert store.calls == [("belt slipping", 3, "conveyor")]
    assert result.data["hits"] == [
        {"source": "conveyor.md", "heading": "Belt Slip", "score": 0.81, "text": "## Belt Slip\n\nTension the belt."}
    ]


def test_null_machine_type_searches_all_manuals() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(query="overheating", machine_type=None)

    assert result.ok
    assert store.calls[0][2] is None


def test_rejects_unknown_machine_type() -> None:
    result = SearchManualsTool(FakeManualStore()).run(query="jam", machine_type="lathe")

    assert not result.ok
    assert "welding_robot, conveyor, press, screwdriving_station" in result.error


def test_rejects_empty_query() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(query="  ")

    assert not result.ok
    assert store.calls == []


def test_every_machine_type_has_a_manual() -> None:
    for machine_type in MachineType:
        assert (DATA_DIR / "manuals" / f"{machine_type.value}.md").is_file()


def test_every_error_code_appears_in_a_manual_section() -> None:
    chunker = MarkdownChunker()
    sections = [chunk.text for path in (DATA_DIR / "manuals").glob("*.md") for chunk in chunker.chunk_file(path)]

    for code in load_error_codes(DATA_DIR / "error_codes.json"):
        assert any(code in section for section in sections), code
