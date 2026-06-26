"""
Memory Retrieval — Gets relevant memories for the current query.
Combines semantic search + recent episodes.
"""

import logging
from typing import List, Dict
from pathlib import Path

logger = logging.getLogger("SAM.MemoryRetriever")


class MemoryRetriever:
    def __init__(self):
        self._store = None

    def _get_store(self, settings=None):
        if self._store is None and settings:
            from memory.store import MemoryStore
            self._store = MemoryStore(settings)
        return self._store

    def retrieve(self, query: str, settings=None, top_k: int = 5) -> List[Dict]:
        """
        Retrieve top-K relevant memories for the current query.
        Returns list of memory dicts with 'content' key.
        """
        try:
            store = self._get_store(settings)
            if store is None:
                return []

            memories = store.search_semantic(query, top_k=top_k)
            return memories

        except Exception as e:
            logger.debug(f"Memory retrieval skipped: {e}")
            return []
