"""
FOUNDER MODE v2 — LLM Classifier
Determines whether a user turn contains a decision, rejection, or preference
worth remembering, and extracts it with real reasoning + a confidence score.

Decoupled from core/brain.py on purpose — this is a separate, cheap,
low-temperature classification call, not a conversational turn. Nothing
in here ever touches the main chat pipeline directly.

FAILS SAFE: any error, timeout, or bad response returns a sentinel that
tells the caller "classifier unavailable" — it never raises, and it never
blocks or slows down the main SAM response the user is waiting on, because
it always runs AFTER the response has already been spoken (see main.py).

Bug fixed here (found via real Mac testing): "task_request" is a new type,
added because one-time action instructions ("open youtube and play X")
were being classified as "decision" — which was technically defensible
under the old prompt (the user did state a choice with a reason) but
wrong in effect, since Founder Mode injects every captured "decision" into
EVERY future prompt forever via get_context(). A one-time task request
captured that way meant the Brain saw "you decided to play this video" as
persistent context on every later turn, regardless of relevance — which
is the actual mechanism behind a stale task appearing to "resume" after a
restart on an unrelated new question. task_request is explicitly excluded
from capture (see manager.py's capture_if_relevant) — it's a signal to do
nothing, same as "none".
"""

import json
import logging
import requests

logger = logging.getLogger("SAM.FounderMode.Classifier")

# Sentinel types (in addition to "decision" | "rejection" | "preference" |
# "task_request" | "none")
UNAVAILABLE = "_unavailable"

CLASSIFIER_PROMPT = """You extract product-taste signals from one exchange between a user and their AI assistant.

Decide if the user's message contains ONE of:
- "decision": a PRODUCT, ARCHITECTURE, DESIGN, or PROCESS choice with a reason, meant to inform SIMILAR choices in the future (e.g. "I'm going with FastAPI over Flask because I know it better", "let's always use dark mode by default")
- "rejection": the user rejected or disliked something and can explain why, even briefly
- "preference": the user stated a durable preference or taste (tool, style, workflow) that should apply going forward
- "task_request": an instruction to DO something right now — open an app, play a video, browse a site, run a command, send a message. This is NOT a preference or decision, even if phrased like one ("I want you to...", "I've decided to open..."). The test: would this still make sense to show the user next week as "a decision you made"? If it's really just "do this one thing now", it's task_request, not decision.
- "none": casual conversation, a question, small talk, or anything with no real signal in the above categories

Rules:
- Only extract if there is an actual stance, not just a question or observation.
- When in doubt between "decision" and "task_request": a decision is something you'd want remembered and applied to FUTURE similar situations. A task_request is a one-time instruction whose relevance ends once the task is done. "Open YouTube and play the new trailer" is task_request. "Always open videos in the background instead of switching focus" is a decision.
- "reasoning" must be the user's own justification, paraphrased in your words — never invent a reason they did not give. If no reason was given, write "no reason given".
- "confidence" reflects how explicit the signal is:
    0.85-1.0 = explicit and unambiguous ("I'm going with X because Y", "I hate X, never suggest it again")
    0.5-0.8  = implied or casual but real signal
    0.0-0.4  = weak, could easily be a throwaway remark
- "domain" (preference only) is a short slug, e.g. "backend_framework", "ui_style", "communication_tone".
- "category" (decision/rejection only) is a short slug, e.g. "architecture", "design", "tooling", "process".

Respond with ONLY this JSON, nothing else:
{"type": "decision|rejection|preference|task_request|none", "category": "string", "domain": "string", "statement": "string", "reasoning": "string", "confidence": 0.0}

User message: {user_input}
Assistant reply: {response_text}
"""


def classify(user_input: str, response_text: str, settings) -> dict:
    """
    Returns a dict with keys: type, category, domain, statement, reasoning, confidence.

    type == "none"          -> classifier ran fine, genuinely no signal. Trust this.
    type == "task_request"  -> classifier ran fine, this is a one-time action
                                instruction, not a preference/decision. Trust
                                this too — never capture it into Founder Mode.
    type == "_unavailable"  -> classifier could not run (Ollama down, bad JSON, timeout).
                                Caller should fall back to lightweight heuristic capture.
    """
    try:
        model = getattr(settings, "founder_mode_classifier_model", None) or settings.primary_model
        prompt = CLASSIFIER_PROMPT.replace("{user_input}", user_input[:500]) \
                                  .replace("{response_text}", (response_text or "")[:300])

        r = requests.post(
            f"{settings.ollama_host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 250},
            },
            timeout=20,
        )
        if r.status_code != 200:
            logger.debug(f"Founder Mode classifier HTTP {r.status_code}")
            return {"type": UNAVAILABLE}

        raw = r.json().get("response", "")
        parsed = json.loads(raw)

        result = {
            "type": parsed.get("type", "none"),
            "category": (parsed.get("category") or "general").strip() or "general",
            "domain": (parsed.get("domain") or "general").strip() or "general",
            "statement": (parsed.get("statement") or "").strip(),
            "reasoning": (parsed.get("reasoning") or "no reason given").strip(),
            "confidence": float(parsed.get("confidence", 0.5) or 0.5),
        }

        if result["type"] not in ("decision", "rejection", "preference", "task_request", "none"):
            result["type"] = "none"

        result["confidence"] = max(0.0, min(1.0, result["confidence"]))

        if result["type"] not in ("none", "task_request") and not result["statement"]:
            result["type"] = "none"

        return result

    except Exception as e:
        logger.debug(f"Founder Mode classifier unavailable: {e}")
        return {"type": UNAVAILABLE}
