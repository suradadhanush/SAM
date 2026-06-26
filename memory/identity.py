"""
Memory — Identity
Stores and loads the user's core identity profile.
Injected at every session start.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("SAM.Identity")

IDENTITY_PATH = Path(__file__).parent / "store" / "identity.json"

DEFAULT_IDENTITY = {
    "name": "Dhanush",
    "assistant_name": "SAM",
    "about": "First-year B.Tech CSE student at NSRIT Visakhapatnam. Building SAM.",
    "projects": [
        "SAM — local AI assistant",
        "AnonCampus — NLP grievance platform",
        "NSRIT eSports Arena — tournament platform"
    ],
    "preferences": {
        "communication_style": "direct, no fluff, founder energy",
        "technical_depth": "high — understands systems, products, architecture",
        "response_length": "concise for voice, detailed when asked"
    },
    "context": "Building SAM as both a personal tool and a consumer product."
}


class Identity:
    def __init__(self):
        IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not IDENTITY_PATH.exists():
            self._save(DEFAULT_IDENTITY)
            logger.info("Default identity created")

    def load(self) -> dict:
        try:
            with open(IDENTITY_PATH) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Identity load error: {e}")
            return DEFAULT_IDENTITY

    def update(self, updates: dict):
        identity = self.load()
        identity.update(updates)
        self._save(identity)
        logger.info(f"Identity updated: {list(updates.keys())}")

    def _save(self, data: dict):
        with open(IDENTITY_PATH, "w") as f:
            json.dump(data, f, indent=2)
