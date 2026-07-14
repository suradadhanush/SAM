"""
LICENSING — License Manager (Phase 3, client side)

Verifies a signed license file completely offline — no network round-trip
for day-to-day use, per the frozen architectural invariant: "Network
access is required only for purchasing, downloading updates, and optional
services — not for day-to-day AI functionality."

Clock-rollback protection: stores the last-verified timestamp locally. If
the system clock has moved backwards significantly since the last check,
treats the license as suspicious rather than trusting a clock that could
have been deliberately rolled back to dodge an expiry date. A grace period
allows for normal timezone/NTP drift without false-triggering.

No over-engineering: a determined attacker with a debugger can bypass any
of this regardless of effort. The goal (per the architecture principles
frozen earlier) is stopping casual sharing, not defeating reverse
engineering.

This module NEVER enforces anything by itself — check() just reports a
status. The caller (main.py) decides what to do with it. Default behavior
wired into main.py is a non-blocking warning, not a hard lock-out — see
docs/PHASE_3_LICENSING.md for why.
"""

import json
import logging
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

from licensing.schema import License

logger = logging.getLogger("SAM.Licensing")

SAM_DATA_DIR = Path.home() / ".sam_data"
LICENSING_DIR = SAM_DATA_DIR / "licensing"
ACTIVE_LICENSE_PATH = LICENSING_DIR / "active_license.json"
CLOCK_STATE_PATH = LICENSING_DIR / "clock_state.json"

CLOCK_ROLLBACK_GRACE = timedelta(hours=6)  # allow minor drift/timezone issues

PUBLIC_KEY_PATH = Path(__file__).parent / "public_key.pem"


class LicenseStatus:
    VALID = "valid"
    NO_LICENSE = "no_license"                 # no license installed at all
    EXPIRED = "expired"
    INVALID_SIGNATURE = "invalid_signature"    # tampered, corrupted, or wrong key
    CLOCK_ROLLBACK_SUSPECTED = "clock_rollback_suspected"
    MALFORMED = "malformed"


class LicenseManager:
    def __init__(self):
        LICENSING_DIR.mkdir(parents=True, exist_ok=True)
        self._public_key = self._load_public_key()

    def _load_public_key(self) -> Optional[Ed25519PublicKey]:
        try:
            pem_bytes = PUBLIC_KEY_PATH.read_bytes()
            return serialization.load_pem_public_key(pem_bytes)
        except FileNotFoundError:
            logger.warning(f"No public key found at {PUBLIC_KEY_PATH} — "
                            f"license verification will always fail until this is added "
                            f"(run licensing/keygen.py once, then copy the public key here).")
            return None
        except Exception as e:
            logger.error(f"Failed to load public key: {e}")
            return None

    def install_license(self, license_file_path: str) -> Tuple[bool, str]:
        """Verifies a license file, and if valid, copies it into the
        active slot. Returns (success, message)."""
        try:
            data = json.loads(Path(license_file_path).read_text())
            lic = License.from_dict(data)
        except Exception as e:
            return False, f"Could not read license file: {e}"

        status, message = self._verify(lic)
        if status != LicenseStatus.VALID:
            return False, f"License is not valid ({status}): {message}"

        ACTIVE_LICENSE_PATH.write_text(json.dumps(lic.to_dict(), indent=2))
        self._update_clock_state()
        return True, f"License installed: {lic.product_edition}, expires {lic.expiry_date}"

    def check(self) -> Tuple[str, str, Optional[License]]:
        """
        Returns (status, message, license_or_none). Never raises — any
        internal error is treated as "not licensed" via a status, not an
        exception the caller has to handle specially.
        """
        if not ACTIVE_LICENSE_PATH.exists():
            return LicenseStatus.NO_LICENSE, "No license installed.", None

        try:
            data = json.loads(ACTIVE_LICENSE_PATH.read_text())
            lic = License.from_dict(data)
        except Exception as e:
            return LicenseStatus.MALFORMED, f"License file is corrupted: {e}", None

        status, message = self._verify(lic)
        if status == LicenseStatus.VALID:
            self._update_clock_state()
        return status, message, lic

    def _verify(self, lic: License) -> Tuple[str, str]:
        if self._public_key is None:
            return LicenseStatus.INVALID_SIGNATURE, "No public key available to verify against."

        if not lic.signature:
            return LicenseStatus.INVALID_SIGNATURE, "License has no signature."

        try:
            sig_bytes = base64.b64decode(lic.signature)
            self._public_key.verify(sig_bytes, lic.canonical_payload())
        except InvalidSignature:
            return LicenseStatus.INVALID_SIGNATURE, "Signature does not match — license was tampered with or issued by a different key."
        except Exception as e:
            return LicenseStatus.INVALID_SIGNATURE, f"Signature verification failed: {e}"

        rollback_message = self._check_clock_rollback()
        if rollback_message is not None:
            return LicenseStatus.CLOCK_ROLLBACK_SUSPECTED, rollback_message

        if lic.is_expired():
            return LicenseStatus.EXPIRED, f"License expired on {lic.expiry_date}."

        return LicenseStatus.VALID, "License is valid."

    def _check_clock_rollback(self) -> Optional[str]:
        now = datetime.now(timezone.utc)
        try:
            state = json.loads(CLOCK_STATE_PATH.read_text())
            last_seen = datetime.fromisoformat(state["last_verified"])
        except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
            return None  # first check ever — nothing to compare against yet

        if now < last_seen - CLOCK_ROLLBACK_GRACE:
            return (f"System clock appears to have moved backwards "
                    f"(last check was {last_seen.isoformat()}, now is {now.isoformat()}).")
        return None

    def _update_clock_state(self):
        CLOCK_STATE_PATH.write_text(json.dumps({"last_verified": datetime.now(timezone.utc).isoformat()}))
