# Phase 1.5 — Verification Engine + Reflection Upgrade

Status: ready to commit and test on the Mac.

Scope, exactly as locked: 2 of the 12 items from the "SAM Phase 2 Architecture
Evolution" document — everything else in that doc (Capability Router, Model
Router, LSP, Plugin Framework, Scheduler, Device Manager, etc.) stays parked at
its already-agreed phase number and was not touched.

## What changed

**New file:**
- `agent/verifier.py` — `TaskResult` dataclass (`success`, `confidence`, `logs`,
  `artifacts`, `execution_time`, `errors`) + `Verifier.decide()`: accept / retry /
  abort. Heuristic-based by default (matches known failure strings your own
  executors already produce) — no extra LLM call per step, so latency is
  unchanged. **No auto-repair** — a retry always re-runs the identical action
  and payload; it never has the LLM guess a different command. Two failures =
  abort that step, full stop.

**Extended (additive only):**
- `agent/react_loop.py`:
  - New `_execute_verified()` helper — wraps a single action execution with the
    Verifier, retries exactly once on failure, and always records both attempts.
  - `run_task()` and `run_planned_task()` now call `_execute_verified()` instead
    of `execute()` directly. Their control flow, return values, and MAX_STEPS
    behaviour are otherwise identical to Phase 1.
  - `ReactLoop.__init__` gained one new optional parameter: `founder_mode=None`.
    `ReactLoop(settings)` — the old call — still works exactly as before.
- `agent/reflection.py`:
  - `reflect()` now computes `mistakes` and `execution_metrics` (step count,
    total attempts, retry count, failed steps) **directly from the real step
    data**, not asked from the LLM — exact numbers, not a guess.
  - New optional `founder_mode` parameter. When passed and the reflection's
    confidence is **≥ 0.8**, the lesson is written into Founder Mode via the
    existing `capture_decision()` method, tagged `source="reflection"` and
    `category="reflection"`. Below 0.8, nothing is bridged. Omit `founder_mode`
    entirely and `reflect()` behaves exactly as it did in Phase 1.
  - Schema migration (`_migrate_schema`) adds `mistakes_json` and
    `execution_metrics_json` columns to the existing `reflections` table —
    verified against a live-created Phase 1 database, nothing lost.

## What did NOT change

- `run_task()`/`run_planned_task()` return values and overall behaviour on the
  success path — identical to Phase 1. The only visible difference is a failed
  step now gets one automatic retry before giving up, instead of failing
  immediately.
- `core/brain.py`, `core/session.py`, `main.py` — zero changes. (Same as Phase 1:
  `ReactLoop` still isn't wired into the live chat pipeline — this phase extends
  a module that isn't yet in the main loop, so it can't regress live chat.)
- `founder_mode/manager.py` — zero changes. The bridge calls the existing
  `capture_decision()` method exactly as `sam_cli.py` already does; no new
  Founder Mode code was needed.
- `ears/`, `mouth/`, `hands/`, `skills/` — zero changes.

## How to test on the Mac

1. Pull this branch. No new dependencies.
2. Force a failure to see the retry in action — e.g. give the Brain a task that
   references a nonexistent screen element, then check the logs:
   ```bash
   grep "attempt 1\|attempt 2 (retry)" logs/sam.log | tail -10
   ```
   You should see `attempt 1: FAILED (decision=retry)` followed by
   `attempt 2 (retry): ...`.
3. Check a reflection picked up the retry data:
   ```python
   from agent.reflection import ReflectionEngine
   from config.settings import Settings
   r = ReflectionEngine(Settings())
   print(r.get_relevant_lessons())
   ```
4. To see the Founder Mode bridge fire, construct `ReactLoop` with `founder_mode`
   passed in (this is opt-in — main.py doesn't do this automatically yet):
   ```python
   from agent.react_loop import ReactLoop
   from founder_mode.manager import FounderModeManager
   from config.settings import Settings
   settings = Settings()
   fm = FounderModeManager(settings=settings)
   react = ReactLoop(settings, founder_mode=fm)
   # ...run a task through react.run_planned_task(...)...
   ```
   Then `python sam_cli.py founder --all` and look for `source: reflection`
   entries.

## Offline test (already run, included for your reference)

`tests/test_phase15_offline.py` — 22/22 checks pass, zero Ollama needed. Covers:
Verifier accept/retry/abort logic, the retry-then-succeed and abort-after-2-
failures paths through `_execute_verified` (using a mocked `execute()`),
mistake/metric computation from real step data, schema migration, the Founder
Mode bridge firing above 0.8 confidence and correctly NOT firing below it, and
full backward compatibility when `founder_mode` is omitted.

```bash
HOME=/tmp/sam_smoke_test_phase15 python3 tests/test_phase15_offline.py
```

Also re-ran the Phase 0 and Phase 1 offline tests — no regressions.

## Rollback

Three files touched: `agent/verifier.py` (new), `agent/reflection.py` (extended,
old behaviour preserved when `founder_mode` is omitted), `agent/react_loop.py`
(extended, `run_task`/`run_planned_task` success-path behaviour unchanged).
`git diff` against the Phase 1 commit shows the full blast radius.
