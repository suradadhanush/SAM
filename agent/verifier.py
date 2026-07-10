"""
AGENT — Verification Engine (Phase 1.5)

Wraps each executed step's raw observation into a structured TaskResult,
and decides whether to accept it, retry once, or abort. Deliberately does
NOT auto-repair a failed action (e.g. rewrite and re-run a different
command) — that's a meaningfully bigger, riskier capability than "verify
and retry the same thing once," and is left as an explicit future decision
per Dhanush's call, not smuggled in here.

Heuristic by default — no extra LLM round-trip per step, so step latency
is unchanged from before this phase. The failure signals below match the
exact strings agent/react_loop.py's own executors already produce on
failure (see execute()'s except block and each _execute_* method), so
this is pattern-matching on known, reliable text, not guesswork.

Never raises. verify() always returns a TaskResult, even on unexpected
input — a broken Verifier must never break the ReAct loop around it.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger("SAM.Agent.Verifier")

_FAILURE_SIGNALS = [
    "error executing", "could not find", "unknown action", "unknown control action",
    "traceback", "exception:",
]


@dataclass
class TaskResult:
    success: bool
    confidence: float
    logs: List[str] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    errors: List[str] = field(default_factory=list)


class Verifier:
    def __init__(self, settings=None):
        self.settings = settings

    def verify(self, action: str, payload: Dict, observation: str, execution_time: float,
               exception: Optional[Exception] = None) -> TaskResult:
        """Builds a TaskResult from one executed attempt. Never raises."""
        try:
            if exception is not None:
                return TaskResult(
                    success=False, confidence=0.9,
                    logs=[f"{action} raised an exception"],
                    artifacts={"action": action, "payload": payload},
                    execution_time=execution_time,
                    errors=[str(exception)],
                )

            obs_lower = (observation or "").lower()
            looks_failed = any(sig in obs_lower for sig in _FAILURE_SIGNALS)

            if looks_failed:
                return TaskResult(
                    success=False, confidence=0.6,
                    logs=[f"{action} completed but observation suggests failure"],
                    artifacts={"action": action, "payload": payload, "observation": observation},
                    execution_time=execution_time,
                    errors=[observation or "unknown failure"],
                )

            return TaskResult(
                success=True, confidence=0.8,
                logs=[f"{action} completed"],
                artifacts={"action": action, "payload": payload, "observation": observation},
                execution_time=execution_time,
                errors=[],
            )
        except Exception as e:
            logger.debug(f"Verifier itself failed, defaulting to a cautious accept: {e}")
            return TaskResult(success=True, confidence=0.3,
                               logs=["verifier error, defaulted to accept"],
                               execution_time=execution_time, errors=[str(e)])

    def decide(self, result: TaskResult, already_retried: bool) -> str:
        """
        Returns 'accept', 'retry', or 'abort'.
        No auto-repair: a retry always re-runs the exact same action and
        payload. If it fails twice, the loop aborts that step rather than
        having the LLM guess a different command and try again unsupervised.
        """
        if result.success:
            return "accept"
        if not already_retried:
            return "retry"
        return "abort"
