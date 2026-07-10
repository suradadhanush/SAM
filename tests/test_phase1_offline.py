"""
Offline smoke test for Phase 1 (Planner + Reflection) — no Ollama required.

Mocks requests.post so planner.decompose() and ReflectionEngine.reflect()
parsing/validation logic is tested without any network dependency. Also
exercises the full ReactLoop.run_planned_task() orchestration (planning ->
step execution -> reflection, and the fallback path when planning fails)
using a FakeBrain so nothing here needs the Mac or Ollama.

Usage:
    HOME=/tmp/sam_smoke_test_phase1 python3 tests/test_phase1_offline.py
"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import planner  # noqa: E402
from agent.reflection import ReflectionEngine  # noqa: E402
from agent.react_loop import ReactLoop  # noqa: E402
from config.settings import Settings  # noqa: E402

results = []


def check(label, condition):
    status = "PASS" if condition else "FAIL"
    results.append(condition)
    print(f"[{status}] {label}")


def fake_ollama_response(payload_dict):
    """Builds a mock requests.Response-like object returning the given dict
    as Ollama's {"response": "<json string>"} envelope."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": json.dumps(payload_dict)}
    return mock_resp


class FakeBrainResponse:
    def __init__(self, text, action=None, action_payload=None):
        self.text = text
        self.action = action
        self.action_payload = action_payload


class FakeBrain:
    """Deterministic brain — returns a canned 'no action needed' response
    for every step, so run_planned_task's loop terminates predictably."""
    def process(self, session):
        return FakeBrainResponse(text=f"Handled: {session.user_input[:40]}", action=None)


class FakeSession:
    def __init__(self):
        self.user_input = ""


def main():
    settings = Settings()

    # ── Test 1: planner.decompose parses a valid plan ────────────────────
    with patch("agent.planner.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "steps": [
                {"step": 1, "description": "Open the terminal"},
                {"step": 2, "description": "Run git pull"},
            ]
        })
        plan = planner.decompose("update the repo", settings)
        check("Planner parses a valid 2-step plan", plan is not None and len(plan) == 2)
        check("Planner steps have correct descriptions", plan[0]["description"] == "Open the terminal")

    # ── Test 2: planner.decompose fails safe on bad JSON ──────────────────
    with patch("agent.planner.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "not valid json{{{"}
        mock_post.return_value = mock_resp
        plan = planner.decompose("do something", settings)
        check("Planner returns None on malformed JSON (fails safe)", plan is None)

    # ── Test 3: planner.decompose fails safe on HTTP error ────────────────
    with patch("agent.planner.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_post.return_value = mock_resp
        plan = planner.decompose("do something", settings)
        check("Planner returns None on HTTP error (fails safe)", plan is None)

    # ── Test 4: planner.decompose fails safe on connection error ──────────
    with patch("agent.planner.requests.post", side_effect=ConnectionError("no network")):
        plan = planner.decompose("do something", settings)
        check("Planner returns None on connection error (fails safe)", plan is None)

    # ── Test 5: ReflectionEngine stores and retrieves a lesson ────────────
    reflection = ReflectionEngine(settings=settings)
    with patch("agent.reflection.requests.post") as mock_post:
        mock_post.return_value = fake_ollama_response({
            "went_well": "Task completed quickly",
            "went_wrong": "Had to retry the terminal command once",
            "lesson": "Always check working directory before running git pull",
            "confidence": 0.8,
        })
        result = reflection.reflect(
            task="update the repo",
            steps=[{"step": 1, "action": "terminal", "observation": "ran git pull"}],
            outcome="Repo updated successfully"
        )
        check("Reflection stores successfully", result is not None)
        check("Reflection lesson captured correctly", result["lesson"].startswith("Always check"))

    lessons = reflection.get_relevant_lessons(query="update the repo")
    check("Stored lesson is retrievable by keyword match", "Always check working directory" in lessons)

    # ── Test 6: ReflectionEngine fails safe on bad response ───────────────
    with patch("agent.reflection.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "{}"}  # no "lesson" field
        mock_post.return_value = mock_resp
        result = reflection.reflect(task="x", steps=[], outcome="y")
        check("Reflection returns None when no lesson extracted (fails safe)", result is None)

    # ── Test 7: run_planned_task falls back to run_task when planning fails ──
    react = ReactLoop(settings)
    fake_brain = FakeBrain()
    fake_session = FakeSession()
    with patch("agent.planner.decompose", return_value=None):
        with patch.object(react, "_safe_reflect") as mock_reflect:
            result_text = react.run_planned_task("some task with no plan", fake_brain, fake_session)
            check("Falls back to run_task() when planner returns None", "Handled:" in result_text)
            check("Reflection still called even on fallback path", mock_reflect.called)

    # ── Test 8: run_planned_task executes a real plan step by step ───────
    react2 = ReactLoop(settings)
    fake_brain2 = FakeBrain()
    fake_session2 = FakeSession()
    fake_plan = [
        {"step": 1, "description": "First thing"},
        {"step": 2, "description": "Second thing"},
    ]
    with patch("agent.planner.decompose", return_value=fake_plan):
        with patch.object(react2, "_safe_reflect") as mock_reflect2:
            result_text = react2.run_planned_task("multi-step task", fake_brain2, fake_session2)
            check("Planned execution returns a result", "Handled:" in result_text)
            check("Reflection called after planned execution", mock_reflect2.called)
            # Verify it actually iterated both steps (2 calls means both steps ran)
            call_args = mock_reflect2.call_args
            observations_passed = call_args.args[1]
            check("Both planned steps were executed", len(observations_passed) == 2)

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)
    print("Phase 1 (Planner + Reflection) offline logic verified.")


if __name__ == "__main__":
    main()
