"""
Memory Store — Three-layer memory system
1. ChromaDB — Semantic/vector memory (facts, preferences, procedures)
2. SQLite — Episodic memory (what happened and when)
3. Auto-extraction — LLM extracts memories post-session
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("SAM.MemoryStore")


class MemoryStore:
    def __init__(self, settings):
        self.settings = settings
        self._chroma_client = None
        self._collection = None
        self._db_path = Path(settings.sqlite_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()

    # ─── SQLite (Episodic) ─────────────────────────────────────────────────

    def _init_sqlite(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    response TEXT NOT NULL,
                    action TEXT,
                    metadata TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_model (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()
        logger.info("SQLite episodic store initialised")

    def save_episode(self, user_input: str, response: str,
                     action: Optional[str], timestamp: str):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO episodes (timestamp, user_input, response, action) VALUES (?,?,?,?)",
                (timestamp, user_input, response, action)
            )
            conn.commit()

    def get_recent_episodes(self, limit: int = 10) -> List[Dict]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT timestamp, user_input, response, action FROM episodes ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [
            {"timestamp": r[0], "user": r[1], "response": r[2], "action": r[3]}
            for r in rows
        ]

    def update_user_model(self, key: str, value: str):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_model (key, value, updated_at) VALUES (?,?,?)",
                (key, value, datetime.now().isoformat())
            )
            conn.commit()

    # ─── ChromaDB (Semantic) ───────────────────────────────────────────────

    def _init_chroma(self):
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            chroma_path = Path(self.settings.chroma_path)
            chroma_path.mkdir(parents=True, exist_ok=True)

            self._chroma_client = chromadb.PersistentClient(
                path=str(chroma_path)
            )
            self._collection = self._chroma_client.get_or_create_collection(
                name="sam_memory",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info("ChromaDB semantic store initialised")

        except ImportError:
            logger.warning("ChromaDB not installed — semantic memory disabled")
        except Exception as e:
            logger.error(f"ChromaDB init error: {e}")

    def save_semantic(self, content: str, metadata: dict = None):
        """Save a fact/preference/procedure to semantic memory."""
        if self._collection is None:
            return

        try:
            embedding = self._get_embedding(content)
            doc_id = f"mem_{datetime.now().timestamp()}"

            self._collection.add(
                documents=[content],
                embeddings=[embedding],
                metadatas=[metadata or {}],
                ids=[doc_id]
            )
            logger.debug(f"Saved to semantic memory: {content[:60]}")

        except Exception as e:
            logger.error(f"Semantic memory save error: {e}")

    def search_semantic(self, query: str, top_k: int = 5) -> List[Dict]:
        """Retrieve top-K semantically similar memories."""
        if self._collection is None:
            return []

        try:
            embedding = self._get_embedding(query)
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, self._collection.count()),
                include=["documents", "metadatas", "distances"]
            )

            memories = []
            if results["documents"]:
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0]
                ):
                    memories.append({
                        "content": doc,
                        "metadata": meta,
                        "relevance": 1 - dist
                    })
            return memories

        except Exception as e:
            logger.error(f"Semantic memory search error: {e}")
            return []

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding via Ollama nomic-embed-text."""
        import requests
        response = requests.post(
            f"{self.settings.ollama_host}/api/embeddings",
            json={"model": self.settings.embedding_model, "prompt": text},
            timeout=30
        )
        return response.json()["embedding"]

    def extract_and_save(self, user_input: str, response: str):
        """
        Use LLM to extract memorable facts from the conversation
        and save them to semantic memory.
        """
        try:
            import requests

            prompt = f"""Extract any important facts, preferences, or information about the user from this conversation.
Return a JSON array of strings. Each string is one memorable fact.
If nothing important, return an empty array [].

User said: {user_input}
SAM responded: {response}

Return ONLY a JSON array, nothing else."""

            r = requests.post(
                f"{self.settings.ollama_host}/api/generate",
                json={
                    "model": self.settings.primary_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                },
                timeout=30
            )

            raw = r.json().get("response", "[]")
            facts = json.loads(raw)

            if isinstance(facts, list):
                for fact in facts:
                    if isinstance(fact, str) and len(fact) > 10:
                        self.save_semantic(fact, metadata={
                            "source": "auto_extract",
                            "timestamp": datetime.now().isoformat()
                        })
                logger.info(f"Extracted {len(facts)} memories from session")

        except Exception as e:
            logger.debug(f"Memory extraction skipped: {e}")
