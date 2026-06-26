"""
Session — Manages a single interaction with SAM.
Holds context, history, and handles post-session memory saving.
"""

import logging
import json
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

logger = logging.getLogger("SAM.Session")


@dataclass
class Session:
    user_input: str
    identity: Dict[str, Any]
    memories: List[Dict]
    founder_context: str
    settings: Any
    history: List[Dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def save(self, user_input: str, response):
        """
        Extract and save memory from this interaction.
        Skipped entirely in incognito mode.
        """
        if self.settings.incognito:
            logger.info("Incognito mode — session not saved")
            return

        try:
            from memory.store import MemoryStore
            store = MemoryStore(self.settings)

            # Save episodic event
            store.save_episode(
                user_input=user_input,
                response=response.text,
                action=response.action,
                timestamp=self.created_at
            )

            # Extract and save semantic memory
            store.extract_and_save(
                user_input=user_input,
                response=response.text
            )

            logger.info("Session saved to memory")

        except Exception as e:
            logger.error(f"Session save error: {e}", exc_info=True)
