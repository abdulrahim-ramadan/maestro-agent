from pathlib import Path

import pytest

from maestro.knowledge.chunker import MarkdownChunker

MANUAL = """# Test Machine Manual

Intro text.

## Belt Slip

Belt slips under load.

## Motor Overheating

Motor gets hot.
"""


def test_splits_by_level_two_headings() -> None:
    chunks = MarkdownChunker().chunk_text(MANUAL, source="test_machine")

    assert [chunk.heading for chunk in chunks] == ["", "Belt Slip", "Motor Overheating"]
    assert chunks[1].text == "## Belt Slip\n\nBelt slips under load."
    assert chunks[2].text.startswith("## Motor Overheating")
    assert all(chunk.source == "test_machine" for chunk in chunks)


def test_long_section_respects_size_limit() -> None:
    text = "## Long Section\n\n" + "word " * 500

    chunks = MarkdownChunker(max_chars=200, overlap=50).chunk_text(text, source="long")

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 200 for chunk in chunks)
    assert all(chunk.heading == "Long Section" for chunk in chunks)


def word_section(word_count: int) -> str:
    return "## Words\n\n" + " ".join(f"w{index}" for index in range(word_count))


def test_consecutive_chunks_overlap() -> None:
    chunks = MarkdownChunker(max_chars=300, overlap=60).chunk_text(word_section(400), source="words")

    for previous, current in zip(chunks, chunks[1:]):
        previous_words = previous.text.split()
        current_words = current.text.split()
        shared = previous_words[previous_words.index(current_words[0]) :]
        assert current_words[: len(shared)] == shared
        assert len(" ".join(shared)) >= 60 - len(max(previous_words, key=len)) - 1


def test_splits_only_at_whitespace() -> None:
    text = word_section(400)
    original_words = set(text.split())

    chunks = MarkdownChunker(max_chars=250, overlap=40).chunk_text(text, source="words")

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 250 for chunk in chunks)
    assert all(word in original_words for chunk in chunks for word in chunk.text.split())
    covered = [word for chunk in chunks for word in chunk.text.split()]
    assert list(dict.fromkeys(covered)) == text.split()


def test_word_longer_than_limit_is_cut_hard() -> None:
    chunks = MarkdownChunker(max_chars=50, overlap=10).chunk_text("x" * 120, source="long_word")

    assert all(len(chunk.text) <= 50 for chunk in chunks)
    assert "".join(chunk.text for chunk in chunks) == "x" * 120


def test_ids_are_stable_and_unique(tmp_path: Path) -> None:
    path = tmp_path / "conveyor.md"
    path.write_text(MANUAL, encoding="utf-8")
    chunker = MarkdownChunker()

    first = chunker.chunk_file(path)
    second = chunker.chunk_file(path)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert len({chunk.id for chunk in first}) == len(first)
    assert first[0].source == "conveyor"


def test_ids_differ_between_sources() -> None:
    chunker = MarkdownChunker()

    first = chunker.chunk_text(MANUAL, source="press")
    second = chunker.chunk_text(MANUAL, source="conveyor")

    assert {chunk.id for chunk in first}.isdisjoint(chunk.id for chunk in second)


@pytest.mark.parametrize("max_chars, overlap", [(0, 0), (100, 100), (100, -1)])
def test_rejects_invalid_sizes(max_chars: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        MarkdownChunker(max_chars=max_chars, overlap=overlap)
