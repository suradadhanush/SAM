# Concurrency Fix + Vision (0,0) Fix — Root Causes From Real Testing

Status: ready to commit and test on the Mac. Two real bugs fixed, two more
identified and explicitly scoped out for now — read the "not fixed" section
before assuming everything in the log is resolved.

## The big one: unsynchronized concurrent execution

**What the log showed:** you typed "stop it" while "open youtube" was still
running — it didn't stop anything, and a few messages later "cannot switch
to a different thread (which happens to have exited)" crashed the browser
mid-task.

**Root cause, confirmed by reading the actual code, not guessed:**
`ears/text_input.py` fires a **brand new, completely unsynchronized daemon
thread for every single line you type** (`ears/wake_word.py` does the same
for every wake-word trigger). There was no lock, no queue — nothing
stopping two calls to `main.py`'s `_process()` from running at the exact
same time on two different threads.

Both of those concurrent calls share the same `ReactLoop`, and critically,
the same cached Playwright `Page` object (`hands/browser/playwright_agent.py`
creates it once and reuses it for the process's lifetime). Playwright's
**sync API is bound to whichever OS thread created it** — it is not safe to
call from a different thread. When your second message ("stop it") spawned
a new thread that tried to touch the same Page a now-finished daemon thread
had created, that's exactly the "cannot switch to a different thread"
crash. This wasn't a Playwright bug or a fluke — it was two of your own
threads racing on state that was never meant to be shared across threads.

**Fixed:** `main.py._process()` is now wrapped in a `threading.Lock`. This
is the single point both text input and voice input converge on, so one
lock there protects both input sources with one change, instead of patching
`text_input.py` and `wake_word.py` separately (which would still leave a
gap if voice and text were ever both active). If a new message arrives
while one's still processing, you now see:
```
[SAM] Still working on your previous request — this will run right after it finishes.
```
instead of silent, unsynchronized chaos. Verified against the *exact*
3-message-rapid-fire scenario from your log (open youtube / stop it / now
continue) — confirmed strictly sequential now, zero concurrent execution.

**What this does NOT do:** it does not make "stop it" actually interrupt a
task that's already running. It queues "stop it" to run *after* the current
task finishes, instead of racing it. True mid-task cancellation — actually
aborting an in-flight Ollama call or PyAutoGUI action — is a real,
separate feature (needs a cancellation token threaded through the ReAct
loop, checked between steps, plus a way to abort a blocking HTTP request).
Flag if you want that scoped next; I didn't want to bundle a half-built
interrupt system into a bug-fix round.

## Vision returning (0,0) as a non-answer, not a real location

**What the log showed:** `Found 'play the video' at normalized (0.000,
0.000) -> pixel (0, 0)` — repeatedly, for completely different UI elements
("play the video", "WhatsApp icon", "YouTube icon in Dock"). Every one
triggered the same PyAutoGUI corner fail-safe crash.

**Root cause:** the coordinate *scaling* fix from the last round was
correct — but it exposed a deeper issue. Moondream itself was answering
`{"x": 0.0, "y": 0.0}` when it genuinely couldn't find the element, instead
of the `{"x": null, "y": null}` it was explicitly told to return in that
case. This is a well-documented failure pattern in vision-language models —
collapsing to a degenerate default answer (often the origin) rather than
admitting uncertainty, even when told exactly how to. No amount of prompt
wording fixes this reliably.

**Fixed:** `find_element()` now treats an exact `(0.0, 0.0)` result as
"not found" and returns `None` — the same as if the model had honestly
returned null. No real on-screen element is ever at the literal top-left
corner pixel in practice, so this is a safe, defensible check. Converts a
guaranteed crash into a clean, retryable "could not find X" — exactly what
the Verifier (Phase 1.5) was built to handle gracefully. Verified this
doesn't over-correct: a genuinely near-corner element like `(0.02, 0.03)`
still resolves correctly to a real pixel location.

## What I found but did NOT fix this round — flagging honestly

**"No content found" appearing intermittently on real pages with real
content.** Step 2 and 3 in your log got "No content found" navigating to a
YouTube search page, while step 4 — the same kind of navigation — correctly
extracted real text ("Tabaahi 🔥 - Toxic (Telugu)..."). This smells like a
timing/race condition in `_extract_content()` — reading `document.body.
innerText` before a JS-rendered page has actually finished populating.
Needs investigation into `playwright_agent.py`'s wait conditions before a
real fix, not a guess bolted on. Flag if you want this picked up next.

**The Brain hallucinating a fake video URL.** Step 6 tried to navigate to
`youtube.com/watch?v=your_video_id` — a literal placeholder string, not a
real ID, even though step 4's observation already contained the real video
title in the page text. This is a reasoning-quality limitation: the browser
tool hands the Brain raw scraped text, and a 7B model extracting a specific
real ID out of unstructured text reliably is a genuinely hard ask. A better
fix would give the Brain structured link data (actual `href` values, not
just visible text) — real scope, not a one-line patch.

**Your workaround request (open the YouTube desktop app via Finder/Dock
instead of the browser)** didn't actually help, and now we know exactly
why: Dock icon clicks go through the *same* vision `find_element()` path
that was returning `(0,0)`, so it hit the identical bug, just via a
different action type. The vision fix above should make that path work
correctly too — worth re-testing specifically.

## Offline tests run before packaging

`tests/test_concurrency_and_vision_fixes_offline.py` — 7/7 checks, zero
Ollama/network needed. Reproduces the exact 3-message rapid-fire scenario
from your real log and confirms strict serialization; reproduces the exact
`(0.0, 0.0)` response and confirms it's now rejected, plus two sanity
checks confirming legitimate near-corner and normal coordinates are
unaffected.

Also re-ran all 5 existing suites (Phase 0, 1, 1.5, 2, latency fixes) — no
regressions. 76 + 7 = 83 checks total, all passing.

## Rollback

Three files touched: `main.py` (the lock — `_process()`'s logic itself is
unchanged, just wrapped), `hands/vision/screen_reader.py` (the `(0,0)`
check, ~10 lines), `tests/test_concurrency_and_vision_fixes_offline.py`
(new). `ears/text_input.py` and `ears/wake_word.py` were **not** touched —
the fix lives at the single point they both converge on instead.
`git diff` against the latency-fixes commit shows the full blast radius.
