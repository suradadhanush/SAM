# Founder Mode Task-Bleed Fix + ReAct Stagnation Detection

Status: ready to commit and test on the Mac.

## The corrected diagnosis

An external analysis document described a "session restoration bug" —
SAM appeared to resume an old, unrelated YouTube task after a restart,
in response to an unrelated new question. Its proposed mechanism (an
explicit `current_task`/`pending_action` object surviving a process
restart) doesn't exist anywhere in this codebase — `ReactLoop`'s
`observations` list is a local variable, gone the moment the process
exits.

The real mechanism, traced through the actual code: Founder Mode's
classifier correctly matched "I want you to open youtube and play X"
against the **decision** pattern (it does state a choice with intent),
and Founder Mode's entire design is to inject captured decisions into
**every future prompt, forever**, via `get_context()` — that's the whole
point of Founder Mode, decisions are meant to persist as taste. But a
one-time task request isn't taste. It got captured at `conf=0.85`
(visible in an earlier log), which meant it sat near the top of "DECISIONS
MADE" in the Brain's context on every subsequent turn, regardless of
relevance. A 7B model, faced with a vague new question and a loud,
high-confidence "decision" about a video sitting right there in context,
leaned on the wrong signal.

## Fix 1 — Founder Mode task_request classification

**`founder_mode/classifier.py`**: added a 5th classification type,
`task_request` — a one-time action instruction ("open an app, play a
video, browse a site, run a command"), explicitly distinguished from
`decision` in the prompt with a concrete test: *"would this still make
sense to show the user next week as 'a decision you made'?"* If it's just
"do this one thing now," it's `task_request`, not `decision`.

**`founder_mode/manager.py`**: `capture_if_relevant()` now has an explicit
branch for `task_request` that does nothing — no decision, no taste, no
rejection gets written. The task itself is still handled correctly by the
normal execution pipeline (`ReactLoop`); it's just never turned into
permanent Founder Mode context. Genuine conversation is still recorded via
episodic memory (`session.save()`, separate from Founder Mode) — so a task
is still *retrievable* if semantically relevant to a later query, it's
just no longer *force-injected* into every unrelated future prompt.

**Verified:** a real decision ("going with FastAPI because...") is still
captured exactly as before — this fix only changes what happens to
one-time task requests, nothing else.

## Cleanup needed on your Mac (one-time, manual)

This code fix does **not** retroactively remove the "Tabahi video" entry
that's already sitting in your live `~/.sam_data/founder_mode/founder_mode.db`
from before this fix. Clean it up with the tool that already exists for
exactly this:
```bash
python sam_cli.py founder-review
```
Find the Tabahi entry and reject it (`n`). This excludes it from context
permanently without deleting the audit record. Didn't build new tooling
for this since `founder-review` already does exactly what's needed.

## Fix 2 — ReAct stagnation detection

**`agent/react_loop.py`**: both `run_task()` and `run_planned_task()` now
call `_is_stagnant()` after every step. If the last 3 consecutive
observations are byte-for-byte identical (the real pattern from testing —
"No content found" repeated verbatim, not a fuzzy near-match), the loop
aborts immediately with a clear explanation instead of burning through all
`MAX_STEPS`. Exact-match on purpose: fuzzy similarity risks false-aborting
on genuinely different steps that happen to read similarly, which is worse
than occasionally missing a near-duplicate.

This is a distinct, higher-level check from Phase 1.5's per-step retry —
retries handle "this one action failed, try again"; stagnation detection
handles "the model keeps choosing *different* actions but getting the
*same* useless result across multiple steps," a different failure mode
entirely.

**Verified:** aborts at exactly 3 repeated identical observations (not
later, not earlier); a genuinely progressing loop (different observation
each step) is confirmed unaffected and completes normally.

## What I did NOT build (per the earlier document's other proposals)

- **Intent Classifier** (a separate upfront conversation-vs-action stage):
  held off — if the corrected diagnosis above is right, the Brain wasn't
  confused about intent in general, it was reacting to bad context. Adding
  a mandatory extra LLM call per turn would also directly work against the
  latency fixes already shipped and tested.
- **Persistent Task Manager**: the diagnosis (Brain confabulating "planner
  tasks" using your real project names) is accurate, but this is a new
  feature, not a bug fix, and the underlying tendency (confabulating about
  untracked internal state) is broader than just planner tasks. Flag if
  you want this scoped as its own phase.
- **Richer browser observations** (DOM/accessibility tree extraction):
  consistent with what was already parked in the earlier architecture
  discussion — real, but heavier scope than this round.

## Offline tests run before packaging

`tests/test_task_request_and_stagnation_offline.py` — 16/16 checks:
classifier accepts `task_request`, a task request captures nothing to
decisions/taste/rejections and never appears in `get_context()`, a
genuine decision is still captured normally (regression guard), stagnation
aborts at exactly 3 repeats with a clear message, a progressing
(non-stagnant) loop is confirmed unaffected, plus direct unit checks on
`_is_stagnant()`'s edge cases (too few observations, empty strings).

Also re-ran all 7 existing suites — no regressions. 89 + 16 = 105 checks
total, all passing.

## Rollback

Three files touched: `founder_mode/classifier.py` (new type added to an
existing enum-like field), `founder_mode/manager.py` (one new early-return
branch), `agent/react_loop.py` (`_is_stagnant()` + 2 call sites). Plus the
new test file. `git diff` against the browser-thread-affinity commit shows
the full blast radius.

## Phase 3 (licensing) — paused, not abandoned

`cryptography` is installed and ready. Say the word to resume — hosting
(you deferred to my judgment) and automation level (manual trigger for v1)
are already locked from before this detour.
