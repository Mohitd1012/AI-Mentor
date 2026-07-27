"""
ChromaDB wrapper for semantic memory retrieval.

Uses Chroma's default embedder (all-MiniLM-L6-v2 ONNX, ~80MB, fully local).
The collection's ID space stays in sync with SQLiteStore.memories.id.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"


class VectorStore:
    def __init__(self, persist_dir: Optional[Path] = None) -> None:
        self._dir = persist_dir or _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

        import chromadb
        from chromadb.config import Settings

        self._client = chromadb.PersistentClient(
            path=str(self._dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name="memories",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("[vector] ready — %d memories indexed", self._collection.count())

    def upsert(
        self,
        memory_id: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> None:
        # Chroma requires non-empty metadata. Always include at least an id.
        md = dict(metadata) if metadata else {}
        md.setdefault("_id", memory_id)
        self._collection.upsert(
            ids=[memory_id],
            documents=[content],
            metadatas=[md],
        )

    def delete(self, memory_id: str) -> None:
        try:
            self._collection.delete(ids=[memory_id])
        except Exception as exc:
            logger.warning("[vector] delete failed for %s: %s", memory_id, exc)

    def search(
        self,
        query: str,
        n_results: int = 3,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Returns: [{id, content, distance, metadata}] sorted by relevance.
        """
        if not query.strip():
            return []
        try:
            res = self._collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )
        except Exception as exc:
            logger.warning("[vector] query failed: %s", exc)
            return []

        ids       = (res.get("ids")       or [[]])[0]
        docs      = (res.get("documents") or [[]])[0]
        dists     = (res.get("distances") or [[]])[0]
        metas     = (res.get("metadatas") or [[]])[0]

        return [
            {"id": i, "content": d, "distance": dist, "metadata": m or {}}
            for i, d, dist, m in zip(ids, docs, dists, metas)
        ]

    def count(self) -> int:
        return self._collection.count()

    def clear(self) -> None:
        """Drop and recreate the collection."""
        self._client.delete_collection("memories")
        self._collection = self._client.get_or_create_collection(
            name="memories",
            metadata={"hnsw:space": "cosine"},
        )
