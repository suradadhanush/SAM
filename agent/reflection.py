"""
AGENT — Reflection Engine (Phase 1, extended in Phase 1.5)

After a task finishes (success, failure, or max-steps-reached), generates
a short lesson: what went well, what didn't, and what to do differently
next time. Stored permanently in ~/.sam_data/reflection/ — never
overwritten or deleted, same spirit as Founder Mode.

Phase 1.5 additions (additive — nothing below removed or changed):
- mistakes / execution_metrics are computed directly from the step data
  (including any retry attempts from agent/verifier.py) rather than asked
  from the LLM — exact counts instead of a guess.
- Founder Mode bridge: when a reflection's confidence is high (>= 0.8 by
  default), and a FounderModeManager is passed in, the lesson is written
  into Founder Mode as a low-friction learned preference/decision
  (source="reflection") so SAM's taste profile can absorb what it learned
  from its own actions, not just what the user explicitly said. This is
  entirely opt-in per call — reflect() works exactly as before if no
  founder_mode is passed.
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

FOUNDER_BRIDGE_MIN_CONFIDENCE = 0.8

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
        self._migrate_schema()

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

    def _migrate_schema(self):
        """Phase 1.5: add mistakes/metrics columns to an existing table if
        they aren't there yet. Safe to run every startup."""
        with sqlite3.connect(REFLECTION_DB_PATH) as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(reflections)").fetchall()}
            for col_name, col_def in [
                ("mistakes_json", "TEXT DEFAULT '[]'"),
                ("execution_metrics_json", "TEXT DEFAULT '{}'"),
            ]:
                if col_name not in existing:
                    try:
                        conn.execute(f"ALTER TABLE reflections ADD COLUMN {col_name} {col_def}")
                        logger.info(f"Migrated reflections: added {col_name}")
                    except sqlite3.OperationalError as e:
                        logger.debug(f"Migration skip reflections.{col_name}: {e}")
            conn.commit()

    def reflect(self, task: str, steps: List[Dict], outcome: str,
                founder_mode=None) -> Optional[Dict]:
        """
        Generates and stores a reflection. Returns the reflection dict, or
        None if the LLM call failed or settings are unavailable — nothing
        is stored in that case, and the caller should treat this as a
        no-op, not an error.

        If founder_mode (a FounderModeManager) is passed and the resulting
        confidence is high, the lesson is also bridged into Founder Mode.
        This is entirely optional — omit founder_mode to keep the old
        behaviour exactly as it was.
        """
        mistakes, metrics = self._compute_mistakes_and_metrics(steps)

        try:
            if self.settings is None:
                return None
            model = getattr(self.settings, "reflection_model", None) or self.settings.primary_model
            steps_text = self._format_steps_for_prompt(steps)

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
                "mistakes": mistakes,
                "execution_metrics": metrics,
            }

            if not reflection["lesson"]:
                return None

            with sqlite3.connect(REFLECTION_DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO reflections (timestamp, task, outcome, went_well, went_wrong, lesson, "
                    "confidence, mistakes_json, execution_metrics_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (datetime.now().isoformat(), task, outcome, reflection["went_well"],
                     reflection["went_wrong"], reflection["lesson"], reflection["confidence"],
                     json.dumps(mistakes), json.dumps(metrics))
                )
                conn.commit()

            logger.info(f"Reflection stored: {reflection['lesson'][:80]}")

            if founder_mode is not None and reflection["confidence"] >= FOUNDER_BRIDGE_MIN_CONFIDENCE:
                self._bridge_to_founder_mode(task, reflection, founder_mode)

            return reflection

        except Exception as e:
            logger.debug(f"Reflection skipped: {e}")
            return None

    def _bridge_to_founder_mode(self, task: str, reflection: Dict, founder_mode):
        """High-confidence lessons get written into Founder Mode so SAM's
        taste profile absorbs what it learned from its own actions, not
        just what the user explicitly said. Wrapped so a bridge failure
        never affects the reflection that was already stored above."""
        try:
            founder_mode.capture_decision(
                decision=f"Lesson from task '{task[:80]}': {reflection['lesson']}",
                reasoning=reflection.get("went_well") or "Derived from a high-confidence reflection.",
                category="reflection",
                confidence=reflection["confidence"],
                evidence=[reflection["lesson"]],
                source="reflection",
            )
            logger.info("Reflection bridged into Founder Mode")
        except Exception as e:
            logger.debug(f"Founder Mode bridge skipped: {e}")

    @staticmethod
    def _compute_mistakes_and_metrics(steps: List[Dict]):
        """Computed from real step/attempt data, not asked from the LLM —
        exact counts instead of a guess. Works whether or not steps carry
        the Phase 1.5 'attempts' field (older callers just get empty
        mistakes/zeroed retry counts, nothing breaks)."""
        mistakes = []
        total_attempts = 0
        retry_count = 0
        failed_steps = 0

        for s in steps:
            attempts = s.get("attempts") or []
            total_attempts += len(attempts) if attempts else 1
            for a in attempts:
                if a.get("attempt") == 2:
                    retry_count += 1
                if not a.get("success", True):
                    mistakes.append({
                        "step": s.get("step"),
                        "action": s.get("action"),
                        "error": (a.get("errors") or ["unknown"])[0] if a.get("errors") else "unknown",
                    })
            if attempts and not attempts[-1].get("success", True):
                failed_steps += 1

        metrics = {
            "step_count": len(steps),
            "total_attempts": total_attempts,
            "retry_count": retry_count,
            "failed_steps": failed_steps,
        }
        return mistakes, metrics

    @staticmethod
    def _format_steps_for_prompt(steps: List[Dict]) -> str:
        if not steps:
            return "No intermediate steps — task resolved directly."
        lines = []
        for s in steps:
            action_desc = s.get("action", s.get("description", ""))
            obs = s.get("observation", "")
            lines.append(f"Step {s.get('step')}: {action_desc} -> {obs}")
        return "\n".join(lines)

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
