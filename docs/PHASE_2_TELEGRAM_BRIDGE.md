# Phase 2 — Telegram Bridge (Internet-Relay Ecosystem)

Status: ready to commit and test on the Mac + your phone.

## Read this first: what this actually is

This is **not** the local-WiFi ecosystem originally scoped for "Phase 2" —
it's a deliberate, explicit trade-off we agreed on to get remote control
working now, without a native Android app.

**What this means concretely:** when you send a command from your phone via
Telegram, that text travels through Telegram's servers to reach your laptop
(TLS-encrypted in transit, but readable server-side by Telegram — this is a
regular bot chat, not a Secret Chat with end-to-end encryption). Your actual
SAM data — Founder Mode, memories, conversation history — never leaves the
laptop; only the live command text for this bridge touches Telegram at all.

Real same-WiFi, zero-third-party device pairing is still the long-term plan,
whenever a proper Android app exists. This bridge gets you working remote
control in the meantime.

## What was built

**`ecosystem/device_registry.py`** — SQLite-backed trusted device list at
`~/.sam_data/ecosystem/devices.db`, kept separate from Founder Mode/memory
(account/device metadata vs. AI data, per the PDR's Local Data Separation
principle). Handles the full pairing lifecycle: token creation, one-time
redemption (a token can't be reused), 10-minute expiry, trust checks, revoke,
rename.

**`ecosystem/telegram_bridge.py`** — the bot itself. Long-polls Telegram (no
inbound network config, no port forwarding, no public IP needed). Three
handlers:
- `/start <token>` — pairing. Validates the token via the registry, marks
  that Telegram chat as trusted if valid.
- Any text message — if the chat is trusted, routes through **the exact
  same pipeline `main.py` uses**: builds a `Session`, calls `Brain.process`,
  runs real execution via `ReactLoop.run_planned_task` if an action is
  needed (Planner + Verifier's 1-retry, same as everything else you've
  tested), saves to memory, captures to Founder Mode. Untrusted chats get a
  polite refusal, not a stack trace or silence.
- `/devices` — lets you check what's paired, from your phone.

Runs as **its own standalone process** — `python -m ecosystem.telegram_bridge`
— separate from `main.py`'s voice/text loop entirely. It builds its own
`Brain`/`ReactLoop`/`FounderModeManager` instances the same way `main.py`
does. Nothing in `main.py` was touched to build this — zero risk to the
voice/text pipeline you've already tested.

**`ecosystem/pair_new_device.py`** — run this on the laptop to generate a
pairing QR code (printed as ASCII in the terminal, works fine over SSH/no
GUI, plus saved as a PNG). Scanning it opens Telegram directly to your bot
with the token pre-filled via a `t.me/<bot>?start=<token>` deep link — one
scan-and-tap on the phone, no manual typing.

**`sam_cli.py`** — two new commands: `devices` (list trusted devices),
`revoke-device <id>`.

**A safety note:** `TelegramBridge` uses an `asyncio.Lock` so only one task
runs at a time — `ReactLoop`/the hands weren't built for concurrent execution
(two browser/terminal actions racing each other would be a mess), so a
second command sent while one's still running will simply wait its turn
rather than corrupting shared state.

## Setup (do this before testing)

1. **Create the bot.** Message `@BotFather` on Telegram, send `/newbot`,
   follow the prompts. You'll get a token (looks like `123456:ABC-...`) and
   choose a username (must end in `bot`, e.g. `dhanush_sam_bot`).
2. **Configure SAM.** Add to `config/settings.yaml`:
   ```yaml
   telegram_bot_token: "123456:ABC-your-real-token"
   telegram_bot_username: "dhanush_sam_bot"   # no @
   ```
3. **Install the new dependencies:**
   ```bash
   pip install python-telegram-bot qrcode[pil]
   ```
   (Both free, MIT/Apache-licensed, zero cost — added to `requirements.txt`.)
4. **Generate a pairing code:**
   ```bash
   python -m ecosystem.pair_new_device
   ```
   Scan the QR with your phone's camera — it opens Telegram and sends the
   pairing code to your bot automatically.
5. **Start the bridge** (separate terminal/session from `main.py`):
   ```bash
   python -m ecosystem.telegram_bridge
   ```
6. From your phone's Telegram, send SAM a real command and watch it execute
   on the laptop, same as your text-mode testing.

## What to verify on the Mac

- Pairing: scan the QR, confirm you get "Paired!" back in Telegram.
- Trust gating: from a different Telegram account (or ask a friend), message
  the bot without pairing first — confirm you get the "not paired" message,
  not a response or a crash.
- Real execution: send a command through Telegram, confirm it actually
  executes (same as your `main.py --text` testing) and you get the real
  outcome back, not a pre-action guess.
- `python sam_cli.py devices` shows your phone as trusted.
- `python sam_cli.py revoke-device <id>` then try sending a command from
  that phone again — confirm it's refused.
- Try pairing with an expired/reused token (wait 10+ minutes, or scan the
  same QR twice) — confirm the second attempt is rejected.

## Offline tests run before packaging

`tests/test_phase2_telegram_offline.py` — 20/20 checks, zero network or bot
token needed. Covers the full pairing lifecycle (valid/invalid/reused/expired
tokens, trust checks, revoke) and every bot handler using mocked Telegram
Update/Context objects (pairing success/failure, trust gating on messages,
real turn processing via a mocked `_process_turn`, graceful error handling,
`/devices` command both trusted and untrusted).

Also re-ran Phase 0, Phase 1, and Phase 1.5 offline suites — no regressions.

## A bug I introduced and caught before shipping

While wiring the new `devices`/`revoke-device` CLI commands into
`sam_cli.py`, an editing mistake deleted the `def cmd_founder_review():`
line itself, leaving that function's body orphaned with no signature —
would have crashed `sam_cli.py` on *any* command, not just the new ones,
since it's imported into a shared dispatch dict at module load. Caught by
running the exact regression suite before packaging, not just the new
tests — worth noting since it's a reminder of why the "test everything,
not just what changed" habit matters. Fixed, and the fix is included in
this zip; verified `founder-review` and every other existing command still
works.

## Known scope cuts (not built this pass)

Explicitly out of scope for this round, to keep it testable: clipboard sync,
notification sync, file transfer, conversation continuation state, same-WiFi
local discovery. These were listed under Phase 2 originally but weren't
needed to answer "can I control SAM from my phone" — they're real follow-ups
once this is confirmed working, not forgotten.

## Rollback

New files only, nothing existing was restructured: `ecosystem/__init__.py`,
`ecosystem/device_registry.py`, `ecosystem/telegram_bridge.py`,
`ecosystem/pair_new_device.py`, `tests/test_phase2_telegram_offline.py`.
Modified: `config/settings.py` (2 new fields), `config/settings.yaml`
(commented config block), `requirements.txt` (2 new deps), `sam_cli.py`
(2 new commands + the bugfix above). `main.py` was not touched at all.
