"""
FOUNDER MODE v2 — The Killer Feature
Stored in ~/.sam_data/founder_mode/
Survives SAM reinstalls completely.

v2 additions (all additive — no existing behaviour removed):
- Evidence: every captured decision/rejection/preference keeps the actual
  user quote(s) that justified it, not just a label.
- Confidence: every entry has a 0.0-1.0 confidence score. LLM-auto-captured
  entries start lower and can be reinforced (repeated) or superseded
  (contradicted) over time. Manually added entries (via sam_cli) default
  to high confidence since the user typed them directly.
- Smarter auto-capture: instead of naive keyword matching with a placeholder
  reasoning string, a cheap keyword pre-filter gates an LLM classification
  call (founder_mode/classifier.py) that extracts the real reasoning.
  If the LLM classifier is unavailable, it falls back to the old
  lightweight heuristic capture rather than losing the signal entirely.
- Preference conflict resolution: a new preference in the same domain that
  contradicts an existing active one supersedes it (kept in DB, excluded
  from live context). A repeated/reinforcing preference bumps confidence
  and appends evidence instead of creating a duplicate row.

Backward compatible:
- FounderModeManager() with no args still works exactly as before.
- capture_decision(decision, reasoning, category) positional calls still work.
- capture_rejection(what, why, category) positional calls still work.
- Existing DBs are migrated in-place (ALTER TABLE) — nothing is dropped.
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

CONFIDENCE_REINFORCE_STEP = 0.15
CONFIDENCE_MAX = 0.95
DEFAULT_MANUAL_CONFIDENCE = 0.9
DEFAULT_AUTO_CONFIDENCE = 0.5

# Broad, high-recall pre-filter. False positives are cheap (one extra LLM
# call, gated behind founder_mode_llm_capture); false negatives lose data.
_TRIGGER_PHRASES = [
    "i don't like", "i dont like", "that's wrong", "thats wrong", "reject",
    "not this", "i prefer", "avoid", "terrible", "hate", "never do",
    "always do", "instead of", "i decided", "going with", "lock it in",
    "confirmed", "i chose", "let's go with", "lets go with", "sticking with",
    "switching to", "i want", "make it", "i love", "final answer",
    "from now on", "don't suggest", "dont suggest",
]


class FounderModeManager:
    def __init__(self, settings=None):
        self.settings = settings
        FM_DIR.mkdir(parents=True, exist_ok=True)
        FM_EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_schema()

    # ─── Schema ─────────────────────────────────────────────────────────

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

    def _migrate_schema(self):
        """Add v2 columns to existing tables if they aren't there yet.
        Safe to run every startup — checks before altering."""
        migrations = {
            "decisions": [
                ("confidence", "REAL DEFAULT 0.9"),
                ("evidence_json", "TEXT DEFAULT '[]'"),
                ("status", "TEXT DEFAULT 'active'"),
                ("superseded_by", "INTEGER"),
                ("source", "TEXT DEFAULT 'manual'"),
            ],
            "rejections": [
                ("confidence", "REAL DEFAULT 0.9"),
                ("evidence_json", "TEXT DEFAULT '[]'"),
                ("status", "TEXT DEFAULT 'active'"),
                ("source", "TEXT DEFAULT 'manual'"),
            ],
            "taste_profile": [
                ("confidence", "REAL DEFAULT 0.6"),
                ("evidence_json", "TEXT DEFAULT '[]'"),
                ("status", "TEXT DEFAULT 'active'"),
                ("superseded_by", "INTEGER"),
                ("source", "TEXT DEFAULT 'manual'"),
            ],
        }
        with sqlite3.connect(FM_DB_PATH) as conn:
            for table, columns in migrations.items():
                existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                for col_name, col_def in columns:
                    if col_name not in existing:
                        try:
                            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                            logger.info(f"Migrated {table}: added {col_name}")
                        except sqlite3.OperationalError as e:
                            logger.debug(f"Migration skip {table}.{col_name}: {e}")
            conn.commit()

    # ─── Capture (manual — used by sam_cli.py, unchanged call signatures) ──

    def capture_decision(self, decision: str, reasoning: str,
                          category: str = "general",
                          alternatives_rejected: str = None,
                          context: str = None,
                          confidence: float = DEFAULT_MANUAL_CONFIDENCE,
                          evidence: Optional[List[str]] = None,
                          source: str = "manual"):
        evidence_json = self._build_evidence_json(evidence or [decision])
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO decisions
                   (timestamp, type, category, decision, reasoning, alternatives_rejected,
                    context, confidence, evidence_json, status, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), "decision", category,
                 decision, reasoning, alternatives_rejected, context,
                 confidence, evidence_json, "active", source)
            )
            conn.commit()
        logger.info(f"Decision captured [{source}, conf={confidence:.2f}]: {decision[:60]}")

    def capture_rejection(self, what: str, why: str, category: str = "general",
                           confidence: float = DEFAULT_MANUAL_CONFIDENCE,
                           evidence: Optional[List[str]] = None,
                           source: str = "manual"):
        evidence_json = self._build_evidence_json(evidence or [what])
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(
                """INSERT INTO rejections
                   (timestamp, what_was_rejected, why, category, confidence, evidence_json, status, source)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (datetime.now().isoformat(), what, why, category,
                 confidence, evidence_json, "active", source)
            )
            conn.commit()
        logger.info(f"Rejection captured [{source}, conf={confidence:.2f}]: {what[:60]}")

    def update_taste(self, domain: str, preference: str, strength: str = "strong",
                      confidence: float = DEFAULT_MANUAL_CONFIDENCE,
                      evidence: Optional[List[str]] = None,
                      source: str = "manual"):
        """
        Reinforces an existing matching preference in this domain (bumps
        confidence, appends evidence) rather than duplicating it.
        Supersedes a contradicting preference in the same domain rather
        than leaving stale/conflicting entries in the live context.
        """
        evidence_list = evidence or [preference]
        norm_new = preference.strip().lower()

        with sqlite3.connect(FM_DB_PATH) as conn:
            existing = conn.execute(
                """SELECT id, preference, confidence, evidence_json FROM taste_profile
                   WHERE domain = ? AND status = 'active' ORDER BY id DESC""",
                (domain,)
            ).fetchall()

            match = None
            for row_id, pref, conf, ev_json in existing:
                if pref.strip().lower() == norm_new:
                    match = (row_id, conf, ev_json)
                    break

            if match:
                row_id, old_conf, old_ev_json = match
                new_conf = min(CONFIDENCE_MAX, (old_conf or 0.6) + CONFIDENCE_REINFORCE_STEP)
                merged_evidence = self._append_evidence_json(old_ev_json, evidence_list)
                conn.execute(
                    "UPDATE taste_profile SET confidence = ?, evidence_json = ?, updated_at = ? WHERE id = ?",
                    (new_conf, merged_evidence, datetime.now().isoformat(), row_id)
                )
                conn.commit()
                logger.info(f"Taste reinforced [{domain}] {preference[:50]} -> conf={new_conf:.2f}")
                return

            # No exact match — insert new, then supersede any differing active entries
            evidence_json = self._build_evidence_json(evidence_list)
            cur = conn.execute(
                "INSERT INTO taste_profile (domain, preference, strength, updated_at, confidence, evidence_json, status, source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (domain, preference, strength, datetime.now().isoformat(),
                 confidence, evidence_json, "active", source)
            )
            new_id = cur.lastrowid

            if existing:
                stale_ids = [row_id for row_id, _, _, _ in existing]
                conn.executemany(
                    "UPDATE taste_profile SET status = 'superseded', superseded_by = ? WHERE id = ?",
                    [(new_id, sid) for sid in stale_ids]
                )
                logger.info(f"Taste superseded [{domain}]: {len(stale_ids)} old entr(y/ies) -> new #{new_id}")

            conn.commit()

    # ─── Auto-capture (called from main.py after every turn) ───────────────

    def capture_if_relevant(self, user_input: str, response):
        """
        Called after every SAM turn. Cheap pre-filter first (no cost if no
        match). If matched and an LLM classifier is available, extracts a
        real structured signal with reasoning + confidence. Falls back to
        lightweight heuristic capture only if the classifier itself is
        unavailable — never on a genuine "none" result.
        """
        text_lower = user_input.lower()
        if not any(phrase in text_lower for phrase in _TRIGGER_PHRASES):
            return

        use_llm = (
            self.settings is not None
            and getattr(self.settings, "founder_mode_llm_capture", True)
            and not getattr(self.settings, "incognito", False)
        )

        if use_llm:
            try:
                from founder_mode.classifier import classify, UNAVAILABLE
                response_text = getattr(response, "text", "") if response else ""
                result = classify(user_input, response_text, self.settings)

                if result["type"] == UNAVAILABLE:
                    self._heuristic_fallback_capture(user_input, text_lower)
                    return

                if result["type"] == "none":
                    return  # Trust the classifier's negative — do nothing.

                if result["type"] == "task_request":
                    # Bug fixed here: this used to fall through and get
                    # captured as a "decision" (technically defensible
                    # under the old prompt, wrong in effect) — a one-time
                    # action instruction ("open youtube and play X") would
                    # then get injected into EVERY future prompt forever
                    # via get_context(), making a stale task look like it
                    # was "resumed" on a totally unrelated later question.
                    # Trust the classifier's task_request call — do nothing.
                    # The task itself is handled by the normal action-
                    # execution pipeline in main.py, not by Founder Mode.
                    return

                if result["type"] == "decision":
                    self.capture_decision(
                        decision=result["statement"], reasoning=result["reasoning"],
                        category=result["category"], confidence=result["confidence"],
                        evidence=[user_input], source="llm_auto"
                    )
                elif result["type"] == "rejection":
                    self.capture_rejection(
                        what=result["statement"], why=result["reasoning"],
                        category=result["category"], confidence=result["confidence"],
                        evidence=[user_input], source="llm_auto"
                    )
                elif result["type"] == "preference":
                    self.update_taste(
                        domain=result["domain"], preference=result["statement"],
                        confidence=result["confidence"], evidence=[user_input],
                        source="llm_auto"
                    )
                return
            except Exception as e:
                logger.debug(f"Founder Mode LLM capture failed, falling back: {e}")

        self._heuristic_fallback_capture(user_input, text_lower)

    def _heuristic_fallback_capture(self, user_input: str, text_lower: str):
        """Old behaviour, kept as a safety net when the LLM classifier
        can't run (Ollama down, timeout, etc). Honest placeholder instead
        of a fake reasoning string."""
        placeholder = "No reasoning captured — LLM classifier unavailable at time of capture."
        reject_signals = ["i don't like", "i dont like", "that's wrong", "thats wrong",
                           "reject", "not this", "i prefer", "avoid", "terrible", "hate"]
        decide_signals = ["i decided", "going with", "lock it in", "confirmed", "i chose"]

        if any(s in text_lower for s in reject_signals):
            self.capture_rejection(what=user_input[:200], why=placeholder,
                                    category="auto", confidence=0.3, source="heuristic")
        elif any(s in text_lower for s in decide_signals):
            self.capture_decision(decision=user_input[:200], reasoning=placeholder,
                                   category="auto", confidence=0.3, source="heuristic")

    # ─── Context assembly (used by core/brain.py via session.founder_context) ──

    def get_context(self) -> str:
        try:
            min_conf = 0.0
            if self.settings is not None:
                min_conf = getattr(self.settings, "founder_mode_min_confidence_to_show", 0.3)

            sections = []
            decisions = self._get_recent_decisions(10, min_conf)
            if decisions:
                d_text = "\n".join(
                    f"• [{d['category']}] {d['decision']} — because: {d['reasoning']} {self._conf_label(d['confidence'])}"
                    for d in decisions
                )
                sections.append(f"DECISIONS MADE:\n{d_text}")

            taste = self._get_taste_profile(min_conf)
            if taste:
                t_text = "\n".join(
                    f"• [{t['domain']}] {t['preference']} {self._conf_label(t['confidence'])}"
                    for t in taste
                )
                sections.append(f"TASTE PROFILE:\n{t_text}")

            rejections = self._get_recent_rejections(5, min_conf)
            if rejections:
                r_text = "\n".join(
                    f"• REJECTED [{r['category']}]: {r['what']} — because: {r['why']} {self._conf_label(r['confidence'])}"
                    for r in rejections
                )
                sections.append(f"WHAT TO AVOID:\n{r_text}")

            return "\n\n".join(sections)
        except Exception as e:
            logger.error(f"Founder Mode context error: {e}")
            return ""

    @staticmethod
    def _conf_label(confidence) -> str:
        try:
            c = float(confidence)
        except (TypeError, ValueError):
            return ""
        if c >= 0.8:
            return ""  # high confidence — no need to flag it in the prompt
        elif c >= 0.5:
            return "(moderate confidence)"
        else:
            return "(uncertain — treat as a guess)"

    def _get_recent_decisions(self, limit: int, min_confidence: float = 0.0) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                """SELECT category, decision, reasoning, confidence FROM decisions
                   WHERE (status IS NULL OR status = 'active') AND (confidence IS NULL OR confidence >= ?)
                   ORDER BY confidence DESC, id DESC LIMIT ?""",
                (min_confidence, limit)
            ).fetchall()
        return [{"category": r[0], "decision": r[1], "reasoning": r[2], "confidence": r[3]} for r in rows]

    def _get_taste_profile(self, min_confidence: float = 0.0) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                """SELECT domain, preference, confidence FROM taste_profile
                   WHERE (status IS NULL OR status = 'active') AND (confidence IS NULL OR confidence >= ?)
                   ORDER BY confidence DESC, updated_at DESC""",
                (min_confidence,)
            ).fetchall()
        return [{"domain": r[0], "preference": r[1], "confidence": r[2]} for r in rows]

    def _get_recent_rejections(self, limit: int, min_confidence: float = 0.0) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(
                """SELECT category, what_was_rejected, why, confidence FROM rejections
                   WHERE (status IS NULL OR status = 'active') AND (confidence IS NULL OR confidence >= ?)
                   ORDER BY confidence DESC, id DESC LIMIT ?""",
                (min_confidence, limit)
            ).fetchall()
        return [{"category": r[0], "what": r[1], "why": r[2], "confidence": r[3]} for r in rows]

    # ─── Review / confirm loop (sam_cli.py "founder-review") ────────────────

    def list_llm_captures(self, max_confidence: float = 0.95, limit: int = 20) -> List[Dict]:
        """Entries auto-captured by the LLM that haven't been confirmed yet."""
        out = []
        with sqlite3.connect(FM_DB_PATH) as conn:
            for table, label_col in [("decisions", "decision"), ("rejections", "what_was_rejected"),
                                      ("taste_profile", "preference")]:
                rows = conn.execute(
                    f"""SELECT id, {label_col}, confidence FROM {table}
                        WHERE source = 'llm_auto' AND status = 'active' AND confidence < ?
                        ORDER BY id DESC LIMIT ?""",
                    (max_confidence, limit)
                ).fetchall()
                for row_id, label, conf in rows:
                    out.append({"table": table, "id": row_id, "label": label, "confidence": conf})
        return out

    def confirm_capture(self, table: str, row_id: int):
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(f"UPDATE {table} SET confidence = 1.0 WHERE id = ?", (row_id,))
            conn.commit()

    def reject_capture(self, table: str, row_id: int):
        with sqlite3.connect(FM_DB_PATH) as conn:
            conn.execute(f"UPDATE {table} SET status = 'rejected_by_user' WHERE id = ?", (row_id,))
            conn.commit()

    # ─── Evidence helpers ───────────────────────────────────────────────────

    @staticmethod
    def _build_evidence_json(quotes: List[str]) -> str:
        now = datetime.now().isoformat()
        entries = [{"ts": now, "quote": q[:300]} for q in quotes if q]
        return json.dumps(entries)

    @staticmethod
    def _append_evidence_json(existing_json: Optional[str], new_quotes: List[str]) -> str:
        try:
            entries = json.loads(existing_json) if existing_json else []
        except (json.JSONDecodeError, TypeError):
            entries = []
        now = datetime.now().isoformat()
        entries.extend({"ts": now, "quote": q[:300]} for q in new_quotes if q)
        return json.dumps(entries[-20:])  # cap growth — keep most recent 20

    # ─── Export ──────────────────────────────────────────────────────────

    def export(self) -> str:
        export_path = FM_EXPORT_PATH / f"founder_mode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        data = {
            "exported_at": datetime.now().isoformat(),
            "decisions": self._get_all("decisions"),
            "taste_profile": self._get_all("taste_profile"),
            "rejections": self._get_all("rejections")
        }
        with open(export_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported to {export_path}")
        return str(export_path)

    def _get_all(self, table: str) -> List[Dict]:
        with sqlite3.connect(FM_DB_PATH) as conn:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            # PRAGMA table_info columns are (cid, name, type, notnull, dflt_value, pk) —
            # index 1 is the column name. (Pre-existing bug fixed here: this previously
            # read index 0, the cid, which silently broke export()'s dict keys.)
            cols = [d[1] for d in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        return [dict(zip(cols, r)) for r in rows]

    @staticmethod
    def db_path() -> Path:
        return FM_DB_PATH
