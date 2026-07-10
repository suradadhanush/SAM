# Execution Wiring — SAM Now Actually Does Things

Status: ready to commit and test on the Mac. This is a bigger behavioral change
than any phase before it — read this whole doc before testing.

## The bug this fixes

From your test log: you asked SAM to open YouTube, play a song, and open
WhatsApp. It replied "Opening YouTube and playing the song, then opening
WhatsApp" — and did none of it. `main.py` only ever spoke `response.text`,
which is the Brain's pre-action narration written in the same JSON response as
the action decision — not a report of anything that actually happened. Nothing
downstream (`ReactLoop`, the hands) was ever called. This was true before any
of the three phases I built and is not something those phases introduced —
I flagged it explicitly in both the Phase 1 and Phase 1.5 docs as a decision
still waiting to be made. You've now made it: wire it in.

## What changed

**`main.py`:**
- Constructs `self.react_loop = ReactLoop(self.settings, founder_mode=self.founder_mode)`
  in `__init__`.
- In `_process()`: if `response.action` is set to a real action (not `None`/`"none"`),
  SAM now calls `self.react_loop.run_planned_task(...)` — Planner-first, each
  step verified with 1 retry (Phase 1.5), falling back to the adaptive
  step-by-step loop if planning fails — and speaks/saves **that result**,
  not the Brain's pre-action guess. If no action is needed, behavior is
  identical to before (plain conversation).
- If execution raises anything unexpected, the existing outer `try/except`
  in `_process()` catches it — you get "I hit an error. Check the logs."
  instead of a crash. Verified this path explicitly (see offline test).

**`hands/terminal/runner.py` — a real safety gap I found and fixed:**
- `REQUIRES_CONFIRMATION` (rm, sudo, kill, mv, etc.) existed as a list in the
  original code but was **never actually checked anywhere** — only
  `BLOCKED_COMMANDS` was enforced. That was fine while `ReactLoop` was dormant.
  Now that a conversation turn can trigger real terminal execution, this needed
  to become a real gate, not a decorative list. Default behavior: commands
  matching that list are refused with a clear message instead of running
  silently. Opt in via `settings.allow_risky_terminal_commands = True` if you
  want SAM to run that class of command unattended. `BLOCKED_COMMANDS`
  (`rm -rf /`, fork bombs, etc.) are still always refused regardless of this
  setting — that list was already enforced and still is.

**`config/settings.py`:** one new field, `allow_risky_terminal_commands: bool = False`.

## What this means concretely, next time you test

- Ask SAM to do something real (open an app, browse somewhere, list files) —
  it will actually attempt it via PyAutoGUI/AppleScript/Playwright/subprocess,
  not just describe it.
- Expect it to be **slower** than before on action turns — a planned task now
  makes at least 2 LLM calls (planning + one execution step minimum) instead
  of 1, plus the actual action's execution time (Playwright opening a browser
  is not instant). This matches the 12-28 second "complex task" latency your
  own PDR already documented — you're now actually hitting that path instead
  of a fake instant text reply.
- Ask it to do something requiring `rm`, `sudo`, `mv`, or `kill` and confirm
  you get the "needs manual confirmation" message instead of it just running.
- **Before testing real browser/app control**: Playwright needs its browser
  binaries installed (`playwright install` if not already done), and macOS
  will prompt for Accessibility / Screen Recording permissions the first time
  PyAutoGUI or the vision module tries to act — grant those or control actions
  will silently fail at the OS level, which is outside anything this code can
  detect or fix.

## What I can't guarantee from here

You asked to make sure eyes/mouth/ears/hands "all work, no one must fail."
I can guarantee the code paths are wired correctly and fail safely (verified
below) — I can't guarantee runtime environment issues on a machine I don't
have access to: whether Playwright's browsers are installed, whether macOS
permissions are granted, whether your specific WhatsApp/YouTube flow needs
a login state Playwright doesn't have, etc. Those will surface as real
`execute()` failures, which now get one automatic retry (Phase 1.5) and then
report honestly instead of pretending to have succeeded — which is the actual
fix for the trust problem in your test log, even in cases I can't personally
verify tonight.

One unrelated, smaller thing from your log, not touched here: Kokoro and
Piper both failed, but your existing 3-tier fallback chain (Kokoro → Piper →
macOS `say`) has a third rung, and no failure was logged for it — meaning
`say` almost certainly spoke the response fine. Not urgent, but if you want
Kokoro/Piper actually working (better voice quality than `say`), that's a
separate, smaller fix — Kokoro's "produced no audio" is most commonly a
missing `espeak-ng` dependency on macOS; Piper just needs `pip install piper-tts`
or the binary on PATH. Flag if you want that looked at next.

## Known inefficiency, not fixed here on purpose

`_process()` calls `brain.process(session)` once to check if there's an
action, and if so, `run_planned_task()` calls `brain.process()` again
internally (for planning and each step). That's one redundant LLM call
(~3-6 sec) on every action turn. Didn't refactor this now because doing it
safely means changing `run_planned_task`'s signature to accept an
already-computed first response, which is a real (if small) API change I
didn't want to bundle into the same change as "turn on real execution" —
better to test this version first, then optimize latency as a clean
follow-up once you've confirmed the execution itself is reliable.

## Offline tests run before this was packaged

- Terminal safety gate: confirmed `rm`/`sudo` refused by default, allowed
  with `allow_risky=True`, and `rm -rf /` always blocked regardless.
- Full flow simulated with a realistic 2-turn fake Brain (decides an action,
  then recognizes completion after seeing the observation) — confirmed the
  final response is the *real* execution outcome, not the pre-action claim.
- Confirmed an unexpected crash inside execution propagates cleanly to
  `main.py`'s existing outer `try/except` rather than taking SAM down.
- Re-ran all three existing offline suites (Phase 0, 1, 1.5) — no regressions,
  22+14+10 checks still passing.

I did not write a new formal test file for this one — the three checks above
were run directly and are shown in full in this conversation. If you want a
`tests/test_execution_wiring_offline.py` added to the repo for future
regression checks, say so and I'll add it.

## Rollback

Four files touched: `main.py` (import + construction + `_process()` logic),
`hands/terminal/runner.py` (safety gate enforcement), `agent/react_loop.py`
(`_get_terminal` passes the new setting through), `config/settings.py` (1 new
field). `git diff` against the Phase 1.5 commit shows the full blast radius —
this is the smallest file-count change so far, but the highest-impact one,
since it's the first time any of this code actually touches your real machine
from a live conversation.
