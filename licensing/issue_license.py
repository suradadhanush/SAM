"""
LICENSING — Issue a License (Phase 3, ADMIN ONLY, run on your own machine)

Run this locally, on the machine that holds your private signing key
(~/.sam_signing_keys/sam_private_key.pem, from licensing/keygen.py). NEVER
run this on a hosted server. This script and the private key it needs
should never touch a machine you don't fully control.

Manual-trigger flow for v1 (per your own choice — automate later once
there's real demand): check the SAM Infrastructure admin panel or your
Razorpay dashboard for a payment, then run this to generate a license,
then send the resulting file to the buyer yourself.

Usage:
    python3 -m licensing.issue_license --edition "SAM Personal" --lifetime
    python3 -m licensing.issue_license --edition "SAM Personal" --years 1
"""

import argparse
import base64
import json
import uuid
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from licensing.schema import License, SCHEMA_VERSION, LIFETIME_SENTINEL_YEAR

PRIVATE_KEY_PATH = Path.home() / ".sam_signing_keys" / "sam_private_key.pem"


def load_private_key() -> Ed25519PrivateKey:
    if not PRIVATE_KEY_PATH.exists():
        print(f"No private key found at {PRIVATE_KEY_PATH}.")
        print("Run `python3 -m licensing.keygen` first (once, ever).")
        sys.exit(1)
    pem_bytes = PRIVATE_KEY_PATH.read_bytes()
    return serialization.load_pem_private_key(pem_bytes, password=None)


def issue(edition: str, lifetime: bool, years: float, public_key_version: str, out_path: str) -> str:
    private_key = load_private_key()

    now = datetime.now(timezone.utc)
    if lifetime:
        expiry = now.replace(year=LIFETIME_SENTINEL_YEAR)
    else:
        expiry = now + timedelta(days=int(365 * years))

    lic = License(
        license_version=SCHEMA_VERSION,
        license_id=str(uuid.uuid4()),
        product_edition=edition,
        issue_date=now.isoformat(),
        expiry_date=expiry.isoformat(),
        public_key_version=public_key_version,
        is_lifetime=lifetime,
    )

    signature = private_key.sign(lic.canonical_payload())
    lic.signature = base64.b64encode(signature).decode("ascii")

    out = Path(out_path)
    out.write_text(json.dumps(lic.to_dict(), indent=2))
    return str(out)


def main():
    parser = argparse.ArgumentParser(description="Issue a signed SAM license (run locally only, never on a server)")
    parser.add_argument("--edition", default="SAM Personal")
    parser.add_argument("--lifetime", action="store_true", help="Never expires (uses a far-future sentinel date)")
    parser.add_argument("--years", type=float, default=1.0, help="Validity period if not --lifetime")
    parser.add_argument("--key-version", default="v1")
    parser.add_argument("--out", default=None, help="Output path (default: ./license_<id>.json)")
    args = parser.parse_args()

    out_path = args.out or f"license_{uuid.uuid4().hex[:8]}.json"
    path = issue(args.edition, args.lifetime, args.years, args.key_version, out_path)
    print(f"License issued: {path}")
    print()
    print("Send this file to the buyer. They install it with:")
    print(f"  python sam_cli.py activate {Path(path).name}")


if __name__ == "__main__":
    main()
