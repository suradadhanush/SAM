# Phase 0 — Founder Mode v2

Status: ready to commit and test on the Mac (real Ollama/Qwen calls).

## What changed

**New file:**
- `founder_mode/classifier.py` — LLM-based extraction. Decoupled from `core/brain.py`
  entirely; makes its own direct call to Ollama. Never touches the main chat pipeline.

**Rewritten:**
- `founder_mode/manager.py` — same public methods as before, fully backward compatible,
  plus:
  - Evidence: every entry keeps the actual user quote(s) that justified it.
  - Confidence: every entry has a 0.0–1.0 score. Manual captures (via `sam_cli.py`)
    default high (0.9). LLM auto-captures start lower and either get **reinforced**
    (same preference stated again → confidence rises, evidence appended) or
    **superseded** (contradicting preference in the same domain → old one excluded
    from live context, but kept in the DB, never deleted).
  - Real reasoning instead of the old placeholder. The old code captured rejections/
    decisions with `reasoning="Auto-captured"` — a fake string, not an actual reason.
    Now a cheap keyword pre-filter gates an LLM call that extracts what the user
    actually said and why. If the LLM classifier can't run (Ollama down, timeout),
    it falls back to the old heuristic — but now with an honest placeholder and a
    low confidence score, instead of pretending it's a real reason.
  - Schema migration (`_migrate_schema`) — runs on every startup, adds the new
    columns to an existing DB via `ALTER TABLE` if they're not already there.
    Verified against a simulated pre-v2 DB: all old rows survive untouched.

**One-line integration change:**
- `main.py` — `FounderModeManager()` → `FounderModeManager(settings=self.settings)`.
  This is the only line touched outside `founder_mode/`. `core/brain.py`,
  `core/session.py`, `agent/react_loop.py`, and every hands/ears/mouth module are
  untouched.

**New settings (all with safe defaults — nothing required in `settings.yaml`):**
```yaml
founder_mode_llm_capture: true          # set false to force the old heuristic-only path
founder_mode_classifier_model: null     # defaults to primary_model if unset
founder_mode_min_confidence_to_show: 0.3
```

**New CLI:**
- `python sam_cli.py founder --all` — shows confidence, source (manual/llm_auto/
  heuristic), and status (active/superseded/rejected_by_user) for everything.
  Without `--all`, only active entries show (matches what the Brain actually sees).
- `python sam_cli.py founder-review` — walks through unconfirmed LLM auto-captures
  one at a time: `y` confirms (bumps confidence to 1.0), `n` rejects (excludes from
  context permanently, but keeps the row for audit), `s` skips, `q` quits.

**Bug fixed (pre-existing, not introduced by this phase):**
- `_get_all()` (used by `export()`) was reading column *index* instead of column
  *name* from `PRAGMA table_info`, which silently corrupted the JSON keys in every
  export. Caught this while writing the offline smoke test below. One-line fix,
  `d[0]` → `d[1]`.

## What did NOT change

- `core/brain.py`, `core/session.py`, `agent/react_loop.py` — zero changes.
- `ears/`, `mouth/`, `hands/`, `skills/` — zero changes.
- The five-part architecture, ReAct loop, memory system — all untouched.
- Every existing `sam_cli.py` command still works exactly as before.

## How to test on the Mac

1. Pull this branch, `pip install -r requirements.txt` if anything's new (nothing
   new was added to `requirements.txt` — no new dependencies).
2. Make sure Ollama is running with `qwen2.5:14b` (or your fallback) pulled.
3. Run `python main.py --text` and have a normal conversation. Somewhere in it,
   say something with a real stance — e.g. "I'm going with FastAPI over Flask
   because I already know it better" or "I don't like that dark mode toggle idea,
   feels like a distraction."
4. After the session, run:
   ```
   python sam_cli.py founder
   ```
   You should see the captured entry with real extracted reasoning (not
   "Auto-captured") and a confidence score/tag.
5. Say a contradicting preference in the same domain later in the same session
   (e.g. "actually switch me to Flask") — run `founder --all` and confirm the old
   one shows `(superseded)` instead of both showing as live, contradicting facts.
6. Run `python sam_cli.py founder-review` and confirm/reject a couple of entries.
7. Kill Ollama (`Ctrl+C` on `ollama serve` or just don't have it running) and try
   step 3 again — confirm SAM doesn't crash, the chat still responds (if Ollama is
   fully down obviously the Brain itself can't respond either — but if you simulate
   just the classifier being slow/unavailable, `main.py`'s try/except around
   `capture_if_relevant` means a Founder Mode failure never takes down the main
   response). This is also covered by the offline smoke test below, which doesn't
   need Ollama at all.

## Offline smoke test (already run, included for your reference)

No Ollama needed — exercises schema creation, migration from a simulated pre-v2 DB,
manual capture, heuristic auto-capture, taste reinforcement, conflict/supersession,
confirm/reject, and export, all in-process. If you want to re-run it yourself on
the phone via Termux before pushing, the logic (not the LLM classifier call itself)
is fully testable without Ollama — ask and I'll hand you the script.

## Rollback

If anything looks wrong on the Mac, this phase touches exactly 4 files
(`founder_mode/manager.py`, `founder_mode/classifier.py` [new], `main.py` [1 line],
`config/settings.py` [3 new fields], `config/settings.yaml` [comment lines],
`sam_cli.py` [founder display + founder-review]). `git diff` against the previous
commit will show the full, small blast radius.
