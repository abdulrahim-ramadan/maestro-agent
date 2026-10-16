import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

HEADING_PATTERN = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
ID_LENGTH = 16


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source: str
    heading: str


class MarkdownChunker:
    def __init__(self, max_chars: int = 800, overlap: int = 100) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if not 0 <= overlap < max_chars:
            raise ValueError("overlap must be at least 0 and smaller than max_chars")
        self._max_chars = max_chars
        self._overlap = overlap

    def chunk_file(self, path: str | Path) -> list[Chunk]:
        file_path = Path(path)
        return self.chunk_text(file_path.read_text(encoding="utf-8"), source=file_path.stem)

    def chunk_text(self, text: str, source: str) -> list[Chunk]:
        chunks: list[Chunk] = []
        for heading, section in self._sections(text):
            for piece in self._split_by_size(section):
                position = len(chunks)
                chunks.append(Chunk(_chunk_id(source, heading, position), piece, source, heading))
        return chunks

    @staticmethod
    def _sections(text: str) -> list[tuple[str, str]]:
        matches = list(HEADING_PATTERN.finditer(text))
        boundaries = [0, *(match.start() for match in matches), len(text)]
        headings = ["", *(match.group(1) for match in matches)]
        sections = [(heading, text[start:end].strip()) for heading, start, end in zip(headings, boundaries, boundaries[1:])]
        return [(heading, section) for heading, section in sections if section]

    def _split_by_size(self, section: str) -> list[str]:
        if len(section) <= self._max_chars:
            return [section]
        step = self._max_chars - self._overlap
        pieces: list[str] = []
        for start in range(0, len(section), step):
            pieces.append(section[start : start + self._max_chars])
            if start + self._max_chars >= len(section):
                break
        return pieces


def _chunk_id(source: str, heading: str, position: int) -> str:
    return hashlib.sha256(f"{source}|{heading}|{position}".encode()).hexdigest()[:ID_LENGTH]
