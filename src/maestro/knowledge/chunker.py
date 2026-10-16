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
        pieces: list[str] = []
        start = 0
        while len(section) - start > self._max_chars:
            end = self._last_break(section, start, start + self._max_chars)
            pieces.append(section[start:end].rstrip())
            start = self._next_start(section, start, end)
        pieces.append(section[start:])
        return pieces

    @staticmethod
    def _last_break(section: str, start: int, limit: int) -> int:
        for index in range(limit, start, -1):
            if section[index].isspace():
                return index
        return limit

    def _next_start(self, section: str, start: int, end: int) -> int:
        candidate = max(end - self._overlap, start + 1)
        while candidate < end and not section[candidate - 1].isspace():
            candidate += 1
        while candidate < len(section) and section[candidate].isspace():
            candidate += 1
        return candidate


def _chunk_id(source: str, heading: str, position: int) -> str:
    return hashlib.sha256(f"{source}|{heading}|{position}".encode()).hexdigest()[:ID_LENGTH]
