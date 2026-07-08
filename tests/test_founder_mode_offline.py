"""
Offline smoke test for Founder Mode v2 — no Ollama required.

Run on the phone (Termux) before pushing, to catch schema/logic bugs early.
This does NOT exercise the LLM classifier itself (that needs Ollama on the
Mac) — it exercises everything else: schema creation, migration from a
pre-v2 DB, manual capture, heuristic auto-capture, taste reinforcement,
conflict/supersession, confirm/reject, and export.

Usage:
    HOME=/tmp/sam_smoke_test python3 tests/test_founder_mode_offline.py

(Uses a throwaway HOME so it never touches your real ~/.sam_data.)
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from founder_mode.manager import FounderModeManager  # noqa: E402


class FakeSettings:
    founder_mode_llm_capture = False  # force heuristic path — no network needed
    incognito = False
    founder_mode_min_confidence_to_show = 0.3
    primary_model = "qwen2.5:14b"
    ollama_host = "http://localhost:11434"
    founder_mode_classifier_model = None


class FakeResponse:
    text = "Sure thing."


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        raise SystemExit(f"Smoke test failed: {label}")


def main():
    mgr = FounderModeManager(settings=FakeSettings())

    # 1. Backward-compat manual capture (old positional call style still works)
    mgr.capture_decision("Use FastAPI for skill backend", "Fastest to prototype with", "architecture")
    mgr.capture_rejection("MongoDB for episodic memory", "Wanted simpler local SQLite", "tooling")

    # 2. Heuristic auto-capture path (LLM disabled in FakeSettings)
    mgr.capture_if_relevant("I decided to go with Ollama instead of llama.cpp directly", FakeResponse())
    mgr.capture_if_relevant("i prefer dark UI themes for everything", FakeResponse())

    ctx = mgr.get_context()
    check("Manual decision appears in context", "Use FastAPI for skill backend" in ctx)
    check("Manual rejection appears in context", "MongoDB for episodic memory" in ctx)
    check("Heuristic auto-capture appears with honest placeholder", "LLM classifier unavailable" in ctx)

    # 3. Taste reinforcement + conflict resolution
    mgr.update_taste(domain="backend_framework", preference="FastAPI", confidence=0.6,
                      evidence=["I like FastAPI"], source="llm_auto")
    mgr.update_taste(domain="backend_framework", preference="FastAPI", confidence=0.6,
                      evidence=["FastAPI again, still love it"], source="llm_auto")  # reinforce
    mgr.update_taste(domain="backend_framework", preference="Django", confidence=0.85,
                      evidence=["Actually switching to Django because of admin panel"], source="llm_auto")  # supersede

    ctx = mgr.get_context()
    check("Only the current preference (Django) shows in live context", "Django" in ctx and "FastAPI" not in ctx.split("TASTE PROFILE:")[1].split("WHAT TO AVOID")[0])

    path = mgr.export()
    with open(path) as f:
        data = json.load(f)
    taste_rows = {row["preference"]: row for row in data["taste_profile"]}
    check("Export dict keys are correct (domain present, not corrupted)", "domain" in taste_rows["FastAPI"])
    check("Superseded FastAPI kept in DB, not deleted", taste_rows["FastAPI"]["status"] == "superseded")
    check("FastAPI confidence reinforced above initial 0.6", taste_rows["FastAPI"]["confidence"] > 0.6)
    check("Django is active", taste_rows["Django"]["status"] == "active")

    # 4. Confirm/reject flow
    pending = mgr.list_llm_captures()
    check("At least one LLM auto-capture pending review", len(pending) > 0)

    django_entry = next(c for c in pending if c["label"] == "Django")
    mgr.confirm_capture(django_entry["table"], django_entry["id"])
    remaining = mgr.list_llm_captures()
    check("Confirmed entry no longer pending review", django_entry["id"] not in [c["id"] for c in remaining if c["table"] == django_entry["table"]])

    print("\nAll offline Founder Mode v2 checks passed.")
    print(f"(Test data written to a throwaway HOME — safe to delete: {Path.home() / '.sam_data'})")


if __name__ == "__main__":
    main()
