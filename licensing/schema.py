"""
LICENSING — Schema (Phase 3)

The license file format, frozen per the architecture principles locked
earlier: License Version, License ID, Product Edition, Issue Date, Expiry
Date, Public Key Version, Signature. Kept intentionally simple — a JSON
file with a detached signature over the other fields, not a JWT or other
heavier format.

No over-engineering: this stops casual sharing, not a determined attacker
with a debugger — an explicit, deliberate trade-off made when the
licensing architecture was frozen. A signed license needs no network
round-trip to verify (see license_manager.py) — network access is only
for purchasing, downloading updates, and optional services, per the
architectural invariant that the cloud never becomes a runtime dependency
for core functionality.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

SCHEMA_VERSION = "1.0"
# "Lifetime" licenses use a far-future expiry rather than None/null, so
# every date comparison in this module can be uniform — no special-casing
# "no expiry" as a separate code path that's easy to get wrong.
LIFETIME_SENTINEL_YEAR = 2126


@dataclass
class License:
    license_version: str
    license_id: str
    product_edition: str
    issue_date: str          # ISO 8601
    expiry_date: str         # ISO 8601 (far-future sentinel for lifetime licenses)
    public_key_version: str
    is_lifetime: bool = False
    signature: Optional[str] = None  # base64, filled in by issue_license.py after signing

    def canonical_payload(self) -> bytes:
        """
        Deterministic serialization of every field EXCEPT the signature
        itself — this is what gets signed, and what a signature is
        verified against. Sorted keys + compact separators so the same
        License object always serializes identically regardless of
        dict-ordering quirks, which matters because the signer and the
        verifier must byte-for-byte agree on what was signed.
        """
        data = asdict(self)
        data.pop("signature", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def is_expired(self, as_of: Optional[datetime] = None) -> bool:
        as_of = as_of or datetime.now(timezone.utc)
        expiry = datetime.fromisoformat(self.expiry_date)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return as_of > expiry

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "License":
        # Ignore unknown future fields rather than crashing — a v1 client
        # reading a v1.1 license (with fields it doesn't know about yet)
        # should degrade gracefully, not explode. Only known fields are
        # passed through.
        known_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)
