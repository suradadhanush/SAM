"""
Memory — Identity
Stored in ~/.sam_data/identity.json
Survives SAM reinstalls, clones, and folder deletions.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("SAM.Identity")

SAM_DATA_DIR = Path.home() / ".sam_data"
IDENTITY_PATH = SAM_DATA_DIR / "identity.json"

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
        "technical_depth": "high",
        "response_length": "concise for voice, detailed when asked"
    },
    "context": "Building SAM as both a personal tool and a future consumer product."
}


class Identity:
    def __init__(self):
        SAM_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not IDENTITY_PATH.exists():
            self._save(DEFAULT_IDENTITY)
            logger.info(f"Identity created at {IDENTITY_PATH}")
        else:
            logger.info(f"Identity loaded from {IDENTITY_PATH}")

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

    @staticmethod
    def path() -> Path:
        return IDENTITY_PATH
