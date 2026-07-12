# Browser Thread-Affinity Fix — The Deeper Bug Behind the Playwright Crash

Status: ready to commit and test on the Mac.

## Your new log confirmed two things

**The vision (0,0) fix works.** `Vision returned (0,0) for 'force quit Chrome'
— treating as not-found rather than clicking the corner` — exactly the
designed behavior, zero PyAutoGUI crashes from that pattern anymore.

**The concurrency lock wasn't the whole story.** Turn 1 ("open yt and play
the song") worked flawlessly across 6 internal browser steps — proving the
browser works fine *within* one turn. But the very next *separate* message
hit `cannot switch to a different thread` on its first browser call, and
**every browser call for the rest of that session failed identically** —
the tool was permanently dead, not just glitchy.

## Why the lock fix didn't cover this

Last round's lock stops two turns from running *at the same time*. It does
nothing about the fact that `ears/text_input.py` still spawns a **brand
new OS thread for every message**, one after another. Turn 1 runs on
Thread A, which creates the Playwright Page — bound permanently to Thread
A. Thread A finishes and exits. Turn 2 arrives, spawns Thread B. Thread B
tries to reuse Thread A's Page. Thread A is gone. Crash — every time,
forever, for the rest of the session, since nothing ever recreated the
browser.

## A flaw in my first fix attempt, caught by testing before shipping

My first attempt compared `threading.get_ident()` between the thread that
created the browser and the thread calling it now — recreate if they
differ. Reasonable-sounding, but testing it against the *actual* scenario
(Thread A finishes and fully exits, **then** Thread B is created — the
exact sequence in your log, not two threads racing) showed it doesn't
work: once Thread A has completely exited before Thread B starts, the OS
very often **reuses the exact same thread ID** for the new thread. My
proactive check compared the IDs, saw they matched, and concluded
(wrongly) that nothing had changed — so it kept using the dead page and
would have crashed identically. Caught this with a direct test before it
ever reached you.

## The actual fix — react to the real failure, don't predict it

Instead of guessing whether the thread changed, `execute()` now catches
the *exact* error Playwright raises in this situation. If it sees "cannot
switch to a different thread" (or the underlying `greenlet.error`), it
tears down the broken session, creates a fresh one, and **retries the
exact same call once, transparently**. This works correctly no matter why
or when the thread changed — reused ID, mode switch, anything — because it
responds to the symptom Playwright itself reports rather than trying to
infer it in advance. A genuinely different error (bad URL, timeout, real
network failure) is *not* retried — only the specific thread-affinity
signature triggers recovery, so real bugs still surface normally instead
of being silently retried into a longer failure.

The original ID comparison is still there as a cheap fast-path (harmless,
occasionally saves a wasted first attempt), but the actual guarantee comes
from the reactive catch-and-retry, not the proactive check.

## One more piece of evidence this diagnosis is right

Your log shows the Brain itself tried `{'type': 'restart', 'description':
'restart the default web browser'}` at one point — an action that doesn't
exist (`Unknown control action: restart`). The model, on its own,
correctly intuited that the browser needed a restart to recover. It just
had no tool to do it. Now it doesn't need one — recovery happens
automatically and transparently on the very next browser call.

## Offline tests run before packaging

`tests/test_browser_thread_affinity_offline.py` — 10/10 checks:
- Error-signature detection (positive and negative cases).
- The exact real scenario: a stale page raises the real error message on
  its first call, gets caught, recreated, and the same call succeeds on a
  fresh page — verified exactly one attempt on the stale page and exactly
  one retry on the fresh one (not a retry loop).
- A genuinely different error (bad domain) is confirmed to NOT trigger a
  recreate-and-retry cycle — fails normally, as it should.
- If even the recreated browser hits the same error twice in a row (a
  truly broken environment, not just one stale thread), it reports the
  error cleanly instead of looping forever — confirmed exactly 2 attempts
  total, not more.

Also re-ran all 6 existing suites — no regressions. 86 + 10 = 96 checks
total, all passing.

## What's still open from your log (unchanged from last round's scoping)

Still flagged, not addressed this round: intermittent "No content found"
on pages with real content (timing/race condition, needs its own
investigation), and the Brain occasionally reasoning its way to a
plausible-but-wrong action path before correcting itself (a 7B-model
quality question, not a bug). Both noted last round, still accurate.

## Rollback

Two files touched: `hands/browser/playwright_agent.py` (the fix — `_start`,
new `_force_close`, new `_is_thread_affinity_error`, `execute` restructured
to catch-and-retry, new `_do_execute` helper), plus the new test file.
`git diff` against the concurrency-and-vision-fixes commit shows the full
blast radius.
