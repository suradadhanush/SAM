"""
AGENT — Hierarchical Planner (Phase 1)

Decomposes a complex goal into an ordered list of concrete steps BEFORE the
ReAct loop starts reasoning turn-by-turn. Decoupled from core/brain.py on
purpose — makes its own direct Ollama call, same pattern as
founder_mode/classifier.py.

FAILS SAFE: returns None on any error or bad response. The caller
(agent/react_loop.py) must fall back to the existing adaptive step-by-step
loop (run_task) when this returns None — the old loop is not touched or
removed, it's still exactly what runs if planning isn't available.
"""

import json
import logging
import requests
from typing import List, Dict, Optional

logger = logging.getLogger("SAM.Agent.Planner")

PLANNER_PROMPT = """You are planning how to accomplish a task using a computer.

Break the task into a short, ordered list of concrete steps (2-8 steps).
Each step should be one clear, checkable action — not vague. If the task is
simple enough to be one step, return exactly one step.

{founder_context}Task: {task}

Respond with ONLY this JSON, nothing else:
{{"steps": [{{"step": 1, "description": "..."}}, {{"step": 2, "description": "..."}}]}}
"""


def decompose(task: str, settings, founder_context: str = "") -> Optional[List[Dict]]:
    """
    Returns a list of {"step": int, "description": str} dicts, or None if
    planning failed or is unavailable. None is a normal, expected outcome —
    callers must fall back to the adaptive step-by-step ReAct loop, not
    treat it as an error.
    """
    try:
        model = getattr(settings, "planner_model", None) or settings.primary_model
        fc = f"Known user preferences/decisions relevant here:\n{founder_context}\n\n" if founder_context else ""
        prompt = PLANNER_PROMPT.format(founder_context=fc, task=task[:800])

        r = requests.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 400},
            },
            timeout=30,
        )
        if r.status_code != 200:
            logger.debug(f"Planner HTTP {r.status_code}")
            return None

        raw = r.json().get("response", "")
        parsed = json.loads(raw)
        steps = parsed.get("steps", [])

        if not isinstance(steps, list) or not steps:
            return None

        cleaned = []
        for i, s in enumerate(steps, start=1):
            if isinstance(s, dict):
                desc = (s.get("description") or "").strip()
            else:
                desc = str(s).strip()
            if desc:
                cleaned.append({"step": i, "description": desc})

        return cleaned or None

    except Exception as e:
        logger.debug(f"Planner unavailable, caller should fall back: {e}")
        return None
