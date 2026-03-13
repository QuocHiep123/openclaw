"""
Chroma-based vector store for shared agent memory.

Provides add / query / delete operations on named *collections*
(e.g. "papers", "ideas", "experiments").
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from config.settings import settings

logger = logging.getLogger(__name__)


class VectorStore:
    """Thin wrapper around a Chroma persistent client."""

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        path = persist_dir or settings.chroma_persist_dir
        self._client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

    # ---- collection helpers ------------------------------------------------

    def _col(self, collection_name: str):
        """Get or create a Chroma collection."""
        return self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ---- public API --------------------------------------------------------

    def add(
        self,
        collection_name: str,
        documents: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ) -> None:
        """
        Add documents to a collection.

        If *ids* are not supplied they are derived from a SHA-256 hash of
        each document to avoid duplicates.
        """
        if ids is None:
            ids = [
                hashlib.sha256(doc.encode()).hexdigest()[:16]
                for doc in documents
            ]
        col = self._col(collection_name)
        col.upsert(documents=documents, metadatas=metadatas, ids=ids)
        logger.info("Upserted %d docs into '%s'", len(documents), collection_name)

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search inside a collection.

        Returns list of dicts with keys: id, document, metadata, distance.
        """
        col = self._col(collection_name)
        if col.count() == 0:
            return []
        results = col.query(query_texts=[query_text], n_results=n_results)
        items: List[Dict[str, Any]] = []
        for i in range(len(results["ids"][0])):
            items.append(
                {
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": (results["metadatas"][0][i] if results["metadatas"] else {}),
                    "distance": (results["distances"][0][i] if results["distances"] else None),
                }
            )
        return items

    def delete(self, collection_name: str, ids: List[str]) -> None:
        col = self._col(collection_name)
        col.delete(ids=ids)

    def count(self, collection_name: str) -> int:
        return self._col(collection_name).count()

    def list_collections(self) -> List[str]:
        return [c.name for c in self._client.list_collections()]


# Module-level singleton
vector_store = VectorStore()
