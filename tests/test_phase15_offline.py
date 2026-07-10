"""
Offline smoke test for Phase 1.5 (Verification Engine + Reflection upgrade)
— no Ollama required. Mocks requests.post and ReactLoop.execute() to test
the retry/abort logic, mistake/metric computation, schema migration, and
the Founder Mode bridge, all without any network dependency.

Usage:
    HOME=/tmp/sam_smoke_test_phase15 python3 tests/test_phase15_offline.py
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.verifier import Verifier, TaskResult  # noqa: E402
from agent.reflection import ReflectionEngine  # noqa: E402
from agent.react_loop import ReactLoop  # noqa: E402
from founder_mode.manager import FounderModeManager  # noqa: E402
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


class FakeBrainResponse:
    def __init__(self, text, action=None, action_payload=None):
        self.text = text
        self.action = action
        self.action_payload = action_payload


class FakeSession:
    def __init__(self):
        self.user_input = ""


def main():
    settings = Settings()

    # ── Test 1: Verifier accepts a clean success ─────────────────────────
    v = Verifier(settings)
    result = v.verify("terminal", {"command": "ls"}, "Ran: ls -> file1 file2", 0.2)
    check("Verifier accepts a normal success observation", result.success and result.confidence >= 0.8)
    check("decide() returns 'accept' for a success", v.decide(result, already_retried=False) == "accept")

    # ── Test 2: Verifier detects failure signals ─────────────────────────
    result_fail = v.verify("control", {"type": "click"}, "Could not find 'Submit button' on screen", 0.1)
    check("Verifier detects a known failure signal", not result_fail.success)
    check("decide() returns 'retry' on first failure", v.decide(result_fail, already_retried=False) == "retry")
    check("decide() returns 'abort' on second failure", v.decide(result_fail, already_retried=True) == "abort")

    # ── Test 3: Verifier never raises, even on garbage input ──────────────
    weird = v.verify("terminal", {}, None, 0.0)
    check("Verifier never raises on None observation", weird is not None)

    # ── Test 4: ReactLoop._execute_verified retries once then succeeds ────
    react = ReactLoop(settings)
    call_log = []

    def fake_execute(action, payload):
        call_log.append(1)
        if len(call_log) == 1:
            return "Error executing terminal: command not found"
        return "Ran successfully: output here"

    with patch.object(react, "execute", side_effect=fake_execute):
        verified = react._execute_verified("terminal", {"command": "foo"}, "test step")
        check("Retries exactly once then succeeds", verified["success"] is True and len(verified["attempts"]) == 2)
        check("First attempt recorded as failed", verified["attempts"][0]["success"] is False)
        check("Second attempt recorded as succeeded", verified["attempts"][1]["success"] is True)

    # ── Test 5: ReactLoop._execute_verified aborts after 2 failures ───────
    react2 = ReactLoop(settings)
    with patch.object(react2, "execute", return_value="Error executing terminal: still broken"):
        verified2 = react2._execute_verified("terminal", {"command": "bar"}, "test step 2")
        check("Aborts (no 3rd attempt) after 2 failures", verified2["success"] is False and len(verified2["attempts"]) == 2)

    # ── Test 6: Reflection computes mistakes/metrics from real step data ──
    steps_with_attempts = [
        {"step": 1, "action": "terminal", "observation": "ok",
         "attempts": [{"attempt": 1, "success": False, "errors": ["not found"]},
                      {"attempt": 2, "success": True, "errors": []}]},
        {"step": 2, "action": "browser", "observation": "ok",
         "attempts": [{"attempt": 1, "success": True, "errors": []}]},
    ]
    mistakes, metrics = ReflectionEngine._compute_mistakes_and_metrics(steps_with_attempts)
    check("Computed exactly 1 mistake from real attempt data", len(mistakes) == 1)
    check("Computed retry_count == 1", metrics["retry_count"] == 1)
    check("Computed step_count == 2", metrics["step_count"] == 2)

    # ── Test 7: Reflection stores mistakes/metrics + migration works ──────
    reflection = ReflectionEngine(settings=settings)
    with patch("agent.reflection.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "went_well": "Recovered after one retry",
            "went_wrong": "First terminal command failed",
            "lesson": "Always check the working directory before running the command",
            "confidence": 0.85,
        })
        result = reflection.reflect(task="run a script", steps=steps_with_attempts, outcome="Succeeded")
        check("Reflection with attempts data stores successfully", result is not None)
        check("Reflection includes computed mistakes", len(result["mistakes"]) == 1)
        check("Reflection includes computed execution_metrics", result["execution_metrics"]["retry_count"] == 1)

    # Verify it's actually persisted with the new columns (migration check)
    import sqlite3
    with sqlite3.connect(reflection.db_path()) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(reflections)").fetchall()}
        check("mistakes_json column exists after migration", "mistakes_json" in cols)
        check("execution_metrics_json column exists after migration", "execution_metrics_json" in cols)
        row = conn.execute("SELECT mistakes_json, execution_metrics_json FROM reflections ORDER BY id DESC LIMIT 1").fetchone()
        check("Stored mistakes_json is valid JSON with 1 entry", len(json.loads(row[0])) == 1)

    # ── Test 8: Founder Mode bridge fires on high confidence ──────────────
    fm = FounderModeManager(settings=settings)
    before = len(fm._get_recent_decisions(50))
    with patch("agent.reflection.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "went_well": "Task went smoothly",
            "went_wrong": "nothing notable",
            "lesson": "Prefer running installs in a virtualenv",
            "confidence": 0.9,  # above FOUNDER_BRIDGE_MIN_CONFIDENCE
        })
        reflection.reflect(task="install a package", steps=[], outcome="done", founder_mode=fm)
    after = len(fm._get_recent_decisions(50))
    check("High-confidence reflection bridged into Founder Mode", after == before + 1)

    # ── Test 9: bridge does NOT fire on low confidence ────────────────────
    before2 = len(fm._get_recent_decisions(50))
    with patch("agent.reflection.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "went_well": "ok", "went_wrong": "ok",
            "lesson": "A weak, low-confidence lesson",
            "confidence": 0.5,  # below threshold
        })
        reflection.reflect(task="minor task", steps=[], outcome="done", founder_mode=fm)
    after2 = len(fm._get_recent_decisions(50))
    check("Low-confidence reflection does NOT bridge into Founder Mode", after2 == before2)

    # ── Test 10: reflect() with no founder_mode still works exactly as before ──
    with patch("agent.reflection.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "went_well": "fine", "went_wrong": "fine", "lesson": "Some lesson", "confidence": 0.95
        })
        result_no_fm = reflection.reflect(task="x", steps=[], outcome="y")  # no founder_mode arg
        check("reflect() with no founder_mode arg still works (backward compatible)", result_no_fm is not None)

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Phase 1.5 (Verification Engine + Reflection upgrade) offline logic verified.")


if __name__ == "__main__":
    main()
