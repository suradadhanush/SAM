"""
AGENT — Reflection Engine (Phase 1)

After a task finishes (success, failure, or max-steps-reached), generates
a short lesson: what went well, what didn't, and what to do differently
next time. Stored permanently in ~/.sam_data/reflection/ — never
overwritten or deleted, same spirit as Founder Mode.

Decoupled from core/brain.py — direct Ollama call, fails safe (returns
None on error; caller simply skips storing a reflection for that task —
this never blocks or breaks the task result itself).
"""

import json
import logging
import sqlite3
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger("SAM.Agent.Reflection")

SAM_DATA_DIR = Path.home() / ".sam_data"
REFLECTION_DIR = SAM_DATA_DIR / "reflection"
REFLECTION_DB_PATH = REFLECTION_DIR / "reflection.db"

REFLECTION_PROMPT = """Reflect briefly on how this task went.

Task: {task}

Steps taken and their observations:
{steps_text}

Outcome: {outcome}

Respond with ONLY this JSON:
{{"went_well": "...", "went_wrong": "...", "lesson": "...", "confidence": 0.0}}

"confidence" is how useful/clear this lesson is for next time (0-1).
If nothing went wrong, set went_wrong to "nothing notable". Keep each field
to one sentence.
"""


class ReflectionEngine:
    def __init__(self, settings=None):
        self.settings = settings
        REFLECTION_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(REFLECTION_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reflections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    task TEXT NOT NULL,
                    outcome TEXT,
                    went_well TEXT,
                    went_wrong TEXT,
                    lesson TEXT,
                    confidence REAL DEFAULT 0.5
                )
            """)
            conn.commit()

    def reflect(self, task: str, steps: List[Dict], outcome: str) -> Optional[Dict]:
        """
        Generates and stores a reflection. Returns the reflection dict, or
        None if the LLM call failed or settings are unavailable — nothing
        is stored in that case, and the caller should treat this as a
        no-op, not an error.
        """
        try:
            if self.settings is None:
                return None
            model = getattr(self.settings, "reflection_model", None) or self.settings.primary_model
            steps_text = "\n".join(
                f"Step {s.get('step')}: {s.get('action', s.get('description', ''))} -> {s.get('observation', '')}"
                for s in steps
            ) if steps else "No intermediate steps — task resolved directly."

            prompt = REFLECTION_PROMPT.format(
                task=task[:500], steps_text=steps_text[:1500], outcome=(outcome or "")[:300]
            )
            r = requests.post(
                f"{self.settings.ollama_host}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.3, "num_predict": 300},
                },
                timeout=30,
            )
            if r.status_code != 200:
                return None

            parsed = json.loads(r.json().get("response", "{}"))
            reflection = {
                "went_well": (parsed.get("went_well") or "").strip(),
                "went_wrong": (parsed.get("went_wrong") or "").strip(),
                "lesson": (parsed.get("lesson") or "").strip(),
                "confidence": max(0.0, min(1.0, float(parsed.get("confidence", 0.5) or 0.5))),
            }

            if not reflection["lesson"]:
                return None

            with sqlite3.connect(REFLECTION_DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO reflections (timestamp, task, outcome, went_well, went_wrong, lesson, confidence) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (datetime.now().isoformat(), task, outcome, reflection["went_well"],
                     reflection["went_wrong"], reflection["lesson"], reflection["confidence"])
                )
                conn.commit()

            logger.info(f"Reflection stored: {reflection['lesson'][:80]}")
            return reflection

        except Exception as e:
            logger.debug(f"Reflection skipped: {e}")
            return None

    def get_relevant_lessons(self, query: str = "", limit: int = 5, min_confidence: float = 0.4) -> str:
        """
        Simple recency + keyword overlap retrieval — no embedding
        dependency, keeps this module fully decoupled from memory/store.py.
        Returns a formatted string ready to inject into the Brain's prompt,
        or "" if nothing relevant.
        """
        try:
            with sqlite3.connect(REFLECTION_DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT task, lesson, confidence FROM reflections WHERE confidence >= ? "
                    "ORDER BY id DESC LIMIT ?",
                    (min_confidence, limit * 3)
                ).fetchall()

            if not rows:
                return ""

            if query:
                query_words = set(query.lower().split())
                scored = []
                for task, lesson, conf in rows:
                    overlap = len(query_words & set(task.lower().split()))
                    scored.append((overlap, conf, task, lesson))
                scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                rows = [(t, l, c) for _, c, t, l in scored[:limit]]
            else:
                rows = rows[:limit]

            if not rows:
                return ""

            return "LESSONS FROM PAST TASKS:\n" + "\n".join(
                f"• (from: {t[:60]}) {l}" for t, l, c in rows
            )
        except Exception as e:
            logger.debug(f"Lesson retrieval skipped: {e}")
            return ""

    @staticmethod
    def db_path() -> Path:
        return REFLECTION_DB_PATH
