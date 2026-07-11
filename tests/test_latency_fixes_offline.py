"""
Offline smoke test for the three latency fixes (post-Phase-2 optimization
round) — no Ollama or live TTS engines required.

Fix #1: eliminate the redundant Brain call (initial_response reuse)
Fix #2: TTS stops retrying engines that already failed this session
Fix #4: skip the Planner's LLM call entirely for single-step tasks

Usage:
    HOME=/tmp/sam_smoke_latency python3 tests/test_latency_fixes_offline.py
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings  # noqa: E402
from core.session import Session  # noqa: E402
from agent.react_loop import ReactLoop  # noqa: E402
from mouth.tts import TextToSpeech  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


class FakeResp:
    def __init__(self, text, action=None, payload=None):
        self.text, self.action, self.action_payload = text, action, payload


def test_multistep_heuristic():
    settings = Settings()
    react = ReactLoop(settings)

    single_step = ["open youtube", "what is the weather today",
                   "list files in this folder", "click the submit button"]
    multi_step = [
        "open youtube and play the song and then open whatsapp",
        "first check my email, then reply to the latest one",
        "download the file, after that extract it",
        "open the terminal; then run git pull",
        "open youtube and play telugu tabahi song from the movie TOXIC and then open whatsapp",
    ]

    for t in single_step:
        check(f"Single-step detected correctly: '{t}'", react._looks_multi_step(t) is False)
    for t in multi_step:
        check(f"Multi-step detected correctly: '{t[:40]}...'", react._looks_multi_step(t) is True)


def test_zero_extra_calls_when_task_already_resolved():
    settings = Settings()
    react = ReactLoop(settings)

    class CountingBrain:
        def __init__(self):
            self.calls = 0

        def process(self, session):
            self.calls += 1
            return FakeResp("should not be called", action=None)

    session = Session(user_input="open youtube", identity={}, memories=[],
                       founder_context="", settings=settings)
    brain = CountingBrain()
    initial_response = FakeResp("Opening YouTube now.", action=None)

    result = react.run_planned_task("open youtube", brain, session, initial_response=initial_response)
    check("Simple resolved single-step task makes ZERO extra Brain calls", brain.calls == 0)
    check("Result text matches the reused initial_response", result == "Opening YouTube now.")


def test_one_extra_call_when_action_needs_completion_check():
    settings = Settings()
    react = ReactLoop(settings)

    class CountingBrain:
        def __init__(self):
            self.calls = 0

        def process(self, session):
            self.calls += 1
            return FakeResp("Done.", action=None)

    session = Session(user_input="open youtube", identity={}, memories=[],
                       founder_context="", settings=settings)
    brain = CountingBrain()
    initial_response = FakeResp("Opening YouTube now.", action="browser",
                                 payload={"url": "https://youtube.com"})

    with patch.object(react, "execute", return_value="Opened successfully"):
        result = react.run_planned_task("open youtube", brain, session, initial_response=initial_response)

    check("Action from initial_response executed without an extra call for it, "
          "only 1 completion-check call needed", brain.calls == 1)
    check("Final result reflects real execution outcome", result == "Done.")


def test_multistep_task_still_plans_and_reuses_first_step():
    settings = Settings()
    react = ReactLoop(settings)

    class SequenceBrain:
        def __init__(self):
            self.calls = 0

        def process(self, session):
            self.calls += 1
            return FakeResp(f"step response {self.calls}", action=None)

    session = Session(user_input="open youtube and then open whatsapp", identity={},
                       memories=[], founder_context="", settings=settings)
    brain = SequenceBrain()
    initial_response = FakeResp("Opening YouTube.", action="browser", payload={})
    fake_plan = [{"step": 1, "description": "Open YouTube"},
                 {"step": 2, "description": "Open WhatsApp"}]

    with patch("agent.planner.decompose", return_value=fake_plan):
        with patch.object(react, "execute", return_value="done"):
            react.run_planned_task(
                "open youtube and then open whatsapp", brain, session,
                initial_response=initial_response
            )

    check("Multi-step task still calls Planner and only needs 1 extra Brain "
          "call (step 2) since step 1 reused initial_response", brain.calls == 1)


def test_tts_skips_known_bad_engines():
    class FakeSettings:
        tts_engine = "kokoro"
        kokoro_voice = "af_bella"
        speech_rate = 1.0
        piper_model = "en_US-lessac-medium"

    tts = TextToSpeech(FakeSettings())
    call_log = []

    def fake_kokoro(text):
        call_log.append("kokoro")
        raise RuntimeError("Kokoro produced no audio")

    def fake_piper(text):
        call_log.append("piper")
        raise RuntimeError("Piper not found in PATH")

    def fake_system(text):
        call_log.append("system")

    with patch.object(tts, "_speak_kokoro", new=fake_kokoro), \
         patch.object(tts, "_speak_piper", new=fake_piper), \
         patch.object(tts, "_speak_system", new=fake_system):

        tts.speak("hello")
        check("Turn 1: all engines tried in order", call_log == ["kokoro", "piper", "system"])

        call_log.clear()
        tts.speak("hello again")
        check("Turn 2: broken engines skipped, only working one tried",
              call_log == ["system"])


def main():
    test_multistep_heuristic()
    test_zero_extra_calls_when_task_already_resolved()
    test_one_extra_call_when_action_needs_completion_check()
    test_multistep_task_still_plans_and_reuses_first_step()
    test_tts_skips_known_bad_engines()

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Latency fixes verified: redundant Brain call eliminated, "
          "TTS engine retry waste eliminated, Planner skipped for single-step tasks.")


if __name__ == "__main__":
    main()
