from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from maestro.knowledge.chunker import Chunk, MarkdownChunker


@dataclass(frozen=True)
class SearchHit:
    text: str
    source: str
    heading: str
    score: float


class ManualStore:
    def __init__(
        self,
        persist_dir: str | Path = "chroma_db",
        collection: str = "manuals",
        chunker: MarkdownChunker | None = None,
    ) -> None:
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection,
            embedding_function=DefaultEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )
        self._chunker = chunker or MarkdownChunker()

    def index(self, directory: str | Path) -> int:
        chunks: list[Chunk] = []
        for path in sorted(Path(directory).glob("*.md")):
            chunks.extend(self._chunker.chunk_file(path))
        current_ids = {chunk.id for chunk in chunks}
        stale_ids = [chunk_id for chunk_id in self._collection.get(include=[])["ids"] if chunk_id not in current_ids]
        if stale_ids:
            self._collection.delete(ids=stale_ids)
        if chunks:
            self._collection.upsert(
                ids=[chunk.id for chunk in chunks],
                documents=[chunk.text for chunk in chunks],
                metadatas=[{"source": chunk.source, "heading": chunk.heading} for chunk in chunks],
            )
        return len(chunks)

    def search(self, query: str, k: int = 3, source: str | None = None) -> list[SearchHit]:
        if self.is_empty():
            return []
        result = self._collection.query(
            query_texts=[query],
            n_results=k,
            where={"source": source} if source else None,
        )
        return [
            SearchHit(text=text, source=str(metadata["source"]), heading=str(metadata["heading"]), score=round(1 - distance, 4))
            for text, metadata, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True)
        ]

    def is_empty(self) -> bool:
        return self._collection.count() == 0
