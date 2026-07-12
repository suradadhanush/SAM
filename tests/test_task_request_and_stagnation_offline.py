"""
Offline smoke test for two fixes triggered by a corrected diagnosis of a
"stale task resuming after restart" symptom reported via an external
analysis document:

1. Founder Mode task_request: one-time action instructions ("open youtube
   and play X") were being classified as "decision" and injected into
   EVERY future prompt forever via get_context() -- making a stale task
   look like it "resumed" on a totally unrelated later question. Now
   classified as task_request and explicitly excluded from capture.

2. ReAct stagnation detection: the loop used to burn through all
   MAX_STEPS even when stuck repeating the exact same observation
   ("No content found" x10), seen in real testing. Now aborts after 3
   consecutive identical observations.

Usage:
    HOME=/tmp/sam_smoke_task_stagnation python3 tests/test_task_request_and_stagnation_offline.py
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from founder_mode.manager import FounderModeManager  # noqa: E402
from founder_mode.classifier import classify, UNAVAILABLE  # noqa: E402
from agent.react_loop import ReactLoop  # noqa: E402
from config.settings import Settings  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


def fake_ollama_response(payload_dict):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": json.dumps(payload_dict)}
    return mock_resp


class FakeResp:
    def __init__(self, text, action=None, payload=None):
        self.text, self.action, self.action_payload = text, action, payload


def test_classifier_accepts_task_request_type():
    settings = Settings()
    with patch("founder_mode.classifier.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "type": "task_request",
            "category": "general",
            "domain": "general",
            "statement": "open youtube and play the Tabahi video",
            "reasoning": "no reason given",
            "confidence": 0.85,
        })
        result = classify("open youtube and play the Tabahi video", "Opening YouTube...", settings)
        check("Classifier accepts task_request as a valid type", result["type"] == "task_request")
        check("task_request does not require a statement to stay valid",
              result["type"] == "task_request")  # never downgraded to none for missing statement


def test_task_request_is_never_captured():
    settings = MagicMock()
    settings.founder_mode_llm_capture = True
    settings.incognito = False
    settings.founder_mode_min_confidence_to_show = 0.3

    mgr = FounderModeManager(settings=settings)
    before_decisions = len(mgr._get_recent_decisions(50))
    before_taste = len(mgr._get_taste_profile(0.0))
    before_rejections = len(mgr._get_recent_rejections(50))

    with patch("founder_mode.classifier.classify") as mock_classify:
        mock_classify.return_value = {
            "type": "task_request",
            "category": "general", "domain": "general",
            "statement": "open youtube and play the Tabahi video",
            "reasoning": "no reason given", "confidence": 0.85,
        }
        mgr.capture_if_relevant(
            "okay i want you to open youtube and run the latest tabahi video song",
            FakeResp("Opening YouTube and playing...")
        )

    after_decisions = len(mgr._get_recent_decisions(50))
    after_taste = len(mgr._get_taste_profile(0.0))
    after_rejections = len(mgr._get_recent_rejections(50))

    check("task_request captured NOTHING to decisions", after_decisions == before_decisions)
    check("task_request captured NOTHING to taste_profile", after_taste == before_taste)
    check("task_request captured NOTHING to rejections", after_rejections == before_rejections)

    ctx = mgr.get_context()
    check("Task text never appears in get_context() (would bleed into every future prompt)",
          "tabahi" not in ctx.lower() and "youtube" not in ctx.lower())


def test_real_decision_still_captured_normally():
    """Regression guard: the fix must not break genuine decisions."""
    settings = MagicMock()
    settings.founder_mode_llm_capture = True
    settings.incognito = False
    settings.founder_mode_min_confidence_to_show = 0.3

    mgr = FounderModeManager(settings=settings)
    before = len(mgr._get_recent_decisions(50))

    with patch("founder_mode.classifier.classify") as mock_classify:
        mock_classify.return_value = {
            "type": "decision",
            "category": "architecture", "domain": "general",
            "statement": "Use FastAPI over Flask",
            "reasoning": "already knows it better", "confidence": 0.9,
        }
        mgr.capture_if_relevant(
            "I'm going with FastAPI over Flask because I know it better",
            FakeResp("Good choice.")
        )

    after = len(mgr._get_recent_decisions(50))
    check("A genuine decision is still captured normally", after == before + 1)
    ctx = mgr.get_context()
    check("Genuine decision DOES appear in context", "fastapi" in ctx.lower())


def test_stagnation_aborts_after_repeated_identical_observations():
    settings = Settings()
    react = ReactLoop(settings)

    class RepeatingBrain:
        """Keeps choosing a (different) action each time, but every one
        produces the exact same useless observation -- mirrors the real
        'No content found' x10 pattern from testing."""
        def __init__(self):
            self.calls = 0

        def process(self, session):
            self.calls += 1
            return FakeResp(f"trying approach {self.calls}", action="browser", payload={})

    from core.session import Session
    session = Session(user_input="find the video", identity={}, memories=[],
                       founder_context="", settings=settings)
    brain = RepeatingBrain()

    with patch.object(react, "execute", return_value="No content found"):
        result = react.run_task("find the video", brain, session)

    check("Stagnant loop aborts before MAX_STEPS", brain.calls < 10)
    check("Abort happens at exactly the stagnation window (3), not later",
          brain.calls == 3)
    check("Result message explains the stagnation, not a generic timeout",
          "stuck" in result.lower() or "same result" in result.lower())


def test_non_stagnant_loop_is_unaffected():
    """Regression guard: a loop making real progress (different
    observations each step) must NOT be falsely aborted."""
    settings = Settings()
    react = ReactLoop(settings)

    class ProgressingBrain:
        def __init__(self):
            self.calls = 0

        def process(self, session):
            self.calls += 1
            if self.calls > 4:
                return FakeResp("Done.", action=None)
            return FakeResp(f"step {self.calls}", action="browser", payload={})

    from core.session import Session
    session = Session(user_input="do a multi-step thing", identity={}, memories=[],
                       founder_context="", settings=settings)
    brain = ProgressingBrain()

    call_counter = {"n": 0}

    def varying_execute(action, payload):
        call_counter["n"] += 1
        return f"progress update {call_counter['n']}"  # different every time

    with patch.object(react, "execute", side_effect=varying_execute):
        result = react.run_task("do a multi-step thing", brain, session)

    check("Non-stagnant (progressing) loop completes normally, not falsely aborted",
          result == "Done.")


def test_is_stagnant_helper_directly():
    settings = Settings()
    react = ReactLoop(settings)

    check("Fewer than 3 observations: never stagnant",
          react._is_stagnant([{"observation": "x"}, {"observation": "x"}]) is False)
    check("3 identical observations: stagnant",
          react._is_stagnant([{"observation": "No content found"}] * 3) is True)
    check("3 different observations: not stagnant",
          react._is_stagnant([{"observation": "a"}, {"observation": "b"}, {"observation": "c"}]) is False)
    check("Empty observation strings don't false-trigger stagnation",
          react._is_stagnant([{"observation": ""}] * 3) is False)


def main():
    test_classifier_accepts_task_request_type()
    test_task_request_is_never_captured()
    test_real_decision_still_captured_normally()
    test_stagnation_aborts_after_repeated_identical_observations()
    test_non_stagnant_loop_is_unaffected()
    test_is_stagnant_helper_directly()

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Founder Mode task_request fix and ReAct stagnation detection verified.")


if __name__ == "__main__":
    main()
