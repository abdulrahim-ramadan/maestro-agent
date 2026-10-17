from pathlib import Path

import pytest

from maestro.knowledge.chunker import MarkdownChunker
from maestro.knowledge.store import SearchHit
from maestro.tools.factory_data import load_error_codes
from maestro.tools.manuals import MAX_HITS, MAX_QUERIES, REPEATED_TEXT, MachineType, SearchManualsTool

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class FakeManualStore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str | None]] = []

    def search(self, query: str, k: int = 3, source: str | None = None) -> list[SearchHit]:
        self.calls.append((query, k, source))
        return [SearchHit(text="## Belt Slip\n\nTension the belt.", source="conveyor", heading="Belt Slip", score=0.81)]


def test_returns_hits_with_citation_fields() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(queries=[" belt slipping "], machine_type="conveyor")

    assert result.ok
    assert store.calls == [("belt slipping", MAX_HITS, "conveyor")]
    assert result.data["results"] == [
        {
            "query": "belt slipping",
            "hits": [{"source": "conveyor.md", "heading": "Belt Slip", "score": 0.81, "text": "## Belt Slip\n\nTension the belt."}],
        }
    ]


def test_returns_hits_per_query_in_one_call() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(queries=["belt slip E201", "wire feed jam E101"])

    assert result.ok
    assert [item["query"] for item in result.data["results"]] == ["belt slip E201", "wire feed jam E101"]
    assert store.calls == [("belt slip E201", MAX_HITS, None), ("wire feed jam E101", MAX_HITS, None)]


def test_section_found_by_several_queries_is_sent_once() -> None:
    result = SearchManualsTool(FakeManualStore()).run(queries=["belt slip", "belt tension"])

    first_hit, second_hit = (item["hits"][0] for item in result.data["results"])
    assert first_hit["text"].startswith("## Belt Slip")
    assert second_hit == {**first_hit, "text": REPEATED_TEXT}


class TwoSectionStore:
    def search(self, query: str, k: int = 3, source: str | None = None) -> list[SearchHit]:
        return [
            SearchHit(text="## Wire Feed Jam\n\nSymptoms", source="welding_robot", heading="Wire Feed Jam", score=0.6),
            SearchHit(text="## Screw Feeder Empty\n\nRefill", source="screwdriving_station", heading="Screw Feeder Empty", score=0.5),
            SearchHit(text="4. Replace the rollers.", source="welding_robot", heading="Wire Feed Jam", score=0.4),
        ]


def test_only_chunks_of_the_best_section_are_returned() -> None:
    result = SearchManualsTool(TwoSectionStore()).run(queries=["wire feed jam"])

    hits = result.data["results"][0]["hits"]
    assert [(hit["heading"], hit["text"]) for hit in hits] == [
        ("Wire Feed Jam", "## Wire Feed Jam\n\nSymptoms"),
        ("Wire Feed Jam", "4. Replace the rollers."),
    ]


def test_null_machine_type_searches_all_manuals() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(queries=["overheating"], machine_type=None)

    assert result.ok
    assert store.calls[0][2] is None


def test_rejects_unknown_machine_type() -> None:
    result = SearchManualsTool(FakeManualStore()).run(queries=["jam"], machine_type="lathe")

    assert not result.ok
    assert "welding_robot, conveyor, press, screwdriving_station" in result.error


@pytest.mark.parametrize("queries", [[], ["q"] * (MAX_QUERIES + 1), "belt slip"])
def test_rejects_wrong_number_of_queries(queries: object) -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(queries=queries)

    assert result == result.failure(f"queries must be a list of 1 to {MAX_QUERIES} strings")
    assert store.calls == []


def test_rejects_empty_query() -> None:
    store = FakeManualStore()

    result = SearchManualsTool(store).run(queries=["belt slip", "  "])

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
