"""
Memory Store — Three-layer memory system
All data in ~/.sam_data — survives reinstalls.
ChromaDB: semantic/vector memory
SQLite: episodic memory
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("SAM.MemoryStore")

SAM_DATA_DIR = Path.home() / ".sam_data"


class MemoryStore:
    def __init__(self, settings):
        self.settings = settings
        self._chroma_client = None
        self._collection = None
        self._db_path = Path(settings.sqlite_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._init_chroma()

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
        logger.info(f"SQLite at {self._db_path}")

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
        return [{"timestamp": r[0], "user": r[1], "response": r[2], "action": r[3]} for r in rows]

    def _init_chroma(self):
        try:
            import chromadb
            chroma_path = Path(self.settings.chroma_path)
            chroma_path.mkdir(parents=True, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(path=str(chroma_path))
            self._collection = self._chroma_client.get_or_create_collection(
                name="sam_memory",
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"ChromaDB at {chroma_path}")
        except ImportError:
            logger.warning("ChromaDB not installed")
        except Exception as e:
            logger.error(f"ChromaDB init error: {e}")

    def save_semantic(self, content: str, metadata: dict = None):
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
        except Exception as e:
            logger.error(f"Semantic save error: {e}")

    def search_semantic(self, query: str, top_k: int = 5) -> List[Dict]:
        if self._collection is None:
            return []
        try:
            count = self._collection.count()
            if count == 0:
                return []
            safe_k = min(top_k, count)
            embedding = self._get_embedding(query)
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=safe_k,
                include=["documents", "metadatas", "distances"]
            )
            memories = []
            if results["documents"]:
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0]
                ):
                    memories.append({"content": doc, "metadata": meta, "relevance": 1 - dist})
            return memories
        except Exception as e:
            logger.error(f"Semantic search error: {e}")
            return []

    def _get_embedding(self, text: str) -> List[float]:
        import requests
        response = requests.post(
            f"{self.settings.ollama_host}/api/embeddings",
            json={"model": self.settings.embedding_model, "prompt": text},
            timeout=30
        )
        return response.json()["embedding"]

    def extract_and_save(self, user_input: str, response: str):
        try:
            import requests
            prompt = f"""Extract important facts or preferences about the user from this conversation.
Return a JSON array of strings. If nothing important, return [].

User: {user_input}
SAM: {response}

Return ONLY a JSON array."""
            r = requests.post(
                f"{self.settings.ollama_host}/api/generate",
                json={"model": self.settings.primary_model, "prompt": prompt, "stream": False, "format": "json"},
                timeout=30
            )
            facts = json.loads(r.json().get("response", "[]"))
            if isinstance(facts, list):
                for fact in facts:
                    if isinstance(fact, str) and len(fact) > 10:
                        self.save_semantic(fact, metadata={
                            "source": "auto_extract",
                            "timestamp": datetime.now().isoformat()
                        })
                logger.info(f"Extracted {len(facts)} memories")
        except Exception as e:
            logger.debug(f"Memory extraction skipped: {e}")
