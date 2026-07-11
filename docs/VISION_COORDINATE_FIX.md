# Vision Coordinate Fix + Diagnosis of Your First Real Execution Run

Status: ready to commit and test on the Mac.

## Headline: the wiring works

Your log shows the full pipeline firing correctly for the first time — Planner
created a real 7-step plan, the Verifier's retry logic fired exactly as
designed (`attempt 1: FAILED (decision=retry)` → `attempt 2 (retry)`),
Playwright actually opened a browser and navigated to YouTube, and a
Reflection got stored and bridged into Founder Mode at 0.80 confidence. That's
every phase we've built, working together, on a real 7B model. Good sign.

## The bug I fixed: every click aimed at (0,0)

Your log's real symptom: `PyAutoGUI fail-safe triggered from mouse moving to
a corner of the screen`, repeatedly, plus `Clicked (0, 0)` on the one attempt
that didn't crash.

Root cause, found in `hands/vision/screen_reader.py`: Moondream (your vision
model) returns **normalized coordinates** — fractions between 0.0 and 1.0 —
for pointing tasks. Your log even shows it working correctly:
`Found 'open YouTube' at (0.17, 0.18)`. But the old code did `int(x), int(y)`
directly on those fractions. `int(0.17)` is `0`. `int(0.18)` is `0`. Every
single click target silently collapsed to the literal top-left pixel —
which is exactly the corner PyAutoGUI's own fail-safe exists to catch. Nothing
was ever "accidentally" moving to a corner; it was being told to, every time.

**Fixed:** `find_element()` now scales normalized coordinates by the real
screen size (via `pyautogui.size()`, already a dependency — no new install)
before returning them. `(0.17, 0.18)` on a 1920×1080 screen now correctly
becomes `(326, 194)`, not `(0, 0)`. Verified against the exact values from
your log.

**Also fixed while I was in there:** two of your log's other errors —
`Unterminated string starting at...` and `Expecting value: line 1 column
1961` — are the vision model occasionally returning slightly malformed JSON
(likely cut off, or with stray text around it). `_parse_coordinates()` now
tries strict JSON first, and falls back to a regex scan for `"x": ...` /
`"y": ...` if that fails, instead of giving up and forcing a retry. Reduces
wasted attempts, doesn't change behavior when the JSON is already clean.

## What I did NOT fix — flagging, not fixing, per your existing docs

These are real issues visible in your log, but each is either an environment
fact I can't fix remotely, or a separate scoped decision. Listed in rough
priority order:

1. **`could not create image from display` (step 1, very first attempt)** —
   this is almost certainly macOS not having granted **Screen Recording**
   permission to your terminal app yet. Go to System Settings → Privacy &
   Security → Screen Recording, add/enable your terminal (Terminal.app,
   iTerm2, whichever you're using), then **fully quit and reopen the
   terminal app** — macOS requires a restart of the app after granting this,
   not just re-running the script. This is exactly the kind of runtime/
   permission fact I flagged in the execution wiring doc as something I
   can't verify or grant from here.

2. **The Brain chose blind desktop-clicking (`control`) as its first 4
   attempts, instead of just using the `browser` action directly** — wasted
   ~15 seconds and 4 failed attempts before it correctly switched to
   Playwright on step 5. This is a prompt/system-prompt issue in
   `core/brain.py` — it doesn't currently give the model a clear heuristic
   like "prefer `browser` for any website/video task; only use `control` for
   local desktop apps unreachable by URL." Worth fixing, but it's a
   `core/brain.py` change — I didn't touch that file in this pass since you
   asked specifically about eyes/mouth/ears/hands, not the Brain's prompt.
   Flag if you want this tightened next.

3. **`Unknown control action: close_tab`** — the Brain invented a control
   subtype that `hands/control/controller.py` doesn't implement (only
   click/type/etc. exist). Same root cause as #2 — the system prompt doesn't
   constrain the model to the actual supported action vocabulary. Fixing #2
   properly would likely fix this too.

4. **Reflection's lessons aren't fed back into the Brain's next prompt yet.**
   Your log shows a genuinely good, specific lesson getting stored ("Ensure
   the mouse is not moved to corners...") — but nothing currently calls
   `ReflectionEngine.get_relevant_lessons()` when building the Brain's prompt.
   Right now lessons are being written, never read. This is a real
   opportunity (the whole point of Reflection is informing future attempts)
   but it's a `core/brain.py` prompt-assembly change, scoped separately from
   this fix.

5. **Kokoro/Piper still failing every turn**, falling through to macOS `say`
   (which appears to succeed — no error logged for it, and you'd have heard
   nothing at all if `say` also failed). Not urgent, unrelated to execution.

I'd rank fixing **#2 first** if you want the next round of testing to look
cleaner — right now roughly half of every task's steps are wasted on the
Brain trying `control` when `browser` was the right tool from the start.

## Offline tests run before packaging

- Reproduced the exact bug: `_to_pixel_coords(0.17, 0.18)` on a 1920×1080
  screen now returns `(326, 194)`, confirmed `!= (0, 0)`.
- Confirmed `(0.5, 0.5)` correctly maps to screen center `(960, 540)`.
- Reproduced the exact truncated-JSON pattern from your log
  (`{"x": 0.34, "y": 0.5` — missing closing brace) and confirmed the regex
  fallback recovers `(0.34, 0.5)` instead of failing.
- Confirmed clean JSON and the "not found" (`null`/`null`) case still work
  exactly as before.
- Re-ran all three existing offline suites (Phase 0, 1, 1.5) — no
  regressions, 22+14+10 checks still passing.
- Confirmed the full import chain still constructs cleanly.

## Rollback

One file touched: `hands/vision/screen_reader.py`. `git diff` against the
execution-wiring commit shows the full, single-file blast radius.
