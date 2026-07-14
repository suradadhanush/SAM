"""
LICENSING — Key Generation (Phase 3)

Run this ONCE, on your own machine, to generate the signing keypair.

The PRIVATE key must NEVER be committed to git, never uploaded to the
hosted SAM Infrastructure server, and never leave your own machine. It's
the only thing that can issue valid licenses — treat it like a password.
This is deliberate: the hosted server only ever receives and records
payments, it never holds anything capable of minting a license, so
compromising the server can't compromise your ability to control who gets
a valid SAM.

The PUBLIC key is safe to commit — it's embedded in the client
(licensing/public_key.pem) so SAM can verify a license completely offline,
with no network round-trip. Having it does not let anyone issue new
licenses, only verify existing ones.

Usage:
    python3 -m licensing.keygen
"""

import sys
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

KEY_DIR = Path.home() / ".sam_signing_keys"


def main():
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    private_path = KEY_DIR / "sam_private_key.pem"
    public_path = KEY_DIR / "sam_public_key.pem"

    if private_path.exists():
        print(f"A private key already exists at {private_path}.")
        print("Refusing to overwrite it — generating a new one would invalidate")
        print("every license already issued with the old one. Delete it manually")
        print("first only if you're SURE (this also means re-issuing licenses to")
        print("anyone who already has one).")
        sys.exit(1)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    private_path.chmod(0o600)  # owner read/write only

    print(f"Private key saved to: {private_path}")
    print(f"  (chmod 600 — keep this OFF git, OFF any server, back it up somewhere private)")
    print(f"Public key saved to:  {public_path}")
    print()
    print("Next steps:")
    print(f"  1. Copy the contents of {public_path} into licensing/public_key.pem")
    print(f"     in the SAM repo (this one is safe to commit to git).")
    print(f"  2. Keep {private_path} on this machine only. Losing it means you")
    print(f"     can never issue another valid license again — back it up somewhere")
    print(f"     safe and private (not git, not cloud sync unencrypted).")


if __name__ == "__main__":
    main()
