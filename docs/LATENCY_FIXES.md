# Latency Fixes — Redundant Brain Call, TTS Retry Waste, Planner Skip

Status: ready to commit and test on the Mac.

## Why this round exists

Your own test log showed ~25 seconds for a trivial "hi, how do you feel" on
`qwen2.5:7b`, and ~3.5 minutes for the YouTube+WhatsApp task. Three real,
separate, fixable causes — not one big rewrite.

## Fix #1 — Eliminated the redundant Brain call

**Before:** every action turn called the Brain once to decide if an action
was needed, then `run_planned_task`/`run_task` called it **again from
scratch** for the actual first reasoning step — the first response was
computed, then thrown away. One full wasted LLM round-trip (5-25s) on every
single action turn.

**Fixed:** `run_task()` and `run_planned_task()` now accept an optional
`initial_response` parameter. `main.py` and the Telegram bridge both pass
the response they already computed. The first step of execution reuses it
directly — zero extra Brain calls if that first response already resolves
the task (confirmed in testing: a simple single-step task now makes **zero**
additional Brain calls, down from at least 1). Every step after the first
still reasons fresh, exactly as before — this only removes the one
guaranteed-wasted call.

Omitting `initial_response` (old call style) still works exactly as before
— nothing that doesn't pass it changes behavior.

## Fix #2 — TTS stops retrying engines that already failed

**Before:** every single turn retried Kokoro, watched it fail
("Kokoro produced no audio"), retried Piper, watched it fail ("Piper not
found in PATH"), *then* fell through to macOS `say` — costing 10+ seconds
of pure waste per turn for engines that had never once worked in your
testing.

**Fixed:** `TextToSpeech` now remembers which engines failed this session
and skips straight past them on every subsequent turn. Verified: turn 1
tries all three engines (as it should — first failure needs to be
discovered), turn 2 only tries the one that actually works. Clears on
restart, so fixing Kokoro/Piper (e.g. installing `espeak-ng`) takes effect
next run without any code change needed.

## Fix #4 — Skip the Planner call for single-step tasks

**Before:** every action, simple or complex, paid for a separate Planner
LLM call before execution even started.

**Fixed:** a lightweight keyword check (`_looks_multi_step`) looks for
signals like "then", "after that", "followed by", "first... then" before
deciding whether to call the Planner at all. "Open YouTube" skips straight
to direct execution. "Open YouTube **and then** open WhatsApp" — the exact
phrasing from your real test — still correctly triggers planning. Verified
against 9 realistic examples including your actual test-log task.

This is a heuristic, not perfect — the design choice was high recall (when
unsure, treat as multi-step) since a false positive just costs one
avoidable-but-harmless Planner call, while a false negative would mean a
genuinely multi-step task gets handled by the adaptive loop instead of a
plan, which still works correctly, just without the upfront breakdown.

## Combined effect, per real scenario

| Scenario | Before | After |
|---|---|---|
| Simple resolved single-step ("hi", "what's the weather") | 1+ Brain calls | Often 0 extra calls |
| Single action needing execution ("open youtube") | 2 Brain calls minimum | 1 Brain call (just the completion check) |
| Multi-step ("X then Y") | 1 (classify) + 1 (plan) + 1 per step | 1 (classify) + 1 (plan) + 1 per step *after the first* |
| Every turn, TTS | ~10s wasted on dead engines | ~0s after turn 1 |

The multi-step case's per-step cost is unchanged (each step still needs its
own fresh reasoning) — the savings there is exactly one call (the first
step), same as the single-action case.

## What this does NOT fix

I flagged this clearly before starting: if the Mac is running Ollama on CPU
instead of Metal GPU acceleration, that's a hardware/environment fact these
fixes can't touch. Worth checking `ollama ps` and Activity Monitor's GPU
tab while a response is generating — if GPU usage is near zero during
inference, that's a bigger lever than anything in this round, and no code
change here addresses it.

## A regression I found and fixed before shipping

Adding the multi-step heuristic changed which code path two *existing*
Phase 1 tests exercised. Both used task strings ("multi-step task", "some
task with no plan") that don't contain any multi-step signal phrase — so
Fix #4 now correctly routes them away from the Planner *before* the tests'
own mocks of `planner.decompose` ever got called. One test failed outright
(caught by the regression suite); the other happened to still pass, but for
the wrong reason — it was accidentally testing the heuristic gate instead
of the planner-returns-None fallback it claimed to test. Both are now
explicitly isolated from the heuristic gate (each is tested separately, on
its own) so each test verifies what it says it verifies. This is exactly
why the full regression suite gets run before every package, not just the
new tests — a passing-for-the-wrong-reason test is worse than a failing one
because it hides a real coverage gap.

## Offline tests run before packaging

- `tests/test_latency_fixes_offline.py` — new, 16/16 checks: the multi-step
  heuristic against 9 realistic phrasings (including your real test-log
  task), zero-extra-calls confirmed for a resolved single-step task,
  exactly-one-extra-call confirmed for an action needing a completion
  check, multi-step tasks still plan correctly and still save the first
  step's call, TTS engine skip-caching confirmed across two turns.
- Re-ran all 4 existing suites (Phase 0, 1, 1.5, 2) — Phase 1's two stale
  tests fixed as described above, everything else unchanged. 76 checks
  total, all passing.

## Rollback

Four files touched: `agent/react_loop.py` (the three core fixes),
`mouth/tts.py` (engine failure caching), `main.py` and
`ecosystem/telegram_bridge.py` (both pass `initial_response` through — one
line each). `tests/test_phase1_offline.py` had two tests corrected.
`git diff` against the Phase 2 commit shows the full blast radius.
