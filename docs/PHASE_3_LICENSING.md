
# Phase 3 — Licensing (Client) + SAM Infrastructure (Server)

Status: ready to commit. Two separate deployables — read the split below
carefully before pushing anything.

## Two things, two different homes

**1. `licensing/` — goes into your `~/SAM` repo** (merge via the usual
`cp -r` + git push flow). This is the client-side offline verification
module.

**2. `sam-infrastructure/` — a SEPARATE, standalone project.** Do NOT
merge this into `~/SAM`. It's a small backend meant to be pushed to its
OWN new GitHub repo and deployed to Render. Full walkthrough in its own
`README.md`.

## Client-side: `licensing/`

- **`schema.py`** — the `License` dataclass with the exact fields frozen
  in the architecture principles: version, ID, edition, issue/expiry
  date, public key version, signature. Canonical JSON serialization
  (sorted keys) so signer and verifier always agree byte-for-byte on what
  was signed.
- **`keygen.py`** — run once, by you, locally. Generates an Ed25519
  keypair. Refuses to overwrite an existing private key (would invalidate
  every license already issued).
- **`license_manager.py`** — fully offline verification. No network
  round-trip for day-to-day checks, per the frozen invariant. Handles
  clock-rollback detection (stores last-verified timestamp, rejects if
  system time appears to have moved backwards beyond a 6-hour grace
  window for normal drift).
- **`issue_license.py`** — the admin signing script. **Run only on your
  own machine.** Never deploy this file's logic to a server — the private
  key it needs must never touch anything internet-facing.
- **`public_key.pem`** — currently a placeholder. Run `keygen.py`, then
  replace this file's contents with your real public key and commit it
  (safe — it's public by design).

**`sam_cli.py`**: two new commands — `license` (status) and `activate
<file>` (install a purchased license).

**`main.py`**: a non-blocking check at startup. Logs/prints the license
status, never blocks or exits — matches the frozen principle "no hard
license enforcement at launch, non-blocking warnings only." You're still
actively testing daily; this must never lock you out of your own app.

## Security properties, all verified by test

- **Tamper detection**: any field changed after signing (e.g., trying to
  upgrade "SAM Personal" to "SAM Enterprise" by editing the JSON)
  invalidates the signature. Confirmed.
- **Forgery rejection**: a license signed with a different private key
  fails verification against your public key. Confirmed — nobody can mint
  a valid license without your actual private key, full stop.
- **Expiry enforcement**: a genuinely, validly-signed-but-expired license
  is rejected. Confirmed.
- **Clock-rollback detection**: rolling the system clock back to dodge an
  expiry date is caught (beyond a 6-hour grace window for normal drift).
  Confirmed.
- **Graceful degradation**: no license installed, a corrupted license
  file, or a missing/broken public key all report a clear status without
  crashing anything. Confirmed against the real placeholder key file
  currently in the repo.

No over-engineering beyond this — a determined attacker with a debugger
can bypass any client-side check regardless of effort. This stops casual
sharing, which was the explicit, deliberate goal when this architecture
was frozen.

## Server-side: `sam-infrastructure/`

A small FastAPI app with exactly three jobs:
1. Receive and verify Razorpay webhooks (`payment.captured` events).
2. Show you (admin-only) what's pending license issuance.
3. Let you mark a payment as issued once you've manually generated and
   sent the license.

**It never signs a license and never talks to the SAM client app.** The
private key never touches this server — that's a deliberate security
boundary. If this server were ever compromised, nobody could mint a
license from it, only see payment records.

**Hosting**: Render free Web Service + Render free Postgres (not plain
SQLite-on-disk — Render's free web services wipe their filesystem on
redeploy, which would silently lose payment history; Postgres is a
separate, genuinely persistent resource). Deploys via the included
`render.yaml` Blueprint — one click provisions both pieces linked
together. Full walkthrough, including the exact Razorpay dashboard steps,
in `sam-infrastructure/README.md`.

**Security-critical piece, tested thoroughly**: `razorpay_verify.py`
checks Razorpay's HMAC-SHA256 webhook signature using constant-time
comparison, before anything in a webhook payload is trusted. Without
this, anyone could POST a fake "payment captured" event. Verified: correct
signature accepted, wrong signature rejected, tampered body rejected
(even 1 byte), wrong secret rejected, missing signature/secret both fail
closed rather than defaulting to trusting an empty check.

**End-to-end tested** (in-memory database, no real Postgres needed for
this): full webhook receive → record → admin list → mark-issued flow, 14
checks, including duplicate-webhook handling (Razorpay retries webhooks;
a duplicate `payment_id` is recognized and not double-recorded) and
correct paise-to-rupees conversion.

## What I genuinely cannot test from here

Real Postgres connectivity, real Razorpay webhook delivery, and the
actual Render deployment itself all need your real accounts/infrastructure
— I tested the logic thoroughly with an in-memory substitute, but the
real integration is yours to confirm once deployed. The README walks
through every step.

## Manual-trigger flow, end to end (as you chose it)

```
Buyer pays via Razorpay
        ↓
Webhook fires → sam-infrastructure records it (Postgres)
        ↓
You check: curl .../admin/payments/pending
        ↓
You run locally: python3 -m licensing.issue_license --lifetime
        ↓
You email the resulting license_xxxx.json to the buyer
        ↓
Buyer runs: python sam_cli.py activate license_xxxx.json
        ↓
You call: curl -X POST .../admin/payments/{id}/mark-issued
```

## What's explicitly deferred, not forgotten

- Automatic license generation + email on payment (manual for v1, per
  your choice — automate once there's real demand).
- Professional/Enterprise editions (SAM Personal only, per the frozen
  "launch with one excellent edition" decision).
- Update distribution via SAM Infrastructure (mentioned in the original
  architecture principles, no client-side update-checker built yet).
- License revocation (the schema has a `license_id` and
  `public_key_version` specifically to support this later without
  breaking existing licenses, per the frozen "license evolution" plan —
  not built now since v1 has no online check-in at all, by design).

## Tests run before packaging

- `tests/test_licensing_offline.py` — 14/14, full client-side crypto
  roundtrip and every security property above.
- Server: 7/7 signature verification checks + 14/14 end-to-end webhook/
  admin flow checks (shown in this conversation, not yet a committed test
  file in `sam-infrastructure/` — flag if you want that formalized into
  the repo too).
- Full regression across all 9 existing client-side suites — no
  regressions, 119 checks total, all passing.

## Rollback

**Client side** (`SAM-main` zip): new `licensing/` package, `sam_cli.py`
(+2 commands), `config/settings.py` (+1 field), `main.py` (+non-blocking
startup check), `requirements.txt` (+cryptography), new test file.
`git diff` against the task-request-and-stagnation commit shows the full
blast radius.

**Server side**: entirely new, separate project — nothing to roll back
against since it doesn't touch `~/SAM` at all.

## The launchd repeating-restart issue (separate, still open)

Flagged in this same conversation: your `KeepAlive: true` launchd plist
restarts SAM unconditionally on any exit. If the background (voice-mode)
instance is crashing shortly after startup — most likely a microphone
permission issue specific to non-interactive launchd agents on macOS,
separate from Terminal.app's own mic permission — you get the repeating
"SAM is ready" you noticed. Immediate relief:
```bash
launchctl unload ~/Library/LaunchAgents/ai.sam.assistant.plist
```
Waiting on `logs/sam_error.log`'s actual traceback before writing a real
fix — didn't want to patch blind. Unrelated to everything else in this
document; tracked separately.
