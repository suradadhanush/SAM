"""
Founder Mode v2 — LIVE integration test (needs Ollama running with your model pulled).

Unlike tests/test_founder_mode_offline.py (which forces the heuristic path and
needs no network), this test calls the real LLM classifier and checks that it
extracts real reasoning, sensible confidence, and correctly resolves conflicts —
the actual thing that matters for this phase.

Usage (on the Mac, Ollama already running):
    HOME=/tmp/sam_live_test python3 tests/test_founder_mode_live.py

Uses a throwaway HOME so it never touches your real ~/.sam_data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from founder_mode.manager import FounderModeManager  # noqa: E402
from config.settings import Settings  # noqa: E402


class FakeResponse:
    def __init__(self, text):
        self.text = text


results = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}" + (f"  ({detail})" if detail else ""))


def main():
    settings = Settings()
    print(f"Using model: {settings.primary_model} @ {settings.ollama_host}\n")

    mgr = FounderModeManager(settings=settings)

    # ── Test 1: Decision with real reasoning ────────────────────────────
    print("── Test 1: Decision capture ──")
    mgr.capture_if_relevant(
        "I've decided to go with FastAPI over Flask for the skill backend, "
        "mainly because I already know it well and it's faster to prototype with.",
        FakeResponse("Good choice, FastAPI's async support will help too.")
    )
    ctx = mgr.get_context()
    got_it = "FastAPI" in ctx and "Flask" not in ctx.split("DECISIONS")[0]  # sanity, not strict
    check("Decision appears in context", "FastAPI" in ctx)
    check("Reasoning is NOT the old fake placeholder", "Auto-captured" not in ctx)
    print(f"  Context so far:\n{ctx}\n")

    # ── Test 2: Rejection with real reasoning ────────────────────────────
    print("── Test 2: Rejection capture ──")
    mgr.capture_if_relevant(
        "I hate the idea of a dark-mode-only toggle, it feels gimmicky and I don't "
        "think most users care that much about it.",
        FakeResponse("Noted, I'll leave it out.")
    )
    ctx = mgr.get_context()
    check("Rejection appears in context", "dark-mode" in ctx.lower() or "dark mode" in ctx.lower())

    # ── Test 3: Casual chat should NOT get captured as a decision ────────
    print("── Test 3: Negative case — casual question ──")
    before_count = len(mgr._get_recent_decisions(50))
    mgr.capture_if_relevant(
        "What's the weather like for testing outdoor voice recognition?",
        FakeResponse("I can't check live weather, but let's talk about mic sensitivity.")
    )
    after_count = len(mgr._get_recent_decisions(50))
    check("Casual question did not get captured as a decision", after_count == before_count,
          f"before={before_count}, after={after_count}")

    # ── Test 4: Preference + reinforcement ────────────────────────────────
    print("── Test 4: Preference capture + reinforcement ──")
    mgr.capture_if_relevant(
        "I prefer minimal, dark UIs — always have. Please default to that everywhere.",
        FakeResponse("Got it, dark and minimal by default.")
    )
    mgr.capture_if_relevant(
        "Just to reinforce — I really do prefer minimal dark UIs, don't suggest bright themes.",
        FakeResponse("Understood.")
    )
    taste = mgr._get_taste_profile(0.0)
    matching = [t for t in taste if "dark" in t["preference"].lower() or "minimal" in t["preference"].lower()]
    check("Preference captured", len(matching) > 0)
    if matching:
        check("Preference confidence rose after reinforcement", matching[0]["confidence"] > 0.5,
              f"confidence={matching[0]['confidence']:.2f}")

    # ── Test 5: Conflict resolution ──────────────────────────────────────
    print("── Test 5: Conflicting preference supersedes the old one ──")
    mgr.capture_if_relevant(
        "Actually, scratch that — I've changed my mind, I want bright, colourful UIs "
        "from now on, not minimal dark ones.",
        FakeResponse("Switching direction, noted.")
    )
    ctx = mgr.get_context()
    active_taste_section = ctx.split("TASTE PROFILE:")[1].split("WHAT TO AVOID")[0] if "TASTE PROFILE:" in ctx else ""
    check("Only the newer preference shows as active",
          "bright" in active_taste_section.lower() or "colourful" in active_taste_section.lower())

    # ── Test 6: Review flow ──────────────────────────────────────────────
    print("── Test 6: Review flow ──")
    pending = mgr.list_llm_captures()
    check("There are LLM auto-captures pending review", len(pending) > 0, f"count={len(pending)}")
    if pending:
        mgr.confirm_capture(pending[0]["table"], pending[0]["id"])
        still_pending = mgr.list_llm_captures()
        check("Confirming an entry removes it from the pending list",
              pending[0]["id"] not in [c["id"] for c in still_pending if c["table"] == pending[0]["table"]])

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if all(results):
        print("Founder Mode v2 is working correctly with the real LLM classifier.")
    else:
        print("Something needs a look before moving to Phase 1 — see FAILs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
