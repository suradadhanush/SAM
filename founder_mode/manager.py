"""
FOUNDER MODE — The Killer Feature
Stores decisions, rejections, and reasoning permanently.
Builds a taste profile over time.
Every session starts with this context loaded.
No competitor has this feature.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger("SAM.FounderMode")

FM_DB_PATH = Path(__file__).parent / "store" / "founder_mode.db"
FM_EXPORT_PATH = Path(__file__).parent / "export"


class FounderModeManager:
    def __init__(self):
        FM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
        logger.info("Founder Mode DB initialised")

    # ─── Capture ──────────────────────────────────────────────────────────

    def capture_decision(self, decision: str, reasoning: str,
                         category: str = "general",
                         alternatives_rejected: str = None,
                         context: str = None):
        """Store a product/technical/design decision with full reasoning."""
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO decisions
                   (timestamp, type, category, decision, reasoning, alternatives_rejected, context)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    datetime.now().isoformat(),
                    "decision",
                    category,
                    decision,
                    reasoning,
                    alternatives_rejected,
                    context
                )
            )
            conn.commit()
        logger.info(f"Decision captured: {decision[:60]}")

    def capture_rejection(self, what: str, why: str, category: str = "general"):
        """Store what was rejected and the full reasoning why."""
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO rejections (timestamp, what_was_rejected, why, category) VALUES (?,?,?,?)",
                (datetime.now().isoformat(), what, why, category)
            )
            conn.commit()
        logger.info(f"Rejection captured: {what[:60]}")

    def update_taste(self, domain: str, preference: str, strength: str = "strong"):
        """Update the taste profile for a domain (design, tech, product, etc.)"""
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO taste_profile (domain, preference, strength, updated_at)
                   VALUES (?,?,?,?)""",
                (domain, preference, strength, datetime.now().isoformat())
            )
            conn.commit()
        logger.info(f"Taste updated [{domain}]: {preference[:60]}")

    # ─── Context Building ──────────────────────────────────────────────────

    def get_context(self) -> str:
        """
        Build the Founder Mode context string injected at every session start.
        Returns a compact summary of decisions, taste, and rejections.
        """
        try:
            sections = []

            # Recent decisions
            decisions = self._get_recent_decisions(limit=10)
            if decisions:
                d_text = "\n".join(
                    f"• [{d['category']}] {d['decision']} — because: {d['reasoning']}"
                    for d in decisions
                )
                sections.append(f"DECISIONS MADE:\n{d_text}")

            # Taste profile
            taste = self._get_taste_profile()
            if taste:
                t_text = "\n".join(
                    f"• [{t['domain']}] {t['preference']}"
                    for t in taste
                )
                sections.append(f"TASTE PROFILE:\n{t_text}")

            # Recent rejections
            rejections = self._get_recent_rejections(limit=5)
            if rejections:
                r_text = "\n".join(
                    f"• REJECTED [{r['category']}]: {r['what']} — because: {r['why']}"
                    for r in rejections
                )
                sections.append(f"WHAT TO AVOID (rejections):\n{r_text}")

            if not sections:
                return ""

            return "\n\n".join(sections)

        except Exception as e:
            logger.error(f"Founder Mode context error: {e}")
            return ""

    def capture_if_relevant(self, user_input: str, response):
        """
        Auto-detect if the conversation contains a decision or rejection
        and capture it automatically.
        """
        text = user_input.lower()
        rejection_signals = [
            "i don't like", "that's wrong", "no not like that",
            "reject", "not this", "i prefer", "change it to",
            "that's bad", "terrible", "avoid"
        ]
        decision_signals = [
            "i decided", "we're going with", "final decision",
            "lock it in", "confirmed", "use this approach",
            "i chose", "going with"
        ]

        if any(signal in text for signal in rejection_signals):
            self.capture_rejection(
                what=user_input[:200],
                why="Auto-captured from user feedback",
                category="auto"
            )

        elif any(signal in text for signal in decision_signals):
            self.capture_decision(
                decision=user_input[:200],
                reasoning="Auto-captured from user statement",
                category="auto"
            )

    # ─── Queries ──────────────────────────────────────────────────────────

    def _get_recent_decisions(self, limit: int = 10) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT category, decision, reasoning FROM decisions ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"category": r[0], "decision": r[1], "reasoning": r[2]} for r in rows]

    def _get_taste_profile(self) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT domain, preference FROM taste_profile ORDER BY updated_at DESC"
            ).fetchall()
        return [{"domain": r[0], "preference": r[1]} for r in rows]

    def _get_recent_rejections(self, limit: int = 5) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT category, what_was_rejected, why FROM rejections ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [{"category": r[0], "what": r[1], "why": r[2]} for r in rows]

    # ─── Export ───────────────────────────────────────────────────────────

    def export(self) -> str:
        """Export full decision log as JSON."""
        export_path = FM_EXPORT_PATH / f"founder_mode_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        data = {
            "exported_at": datetime.now().isoformat(),
            "decisions": self._get_all_decisions(),
            "taste_profile": self._get_taste_profile(),
            "rejections": self._get_all_rejections()
        }

        with open(export_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Founder Mode exported to {export_path}")
        return str(export_path)

    def _get_all_decisions(self) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT timestamp, type, category, decision, reasoning, alternatives_rejected FROM decisions ORDER BY id"
            ).fetchall()
        return [
            {"timestamp": r[0], "type": r[1], "category": r[2],
             "decision": r[3], "reasoning": r[4], "alternatives_rejected": r[5]}
            for r in rows
        ]

    def _get_all_rejections(self) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                "SELECT timestamp, category, what_was_rejected, why FROM rejections ORDER BY id"
            ).fetchall()
        return [
            {"timestamp": r[0], "category": r[1], "what": r[2], "why": r[3]}
            for r in rows
        ]
