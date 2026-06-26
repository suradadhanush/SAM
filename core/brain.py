"""
THE BRAIN — Qwen 2.5 14B via Ollama
Receives full session context, returns structured response.
Handles model loading status, fallback, and agent routing.
"""

import logging
import json
import requests
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("SAM.Brain")


@dataclass
class BrainResponse:
    text: str                        # What SAM says out loud
    action: Optional[str] = None     # "control" | "browser" | "terminal" | "vision" | None
    action_payload: Optional[dict] = None  # Parameters for the action
    raw: Optional[dict] = None       # Full LLM output


SYSTEM_PROMPT = """You are SAM — a fully local, private, voice-controlled AI assistant.
You are running entirely on the user's machine. No data leaves this device.

Your personality:
- Direct and confident. No filler phrases.
- Intelligent and capable. You don't hedge unnecessarily.
- You remember the user across sessions and learn their preferences.
- You speak naturally — responses will be converted to speech, so avoid markdown, lists, or symbols.

Your capabilities:
- Answer questions and have conversations
- Control the computer (clicks, typing, opening apps)
- Browse the web autonomously
- Run terminal commands
- Read the screen via vision
- Remember everything across sessions (unless incognito mode is active)
- Learn the user's taste, decisions, and reasoning style via Founder Mode

Response format:
Always respond with valid JSON in this exact structure:
{
  "text": "What you say out loud — natural speech, no markdown",
  "action": null or one of: "control", "browser", "terminal", "vision", "none",
  "action_payload": null or object with action parameters
}

Action payload examples:
- control: {"type": "click", "description": "click the send button"} or {"type": "type", "text": "hello world"}
- browser: {"url": "https://...", "task": "find the price of MacBook Air M3"}
- terminal: {"command": "ls -la", "description": "list files in current directory"}
- vision: {"task": "read what is on the screen", "click_after": false}

If no action needed, set action to null and action_payload to null.
Keep spoken responses concise — this is voice, not text.
"""


class Brain:
    def __init__(self, settings):
        self.settings = settings
        self._model_loaded = False
        self._current_model = None

    def _check_ollama(self) -> bool:
        """Check if Ollama is running."""
        try:
            r = requests.get(f"{self.settings.ollama_host}/api/tags", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def _ensure_model(self) -> str:
        """Ensure the right model is available. Returns model name to use."""
        if not self._check_ollama():
            raise RuntimeError(
                "Ollama is not running. Start it with: ollama serve"
            )

        try:
            r = requests.get(f"{self.settings.ollama_host}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]

            if self.settings.primary_model in models:
                return self.settings.primary_model
            elif self.settings.fallback_model in models:
                logger.warning(
                    f"Primary model {self.settings.primary_model} not found. "
                    f"Using fallback: {self.settings.fallback_model}"
                )
                return self.settings.fallback_model
            else:
                raise RuntimeError(
                    f"No SAM models found in Ollama. Run: ollama pull {self.settings.primary_model}"
                )
        except Exception as e:
            raise RuntimeError(f"Model check failed: {e}")

    def process(self, session) -> BrainResponse:
        """
        Send session context to LLM and get structured response.
        """
        model = self._ensure_model()
        self._current_model = model

        # Build messages
        messages = self._build_messages(session)

        logger.info(f"Sending to {model}...")

        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": self.settings.temperature,
                    "num_predict": self.settings.max_tokens,
                    "num_ctx": self.settings.model_context_length,
                }
            }

            response = requests.post(
                f"{self.settings.ollama_host}/api/chat",
                json=payload,
                timeout=120
            )

            if response.status_code != 200:
                raise RuntimeError(f"Ollama returned {response.status_code}: {response.text}")

            raw = response.json()
            content = raw["message"]["content"]

            # Parse JSON response
            parsed = json.loads(content)
            return BrainResponse(
                text=parsed.get("text", "I didn't get a proper response."),
                action=parsed.get("action"),
                action_payload=parsed.get("action_payload"),
                raw=raw
            )

        except json.JSONDecodeError:
            # LLM didn't return valid JSON — extract text anyway
            logger.warning("LLM returned non-JSON response — using raw text")
            text = raw.get("message", {}).get("content", "I encountered an issue.")
            return BrainResponse(text=text)

        except Exception as e:
            logger.error(f"Brain processing error: {e}", exc_info=True)
            return BrainResponse(text="I hit a problem processing that. Try again.")

    def _build_messages(self, session) -> list:
        """Build the full message list for the LLM."""
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Identity context
        if session.identity:
            messages.append({
                "role": "system",
                "content": f"User identity and profile:\n{json.dumps(session.identity, indent=2)}"
            })

        # Founder Mode context
        if session.founder_context and not self.settings.incognito:
            messages.append({
                "role": "system",
                "content": f"Founder Mode — User's taste, decisions, and reasoning:\n{session.founder_context}"
            })

        # Long-term memories
        if session.memories and not self.settings.incognito:
            memory_text = "\n".join(
                f"- {m['content']}" for m in session.memories
            )
            messages.append({
                "role": "system",
                "content": f"Relevant memories from past sessions:\n{memory_text}"
            })

        # Conversation history from this session
        for turn in session.history:
            messages.append({"role": turn["role"], "content": turn["content"]})

        # Current user input
        messages.append({"role": "user", "content": session.user_input})

        return messages

    def unload(self):
        """Signal that SAM is sleeping — model can be freed from RAM."""
        logger.info("Brain unloading (sleep mode)")
        self._model_loaded = False
        self._current_model = None
