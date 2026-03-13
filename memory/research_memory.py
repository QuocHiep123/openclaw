"""
Research-specific memory layer built on top of VectorStore.

Provides typed helpers for storing / retrieving papers, ideas,
experiment results, and chat history.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from memory.vector_store import vector_store

logger = logging.getLogger(__name__)

# Collection names
PAPERS = "papers"
IDEAS = "ideas"
EXPERIMENTS = "experiments"
TASKS = "tasks"
CHAT_HISTORY = "chat_history"


class ResearchMemory:
    """High-level memory interface used by all agents."""

    def __init__(self, store=None):
        self._store = store or vector_store

    # ---- Papers -----------------------------------------------------------

    def store_paper(self, arxiv_id: str, title: str, summary: str, metadata: Optional[Dict] = None) -> None:
        meta = {"arxiv_id": arxiv_id, "title": title, "stored_at": datetime.now(timezone.utc).isoformat()}
        if metadata:
            meta.update({k: str(v) for k, v in metadata.items()})
        self._store.add(
            collection_name=PAPERS,
            documents=[summary],
            metadatas=[meta],
            ids=[f"paper-{arxiv_id}"],
        )

    def search_papers(self, query: str, n: int = 5) -> List[Dict[str, Any]]:
        return self._store.query(PAPERS, query, n_results=n)

    # ---- Ideas ------------------------------------------------------------

    def store_idea(self, idea: str, source: str = "", tags: Optional[List[str]] = None) -> None:
        meta = {"source": source, "tags": ",".join(tags or []), "stored_at": datetime.now(timezone.utc).isoformat()}
        self._store.add(IDEAS, documents=[idea], metadatas=[meta])

    def search_ideas(self, query: str, n: int = 5) -> List[Dict[str, Any]]:
        return self._store.query(IDEAS, query, n_results=n)

    # ---- Experiments ------------------------------------------------------

    def store_experiment(self, name: str, config: Dict, results: Dict) -> None:
        doc = json.dumps({"config": config, "results": results}, default=str)
        meta = {"name": name, "stored_at": datetime.now(timezone.utc).isoformat()}
        self._store.add(EXPERIMENTS, documents=[doc], metadatas=[meta], ids=[f"exp-{name}"])

    def search_experiments(self, query: str, n: int = 5) -> List[Dict[str, Any]]:
        return self._store.query(EXPERIMENTS, query, n_results=n)

    # ---- Tasks / Notes ----------------------------------------------------

    def store_task(self, task: str, status: str = "open") -> None:
        meta = {"status": status, "stored_at": datetime.now(timezone.utc).isoformat()}
        self._store.add(TASKS, documents=[task], metadatas=[meta])

    def search_tasks(self, query: str, n: int = 10) -> List[Dict[str, Any]]:
        return self._store.query(TASKS, query, n_results=n)

    # ---- Chat History (NEW) -----------------------------------------------

    def store_chat_message(self, user_id: int, role: str, content: str) -> None:
        """Store a single chat message (user or assistant) for conversation context."""
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "user_id": str(user_id),
            "role": role,
            "timestamp": now,
        }
        doc_id = f"chat-{user_id}-{now}"
        self._store.add(CHAT_HISTORY, documents=[content], metadatas=[meta], ids=[doc_id])

    def get_recent_chat(self, user_id: int, n: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent chat messages for a user (via semantic search on recent context)."""
        results = self._store.query(
            CHAT_HISTORY,
            query_text=f"user {user_id} recent conversation",
            n_results=n,
        )
        # Filter by user_id and sort by timestamp
        user_msgs = [r for r in results if r.get("metadata", {}).get("user_id") == str(user_id)]
        user_msgs.sort(key=lambda x: x.get("metadata", {}).get("timestamp", ""))
        return user_msgs

    # ---- Utilities --------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        return {
            name: self._store.count(name)
            for name in [PAPERS, IDEAS, EXPERIMENTS, TASKS, CHAT_HISTORY]
        }


# Module-level singleton
research_memory = ResearchMemory()
