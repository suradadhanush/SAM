"""
FOUNDER MODE — The Killer Feature
Stored in ~/.sam_data/founder_mode/
Survives SAM reinstalls completely.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger("SAM.FounderMode")

SAM_DATA_DIR = Path.home() / ".sam_data"
FM_DIR = SAM_DATA_DIR / "founder_mode"
FM_DB_PATH = FM_DIR / "founder_mode.db"
FM_EXPORT_PATH = FM_DIR / "export"


class FounderModeManager:
    def __init__(self):
        FM_DIR.mkdir(parents=True, exist_ok=True)
        FM_EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    category TEXT,
                    decision TEXT NOT NULL,
                    reasoning TEXT,
                    alternatives_rejected TEXT,
                    context TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS taste_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    preference TEXT NOT NULL,
                    strength TEXT DEFAULT 'strong',
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rejections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    what_was_rejected TEXT NOT NULL,
                    why TEXT NOT NULL,
                    category TEXT
                )
            """)
            conn.commit()
        logger.info(f"Founder Mode DB at {FM_DB_PATH}")

    def capture_decision(self, decision: str, reasoning: str,
                         category: str = "general",
                         alternatives_rejected: str = None,
                         context: str = None):
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO decisions
                   (timestamp, type, category, decision, reasoning, alternatives_rejected, context)
                   VALUES (?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), "decision", category,
                 decision, reasoning, alternatives_rejected, context)
            )
            conn.commit()
        logger.info(f"Decision captured: {decision[:60]}")

    def capture_rejection(self, what: str, why: str, category: str = "general"):
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO rejections (timestamp, what_was_rejected, why, category) VALUES (?,?,?,?)",
                (datetime.now().isoformat(), what, why, category)
            )
            conn.commit()
        logger.info(f"Rejection captured: {what[:60]}")

    def update_taste(self, domain: str, preference: str, strength: str = "strong"):
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO taste_profile (domain, preference, strength, updated_at) VALUES (?,?,?,?)",
                (domain, preference, strength, datetime.now().isoformat())
            )
            conn.commit()

    def get_context(self) -> str:
        try:
            sections = []
            decisions = self._get_recent_decisions(10)
            if decisions:
                d_text = "\n".join(
                    f"• [{d['category']}] {d['decision']} — because: {d['reasoning']}"
                    for d in decisions
                )
                sections.append(f"DECISIONS MADE:\n{d_text}")

            taste = self._get_taste_profile()
            if taste:
                t_text = "\n".join(f"• [{t['domain']}] {t['preference']}" for t in taste)
                sections.append(f"TASTE PROFILE:\n{t_text}")

            rejections = self._get_recent_rejections(5)
            if rejections:
                r_text = "\n".join(
                    f"• REJECTED [{r['category']}]: {r['what']} — because: {r['why']}"
                    for r in rejections
                )
                sections.append(f"WHAT TO AVOID:\n{r_text}")

            return "\n\n".join(sections)
        except Exception as e:
            logger.error(f"Founder Mode context error: {e}")
            return ""

    def capture_if_relevant(self, user_input: str, response):
        text = user_input.lower()
        if any(s in text for s in ["i don't like", "that's wrong", "reject", "not this", "i prefer", "avoid", "terrible"]):
            self.capture_rejection(what=user_input[:200], why="Auto-captured", category="auto")
        elif any(s in text for s in ["i decided", "going with", "lock it in", "confirmed", "i chose"]):
            self.capture_decision(decision=user_input[:200], reasoning="Auto-captured", category="auto")

    def _get_recent_decisions(self, limit: int) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT category, decision, reasoning FROM decisions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"category": r[0], "decision": r[1], "reasoning": r[2]} for r in rows]

    def _get_taste_profile(self) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT domain, preference FROM taste_profile ORDER BY updated_at DESC"
            ).fetchall()
        return [{"domain": r[0], "preference": r[1]} for r in rows]

    def _get_recent_rejections(self, limit: int) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT category, what_was_rejected, why FROM rejections ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"category": r[0], "what": r[1], "why": r[2]} for r in rows]

    def export(self) -> str:
        export_path = FM_EXPORT_PATH / f"founder_mode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        data = {
            "exported_at": datetime.now().isoformat(),
            "decisions": self._get_all("decisions"),
            "taste_profile": self._get_taste_profile(),
            "rejections": self._get_all("rejections")
        }
        with open(export_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported to {export_path}")
        return str(export_path)

    def _get_all(self, table: str) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            cols = [d[0] for d in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return [dict(zip(cols, r)) for r in rows]

    @staticmethod
    def db_path() -> Path:
        return FM_DB_PATH
