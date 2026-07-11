"""
ECOSYSTEM — Device Registry (Phase 2, Telegram bridge)

Stores which remote devices (currently: Telegram chats) are trusted to send
SAM commands, and manages the one-time pairing token lifecycle (QR code ->
scan -> /start <token> -> trusted).

Stored in ~/.sam_data/ecosystem/devices.db — separate from Founder Mode and
episodic memory, since this is device/identity metadata, not AI data. This
mirrors the "Local Data Separation" principle from the PDR: account/device
metadata and AI data (conversations, memory, Founder Mode) are always kept
apart, even though both happen to live locally right now.

IMPORTANT — this is an internet-relay bridge, not the local-WiFi Phase 2
ecosystem originally scoped. See docs/PHASE_2_TELEGRAM_BRIDGE.md for the full
explanation of that trade-off. Real same-WiFi device pairing (zero third
party involved) is still the long-term Phase 2 plan once a native Android
app exists — this registry's schema was kept generic enough (device_id,
device_name, channel) that a future WiFi-paired device can be added as a
row here too, not a separate system.
"""

import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger("SAM.Ecosystem.DeviceRegistry")

SAM_DATA_DIR = Path.home() / ".sam_data"
ECOSYSTEM_DIR = SAM_DATA_DIR / "ecosystem"
DEVICES_DB_PATH = ECOSYSTEM_DIR / "devices.db"

PAIRING_TOKEN_TTL_MINUTES = 10


class DeviceRegistry:
    def __init__(self):
        ECOSYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL DEFAULT 'telegram',
                    external_id TEXT NOT NULL,
                    device_name TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    pairing_token TEXT,
                    token_expires_at TEXT,
                    paired_at TEXT,
                    last_active TEXT,
                    UNIQUE(channel, external_id)
                )
            """)
            conn.commit()
        logger.info(f"Device registry DB at {DEVICES_DB_PATH}")

    # ─── Pairing ─────────────────────────────────────────────────────────

    def create_pairing_token(self, channel: str = "telegram") -> str:
        """Generates a fresh one-time token for a new pairing attempt. Not
        tied to a device yet — that happens when the token is redeemed."""
        token = secrets.token_urlsafe(16)
        expires_at = (datetime.now() + timedelta(minutes=PAIRING_TOKEN_TTL_MINUTES)).isoformat()
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            conn.execute(
                "INSERT INTO devices (channel, external_id, status, pairing_token, token_expires_at) "
                "VALUES (?,?,?,?,?)",
                (channel, f"__pending_{token}", "awaiting_redemption", token, expires_at)
            )
            conn.commit()
        logger.info(f"Pairing token created, expires {expires_at}")
        return token

    def redeem_token(self, token: str, external_id: str, device_name: str = "Phone",
                      channel: str = "telegram") -> bool:
        """
        Called when someone sends /start <token> to the bot. Validates the
        token (exists, not expired, not already used), and if valid,
        promotes that external_id (Telegram chat_id) to a trusted device.
        Returns True on success, False on invalid/expired/reused token.
        """
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            row = conn.execute(
                "SELECT id, token_expires_at FROM devices WHERE pairing_token = ? "
                "AND status = 'awaiting_redemption' AND channel = ?",
                (token, channel)
            ).fetchone()

            if not row:
                logger.warning("Pairing token not found or already used")
                return False

            row_id, expires_at = row
            if datetime.now() > datetime.fromisoformat(expires_at):
                logger.warning("Pairing token expired")
                conn.execute("DELETE FROM devices WHERE id = ?", (row_id,))
                conn.commit()
                return False

            # Is this external_id already trusted under a different row?
            existing = conn.execute(
                "SELECT id FROM devices WHERE channel = ? AND external_id = ? AND status = 'trusted'",
                (channel, external_id)
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM devices WHERE id = ?", (row_id,))
                conn.commit()
                logger.info(f"external_id {external_id} already trusted — cleaned up spare token row")
                return True

            now = datetime.now().isoformat()
            conn.execute(
                "UPDATE devices SET external_id = ?, device_name = ?, status = 'trusted', "
                "pairing_token = NULL, token_expires_at = NULL, paired_at = ?, last_active = ? "
                "WHERE id = ?",
                (external_id, device_name, now, now, row_id)
            )
            conn.commit()
        logger.info(f"Device paired: {channel}/{external_id} ({device_name})")
        return True

    # ─── Trust checks ───────────────────────────────────────────────────

    def is_trusted(self, external_id: str, channel: str = "telegram") -> bool:
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            row = conn.execute(
                "SELECT id FROM devices WHERE channel = ? AND external_id = ? AND status = 'trusted'",
                (channel, external_id)
            ).fetchone()
        return row is not None

    def touch_last_active(self, external_id: str, channel: str = "telegram"):
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            conn.execute(
                "UPDATE devices SET last_active = ? WHERE channel = ? AND external_id = ? AND status = 'trusted'",
                (datetime.now().isoformat(), channel, external_id)
            )
            conn.commit()

    # ─── Management ─────────────────────────────────────────────────────

    def list_devices(self, include_pending: bool = False) -> List[Dict]:
        status_filter = "" if include_pending else "WHERE status = 'trusted'"
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            rows = conn.execute(
                f"SELECT id, channel, external_id, device_name, status, paired_at, last_active "
                f"FROM devices {status_filter} ORDER BY id DESC"
            ).fetchall()
        cols = ["id", "channel", "external_id", "device_name", "status", "paired_at", "last_active"]
        return [dict(zip(cols, r)) for r in rows]

    def revoke(self, device_id: int) -> bool:
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            cur = conn.execute("UPDATE devices SET status = 'revoked' WHERE id = ? AND status = 'trusted'",
                                (device_id,))
            conn.commit()
            return cur.rowcount > 0

    def rename(self, device_id: int, new_name: str) -> bool:
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            cur = conn.execute("UPDATE devices SET device_name = ? WHERE id = ? AND status = 'trusted'",
                                (new_name, device_id))
            conn.commit()
            return cur.rowcount > 0

    def cleanup_expired_tokens(self):
        """Housekeeping — removes stale awaiting_redemption rows whose
        token has expired without ever being used."""
        with sqlite3.connect(DEVICES_DB_PATH) as conn:
            now = datetime.now().isoformat()
            cur = conn.execute(
                "DELETE FROM devices WHERE status = 'awaiting_redemption' AND token_expires_at < ?",
                (now,)
            )
            conn.commit()
            if cur.rowcount:
                logger.info(f"Cleaned up {cur.rowcount} expired pairing token(s)")

    @staticmethod
    def db_path() -> Path:
        return DEVICES_DB_PATH
