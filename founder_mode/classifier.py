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
"""

import json
import logging
import requests

logger = logging.getLogger("SAM.FounderMode.Classifier")

# Sentinel types (in addition to "decision" | "rejection" | "preference" | "none")
UNAVAILABLE = "_unavailable"

CLASSIFIER_PROMPT = """You extract product-taste signals from one exchange between a user and their AI assistant.

Decide if the user's message contains ONE of:
- "decision": the user chose an approach and can explain why, even briefly
- "rejection": the user rejected or disliked something and can explain why, even briefly
- "preference": the user stated a durable preference or taste (tool, style, workflow)
- "none": casual conversation, a question, small talk, or anything with no real taste/decision signal

Rules:
- Only extract if there is an actual stance, not just a question or observation.
- "reasoning" must be the user's own justification, paraphrased in your words — never invent a reason they did not give. If no reason was given, write "no reason given".
- "confidence" reflects how explicit the signal is:
    0.85-1.0 = explicit and unambiguous ("I'm going with X because Y", "I hate X, never suggest it again")
    0.5-0.8  = implied or casual but real signal
    0.0-0.4  = weak, could easily be a throwaway remark
- "domain" (preference only) is a short slug, e.g. "backend_framework", "ui_style", "communication_tone".
- "category" (decision/rejection only) is a short slug, e.g. "architecture", "design", "tooling", "process".

Respond with ONLY this JSON, nothing else:
{"type": "decision|rejection|preference|none", "category": "string", "domain": "string", "statement": "string", "reasoning": "string", "confidence": 0.0}

User message: {user_input}
Assistant reply: {response_text}
"""


def classify(user_input: str, response_text: str, settings) -> dict:
    """
    Returns a dict with keys: type, category, domain, statement, reasoning, confidence.

    type == "none"        -> classifier ran fine, genuinely no signal. Trust this.
    type == "_unavailable" -> classifier could not run (Ollama down, bad JSON, timeout).
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

        if result["type"] not in ("decision", "rejection", "preference", "none"):
            result["type"] = "none"

        result["confidence"] = max(0.0, min(1.0, result["confidence"]))

        if result["type"] != "none" and not result["statement"]:
            result["type"] = "none"

        return result

    except Exception as e:
        logger.debug(f"Founder Mode classifier unavailable: {e}")
        return {"type": UNAVAILABLE}
