# Phase 1 — Planner + Reflection

Status: ready to commit and test on the Mac (real Ollama/Qwen calls).

## What changed

**New files:**
- `agent/planner.py` — Hierarchical Planner. Given a task, calls Ollama once to
  decompose it into 2-8 ordered concrete steps before execution starts. Decoupled
  from `core/brain.py` — its own direct Ollama call, same pattern as
  `founder_mode/classifier.py`. **Fails safe**: returns `None` on any error, bad
  JSON, or HTTP failure — this is a normal, expected outcome, not an error state.
- `agent/reflection.py` — Reflection Engine. After a task finishes, calls Ollama
  once to extract what went well, what went wrong, and one lesson for next time.
  Stored permanently in `~/.sam_data/reflection/reflection.db` — never overwritten,
  same spirit as Founder Mode. Also fails safe: if the LLM call fails, nothing is
  stored, and the task's actual result is completely unaffected.

**Extended (additive only):**
- `agent/react_loop.py`:
  - `run_task()` — **completely unchanged behaviour**, just now also calls
    Reflection at the very end (after the result is already decided, wrapped in
    its own try/except so a reflection failure can never affect what the user
    sees).
  - `run_planned_task()` — **new method**. Calls the Planner first; if a plan
    comes back, executes it step by step; if the Planner returns `None` (Ollama
    down, bad response, etc.), it falls straight through to the original
    `run_task()` — the adaptive step-by-step loop is the fallback, not replaced.
- `config/settings.py` — two new optional fields, both default to `None` (which
  means "reuse `primary_model`"): `planner_model`, `reflection_model`.

## What did NOT change

- `run_task()`'s control flow and return values are identical to before.
- `core/brain.py`, `core/session.py` — zero changes.
- `main.py` — zero changes. **Important**: `ReactLoop.run_task`/`run_planned_task`
  are not currently called anywhere in `main.py` — this was already true before
  Phase 1 (checked: the live chat pipeline in `main.py` doesn't invoke the ReAct
  loop at all yet, single-turn `brain.process()` is all that runs today). So this
  phase cannot regress anything in the live text/voice chat — it only extends a
  module that isn't wired into the main loop yet.
- `ears/`, `mouth/`, `hands/`, `founder_mode/`, `skills/` — zero changes.

## A decision I made without asking, and why

I did **not** wire `ReactLoop.run_planned_task` into `main.py`'s `_process()`.
Doing that would mean SAM starts autonomously executing multi-step actions
(terminal, browser, PyAutoGUI) on ordinary conversation turns — a much bigger
decision than "add a planner," and one that needs real testing against the
actual hands (which need the Mac, and ideally a deliberate decision about *when*
SAM should go autonomous vs. just chat). Planner + Reflection are built, tested,
and ready — wiring them into the live loop is a one-line follow-up whenever
you're ready to test autonomous tasks with real PyAutoGUI/Playwright on the Mac.
Flag if you want that wired now instead.

## How to test on the Mac

1. Pull this branch. No new dependencies — `requests` was already required.
2. With Ollama running, test the Planner directly:
   ```python
   from config.settings import Settings
   from agent import planner
   settings = Settings()
   plan = planner.decompose("Set up a new Python virtual environment and install FastAPI", settings)
   print(plan)
   ```
   You should get back an ordered list of 2-8 steps.
3. Test a full planned task through the ReAct loop (needs a real `Brain` instance
   and the hands available, since steps may trigger real terminal/browser/control
   actions):
   ```python
   from core.brain import Brain
   from core.session import Session
   from agent.react_loop import ReactLoop

   brain = Brain(settings)
   react = ReactLoop(settings)
   session = Session(user_input="", identity={}, memories=[], founder_context="", settings=settings)
   result = react.run_planned_task("Check what Python version is installed", brain, session)
   print(result)
   ```
4. Check the reflection got stored:
   ```bash
   python3 -c "
   from agent.reflection import ReflectionEngine
   from config.settings import Settings
   r = ReflectionEngine(Settings())
   print(r.get_relevant_lessons())
   "
   ```

## Offline test (already run, included for your reference)

`tests/test_phase1_offline.py` — mocks every Ollama call, runs on Termux right
now with zero network dependency. 14/14 checks pass: planner JSON parsing and
all three failure modes (bad JSON, HTTP error, connection error all return
`None` safely), reflection storage + keyword retrieval, the fallback path when
planning fails, and full multi-step planned execution via a fake Brain.

```bash
HOME=/tmp/sam_smoke_test_phase1 python3 tests/test_phase1_offline.py
```

## Rollback

Four files touched: `agent/planner.py` (new), `agent/reflection.py` (new),
`agent/react_loop.py` (extended, `run_task` behaviour identical), `config/settings.py`
(2 new optional fields). `git diff` against the Phase 0 commit shows the full,
small blast radius.
