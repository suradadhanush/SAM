"""
Offline smoke test for Phase 3 licensing — no network needed, all pure
cryptographic logic. Generates its own throwaway test keypair (NEVER the
real production key) to exercise the full issue -> install -> verify flow
plus every security property: tamper detection, expiry, wrong-key
forgery rejection, and clock-rollback detection.

Usage:
    HOME=/tmp/sam_smoke_licensing python3 tests/test_licensing_offline.py
"""

import sys
import json
import uuid
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import licensing.license_manager as lm_module  # noqa: E402
from licensing.schema import License, SCHEMA_VERSION  # noqa: E402
from licensing.issue_license import issue, load_private_key  # noqa: E402
from licensing import keygen  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


def main():
    test_home = Path.home()
    test_key_dir = test_home / ".sam_signing_keys"
    test_pub_key = test_key_dir / "sam_public_key.pem"

    # Generate a throwaway TEST keypair (never the real production key —
    # this only ever runs under a throwaway HOME set by the test runner).
    keygen.main()
    check("Test keypair generated", test_pub_key.exists())

    # Point license_manager at the TEST public key for this whole test run.
    with patch.object(lm_module, "PUBLIC_KEY_PATH", test_pub_key):

        # === Basic roundtrip ===
        path = issue(edition="SAM Personal", lifetime=False, years=1.0,
                      public_key_version="v1", out_path=str(test_home / "test_license.json"))
        mgr = lm_module.LicenseManager()
        ok, msg = mgr.install_license(path)
        check("Valid license installs successfully", ok is True)

        status, message, lic = mgr.check()
        check("Installed license reports VALID", status == lm_module.LicenseStatus.VALID)
        check("License fields round-trip correctly", lic.product_edition == "SAM Personal")

        # === Tamper detection ===
        tamper_path = str(test_home / "tamper_test.json")
        data = json.loads(Path(path).read_text())
        data["product_edition"] = "SAM Enterprise"  # try to upgrade edition post-signing
        Path(tamper_path).write_text(json.dumps(data))

        mgr2 = lm_module.LicenseManager()
        ok2, msg2 = mgr2.install_license(tamper_path)
        check("Tampered license (edition changed) is rejected", ok2 is False)
        check("Rejection message references invalid/signature",
              "invalid" in msg2.lower() or "signature" in msg2.lower())

        # === Expiry detection (genuinely expired, validly signed) ===
        private_key = load_private_key()
        past_issue = datetime.now(timezone.utc) - timedelta(days=400)
        past_expiry = datetime.now(timezone.utc) - timedelta(days=35)
        expired_lic = License(
            license_version=SCHEMA_VERSION, license_id=str(uuid.uuid4()),
            product_edition="SAM Personal", issue_date=past_issue.isoformat(),
            expiry_date=past_expiry.isoformat(), public_key_version="v1", is_lifetime=False
        )
        sig = private_key.sign(expired_lic.canonical_payload())
        expired_lic.signature = base64.b64encode(sig).decode("ascii")
        expired_path = str(test_home / "expired_test.json")
        Path(expired_path).write_text(json.dumps(expired_lic.to_dict()))

        mgr3 = lm_module.LicenseManager()
        ok3, msg3 = mgr3.install_license(expired_path)
        check("Genuinely expired (but validly signed) license is rejected", ok3 is False)
        check("Rejection message references expiry", "expired" in msg3.lower())

        # === Forgery rejection (signed by a DIFFERENT private key) ===
        other_key = Ed25519PrivateKey.generate()
        fake_lic = License(
            license_version=SCHEMA_VERSION, license_id=str(uuid.uuid4()),
            product_edition="SAM Personal", issue_date=datetime.now(timezone.utc).isoformat(),
            expiry_date=(datetime.now(timezone.utc) + timedelta(days=365)).isoformat(),
            public_key_version="v1", is_lifetime=False
        )
        fake_sig = other_key.sign(fake_lic.canonical_payload())
        fake_lic.signature = base64.b64encode(fake_sig).decode("ascii")
        fake_path = str(test_home / "wrong_key_test.json")
        Path(fake_path).write_text(json.dumps(fake_lic.to_dict()))

        mgr4 = lm_module.LicenseManager()
        ok4, msg4 = mgr4.install_license(fake_path)
        check("License forged with a different key is rejected", ok4 is False)

        # === Lifetime license ===
        lifetime_path = issue(edition="SAM Personal", lifetime=True, years=0,
                                public_key_version="v1", out_path=str(test_home / "lifetime_test.json"))
        mgr5 = lm_module.LicenseManager()
        ok5, msg5 = mgr5.install_license(lifetime_path)
        check("Lifetime license installs successfully", ok5 is True)
        status5, _, lic5 = mgr5.check()
        check("Lifetime license is not expired (far-future sentinel)", lic5.is_expired() is False)

        # === Clock rollback detection ===
        future_time = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
        lm_module.CLOCK_STATE_PATH.write_text(json.dumps({"last_verified": future_time}))
        status6, message6, _ = mgr5.check()
        check("Clock rollback is detected after system time appears to precede last check",
              status6 == lm_module.LicenseStatus.CLOCK_ROLLBACK_SUSPECTED)

        # === Malformed / missing license file ===
        mgr6 = lm_module.LicenseManager()
        ok7, msg7 = mgr6.install_license("/nonexistent/path/does_not_exist.json")
        check("Nonexistent license file fails gracefully, not a crash", ok7 is False)

    # === No public key at all (module-level test, outside the patch context) ===
    with patch.object(lm_module, "PUBLIC_KEY_PATH", Path("/nonexistent/public_key.pem")):
        mgr7 = lm_module.LicenseManager()
        check("Missing public key file doesn't crash on construction", mgr7._public_key is None)

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Phase 3 licensing module verified: sign/verify roundtrip, tamper detection, "
          "expiry, forgery rejection, and clock-rollback protection all confirmed working.")


if __name__ == "__main__":
    main()
