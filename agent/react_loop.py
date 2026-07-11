"""
AGENT — ReAct Loop
Reason → Act → Observe → Repeat until task complete.
Routes Brain decisions to the correct Hand.
"""

import time
import logging
import json
from typing import Optional, Dict, Any

from agent import planner
from agent.reflection import ReflectionEngine
from agent.verifier import Verifier

logger = logging.getLogger("SAM.Agent")

MAX_STEPS = 10  # Safety limit on autonomous steps


class ReactLoop:
    def __init__(self, settings, founder_mode=None):
        self.settings = settings
        self._control = None
        self._browser = None
        self._terminal = None
        self._vision = None
        self._reflection = ReflectionEngine(settings)
        self._verifier = Verifier(settings)
        # Optional — pass a FounderModeManager to let high-confidence
        # reflections bridge into Founder Mode. Omit to keep old behaviour.
        self.founder_mode = founder_mode

    def _get_control(self):
        if self._control is None:
            from hands.control.controller import ComputerController
            self._control = ComputerController()
        return self._control

    def _get_browser(self):
        if self._browser is None:
            from hands.browser.playwright_agent import BrowserAgent
            self._browser = BrowserAgent()
        return self._browser

    def _get_terminal(self):
        if self._terminal is None:
            from hands.terminal.runner import TerminalRunner
            allow_risky = getattr(self.settings, "allow_risky_terminal_commands", False)
            self._terminal = TerminalRunner(allow_risky=allow_risky)
        return self._terminal

    def _get_vision(self):
        if self._vision is None:
            from hands.vision.screen_reader import ScreenReader
            self._vision = ScreenReader(self.settings)
        return self._vision

    def execute(self, action: str, payload: Dict[str, Any]) -> str:
        """
        Execute a single action and return the observation.
        """
        logger.info(f"Executing action: {action} | payload: {payload}")

        try:
            if action == "control":
                return self._execute_control(payload)
            elif action == "browser":
                return self._execute_browser(payload)
            elif action == "terminal":
                return self._execute_terminal(payload)
            elif action == "vision":
                return self._execute_vision(payload)
            else:
                return f"Unknown action: {action}"

        except Exception as e:
            logger.error(f"Action execution error: {e}", exc_info=True)
            return f"Error executing {action}: {str(e)}"

    def _execute_verified(self, action: str, payload: Dict[str, Any], step_label: str) -> Dict:
        """
        Phase 1.5: executes an action, verifies the result, and retries
        ONCE on failure (same action, same payload — no auto-repair).
        Both attempts are always logged, and both are always included in
        what gets passed to Reflection, whether the final outcome is a
        success (after retry) or an abort (failed twice).
        """
        attempts = []

        start = time.time()
        observation = self.execute(action, payload)
        elapsed = time.time() - start
        result = self._verifier.verify(action, payload, observation, elapsed)
        attempts.append({
            "attempt": 1, "observation": observation,
            "success": result.success, "confidence": result.confidence,
            "errors": result.errors, "execution_time": elapsed,
        })
        decision = self._verifier.decide(result, already_retried=False)
        logger.info(f"[{step_label}] attempt 1: {'OK' if result.success else 'FAILED'} (decision={decision})")

        final_observation = observation
        final_success = result.success

        if decision == "retry":
            start = time.time()
            observation2 = self.execute(action, payload)
            elapsed2 = time.time() - start
            result2 = self._verifier.verify(action, payload, observation2, elapsed2)
            attempts.append({
                "attempt": 2, "observation": observation2,
                "success": result2.success, "confidence": result2.confidence,
                "errors": result2.errors, "execution_time": elapsed2,
            })
            final_decision = self._verifier.decide(result2, already_retried=True)
            logger.info(f"[{step_label}] attempt 2 (retry): {'OK' if result2.success else 'FAILED'} "
                        f"(decision={final_decision})")
            final_observation = observation2
            final_success = result2.success

        return {"observation": final_observation, "success": final_success, "attempts": attempts}

    # Latency fix #4: cheap keyword pre-filter so single-action requests
    # ("open youtube", "what's the weather") skip the Planner's separate
    # LLM call entirely, instead of every action paying for a planning
    # round-trip it doesn't need. High recall on purpose — a false
    # positive just means an unnecessary (but harmless) plan; a false
    # negative means a genuinely multi-step task gets planned anyway
    # since run_task's own adaptive loop still handles it correctly,
    # just without the upfront plan.
    _MULTI_STEP_SIGNALS = [
        " then ", " after that", " after ", " and then", " next,",
        " next ", ", then", "; then", " followed by", " once done",
        " once that", " first,", " first ", " finally "
    ]

    def _looks_multi_step(self, task: str) -> bool:
        t = f" {task.lower()} "
        return any(sig in t for sig in self._MULTI_STEP_SIGNALS)

    def run_task(self, task: str, brain, session, initial_response=None) -> str:
        """
        Run a multi-step autonomous task using ReAct loop.
        Continues until task is complete or MAX_STEPS reached.

        Latency fix #1: if initial_response is provided (the caller already
        got a Brain response for this exact task — e.g. main.py's first
        classification call), the first loop iteration reuses it instead of
        calling brain.process() again for the same decision. Every
        iteration after the first still reasons fresh, exactly as before.
        Omit initial_response to get the old behaviour unchanged.
        """
        logger.info(f"Starting ReAct loop for task: {task}")
        observations = []
        steps = 0

        current_input = task
        response = initial_response

        while steps < MAX_STEPS:
            steps += 1
            logger.info(f"ReAct step {steps}/{MAX_STEPS}")

            if response is None:
                # Reason: ask brain what to do next
                session.user_input = self._build_react_prompt(task, observations, current_input)
                response = brain.process(session)

            # Check if task is complete
            if response.action is None or response.action == "none":
                logger.info("Task complete — no more actions needed")
                self._safe_reflect(task, observations, response.text)
                return response.text

            # Act: execute the action (Phase 1.5: verified, with 1 retry on failure)
            verified = self._execute_verified(response.action, response.action_payload or {}, f"step {steps}")
            observation = verified["observation"]
            observations.append({
                "step": steps,
                "action": response.action,
                "payload": response.action_payload,
                "observation": observation,
                "attempts": verified["attempts"]
            })
            logger.info(f"Observation: {observation[:100]}")

            current_input = f"Observation from last step: {observation}"
            response = None  # force fresh reasoning on the next iteration

        logger.warning(f"ReAct loop reached max steps ({MAX_STEPS})")
        result = "I ran out of steps before completing the task. Please try again."
        self._safe_reflect(task, observations, result)
        return result

    def run_planned_task(self, task: str, brain, session, founder_context: str = "",
                          initial_response=None) -> str:
        """
        Phase 1: Plans the task into ordered steps first, then executes
        each step. Falls back to the original adaptive run_task() if
        planning is unavailable, returns nothing, or the task doesn't look
        multi-step to begin with (latency fix #4) — the old loop is
        untouched and remains the default behaviour whenever planning
        doesn't apply.

        Latency fix #1: initial_response (if provided) is reused for the
        FIRST planned step instead of making a fresh Brain call for it —
        the plan's first step is usually the same action the Brain already
        decided on when first asked. Every step after that still reasons
        fresh, exactly as before. This is an approximation, not a
        guarantee the fresh-asked answer would've been identical — but it
        was already just as much a guess before this change, and it saves
        a full LLM round-trip on every single action turn.
        """
        if not self._looks_multi_step(task):
            logger.info("Task looks single-step — skipping Planner call")
            return self.run_task(task, brain, session, initial_response=initial_response)

        plan = planner.decompose(task, self.settings, founder_context)
        if not plan:
            logger.info("No plan available — falling back to adaptive ReAct loop")
            return self.run_task(task, brain, session, initial_response=initial_response)

        logger.info(f"Plan created with {len(plan)} step(s) for task: {task}")
        observations = []
        steps_run = 0

        for i, planned_step in enumerate(plan):
            if steps_run >= MAX_STEPS:
                logger.warning(f"Planned task exceeded MAX_STEPS ({MAX_STEPS}) — stopping early")
                break
            steps_run += 1

            if i == 0 and initial_response is not None:
                response = initial_response
            else:
                step_prompt = self._build_planned_step_prompt(task, plan, planned_step, observations)
                session.user_input = step_prompt
                response = brain.process(session)

            if response.action and response.action != "none":
                verified = self._execute_verified(
                    response.action, response.action_payload or {}, f"step {planned_step['step']}"
                )
                observation = verified["observation"]
                attempts = verified["attempts"]
            else:
                observation = response.text
                attempts = None

            observations.append({
                "step": planned_step["step"],
                "action": response.action,
                "description": planned_step["description"],
                "observation": observation,
                "attempts": attempts
            })
            logger.info(f"Planned step {planned_step['step']}/{len(plan)}: {observation[:100]}")

        final_text = observations[-1]["observation"] if observations else "Task could not be started."
        self._safe_reflect(task, observations, final_text)
        return final_text

    def _safe_reflect(self, task: str, observations: list, outcome: str):
        """Reflection must never break or delay the response the user is
        waiting on — always call this after the result is already decided.
        Passes self.founder_mode through (may be None) so high-confidence
        lessons can bridge into Founder Mode when it's available."""
        try:
            self._reflection.reflect(task=task, steps=observations, outcome=outcome,
                                      founder_mode=self.founder_mode)
        except Exception as e:
            logger.debug(f"Reflection call skipped: {e}")

    def _build_planned_step_prompt(self, task: str, plan: list, current_step: Dict, observations: list) -> str:
        plan_text = "\n".join(f"{s['step']}. {s['description']}" for s in plan)
        obs_text = "\n".join(
            f"Step {o['step']} ({o['description']}): {o['observation']}" for o in observations
        ) if observations else "None yet."

        return (
            f"Overall task: {task}\n\n"
            f"Full plan:\n{plan_text}\n\n"
            f"Steps completed so far:\n{obs_text}\n\n"
            f"Now execute step {current_step['step']}: {current_step['description']}\n"
            f"If this step needs an action, specify it. If it's already satisfied by the "
            f"conversation so far, respond with action: null and a short status."
        )

    def _build_react_prompt(self, task: str, observations: list, current: str) -> str:
        if not observations:
            return f"Task: {task}\nWhat is the first action to take?"

        obs_text = "\n".join(
            f"Step {o['step']}: {o['action']} → {o['observation']}"
            for o in observations
        )
        return (
            f"Original task: {task}\n\n"
            f"Steps taken so far:\n{obs_text}\n\n"
            f"Current: {current}\n\n"
            f"What is the next action? If the task is complete, respond with action: null."
        )

    # ─── Action Executors ─────────────────────────────────────────────────

    def _execute_control(self, payload: Dict) -> str:
        controller = self._get_control()
        action_type = payload.get("type", "")

        if action_type == "click":
            description = payload.get("description", "")
            # First use vision to find where to click
            vision = self._get_vision()
            coords = vision.find_element(description)
            if coords:
                controller.click(coords[0], coords[1])
                return f"Clicked on '{description}' at {coords}"
            else:
                return f"Could not find '{description}' on screen"

        elif action_type == "type":
            text = payload.get("text", "")
            controller.type_text(text)
            return f"Typed: {text}"

        elif action_type == "hotkey":
            keys = payload.get("keys", [])
            controller.hotkey(*keys)
            return f"Pressed hotkey: {keys}"

        elif action_type == "open_app":
            app = payload.get("app", "")
            controller.open_app(app)
            return f"Opened: {app}"

        elif action_type == "screenshot":
            path = controller.screenshot()
            return f"Screenshot saved to {path}"

        return f"Unknown control action: {action_type}"

    def _execute_browser(self, payload: Dict) -> str:
        browser = self._get_browser()
        url = payload.get("url", "")
        task = payload.get("task", "")
        return browser.execute(url=url, task=task)

    def _execute_terminal(self, payload: Dict) -> str:
        terminal = self._get_terminal()
        command = payload.get("command", "")
        description = payload.get("description", "")
        return terminal.run(command, description)

    def _execute_vision(self, payload: Dict) -> str:
        vision = self._get_vision()
        task = payload.get("task", "read the screen")
        return vision.read(task)
