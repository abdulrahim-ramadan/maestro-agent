from pathlib import Path

import pytest

from maestro.knowledge.store import ManualStore

pytestmark = pytest.mark.slow

WELDING_MANUAL = """# Welding Robot

## Wire Feed Jam

The welding wire stops feeding and the robot halts during the weld. Replace the feed rollers and the wire liner.
"""

CONVEYOR_MANUAL = """# Conveyor

## Part Jam at Transfer Point

Parts get stuck where the belt hands over to the next station. Realign the guide rails.
"""


@pytest.fixture
def manuals_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "manuals"
    directory.mkdir()
    (directory / "welding_robot.md").write_text(WELDING_MANUAL, encoding="utf-8")
    (directory / "conveyor.md").write_text(CONVEYOR_MANUAL, encoding="utf-8")
    return directory


@pytest.fixture
def store(tmp_path: Path) -> ManualStore:
    return ManualStore(persist_dir=tmp_path / "chroma_db", collection="test_manuals")


def test_search_finds_matching_manual(store: ManualStore, manuals_dir: Path) -> None:
    assert store.is_empty()

    assert store.index(manuals_dir) == 4
    hits = store.search("robot stops welding because the wire does not feed", k=1)

    assert not store.is_empty()
    assert len(hits) == 1
    assert hits[0].source == "welding_robot"
    assert hits[0].heading == "Wire Feed Jam"


def test_reindexing_adds_no_duplicates(store: ManualStore, manuals_dir: Path) -> None:
    store.index(manuals_dir)
    store.index(manuals_dir)

    hits = store.search("parts stuck", k=10)

    assert len(hits) == 4
    assert len({(hit.source, hit.heading, hit.text) for hit in hits}) == 4


def test_reindexing_removes_stale_chunks(store: ManualStore, manuals_dir: Path) -> None:
    store.index(manuals_dir)
    (manuals_dir / "welding_robot.md").write_text("# Welding Robot\n", encoding="utf-8")
    (manuals_dir / "conveyor.md").unlink()

    assert store.index(manuals_dir) == 1
    hits = store.search("wire feed jam", k=10)

    assert [(hit.source, hit.heading) for hit in hits] == [("welding_robot", "")]


def test_search_filters_by_source(store: ManualStore, manuals_dir: Path) -> None:
    store.index(manuals_dir)

    hits = store.search("wire feed jam", k=3, source="conveyor")

    assert hits
    assert all(hit.source == "conveyor" for hit in hits)


def test_search_on_empty_store_returns_nothing(store: ManualStore) -> None:
    assert store.search("anything") == []
