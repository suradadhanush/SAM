"""
SAM — Personal AI Assistant
Self-learning Autonomous Mind with Hermes Intelligence & Taste Heuristics Architecture

Entry point. Supports both voice and text input modes.
Start in voice mode: python main.py
Start in text mode:  python main.py --text
"""

import sys
import signal
import logging
import argparse
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/sam.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SAM")

from config.settings import Settings
from ears.wake_word import WakeWordListener
from ears.text_input import TextInputListener
from ears.stt import SpeechToText
from core.brain import Brain
from core.session import Session
from mouth.tts import TextToSpeech
from memory.identity import Identity
from memory.retrieve import MemoryRetriever
from founder_mode.manager import FounderModeManager


class SAM:
    def __init__(self, start_in_text_mode: bool = False):
        logger.info("SAM initialising...")
        self.settings = Settings()
        self.identity = Identity()
        self.memory = MemoryRetriever()
        self.founder_mode = FounderModeManager()
        self.brain = Brain(self.settings)
        self.tts = TextToSpeech(self.settings)
        self.stt = SpeechToText(self.settings)
        self.wake_word = WakeWordListener(self.settings, callback=self.on_wake_voice)
        self.text_input = TextInputListener(
            callback=self.on_text_input,
            mode_switch_callback=self.switch_mode
        )
        self._running = False
        self._input_mode = "text" if start_in_text_mode else "voice"

    # ─── Input Handlers ───────────────────────────────────────────────────

    def on_wake_voice(self):
        """Called by wake word listener — records and transcribes speech."""
        logger.info("Wake word detected — recording...")
        user_input = self.stt.listen()
        if user_input and user_input.strip():
            self._process(user_input)

    def on_text_input(self, text: str):
        """Called by text input listener — processes typed input directly."""
        logger.info(f"Text input: {text}")
        self._process(text)

    # ─── Core Processing ──────────────────────────────────────────────────

    def _process(self, user_input: str):
        """Shared processing pipeline for both voice and text input."""
        try:
            # Handle built-in commands first
            if self._handle_command(user_input):
                return

            # Build session context
            session = Session(
                user_input=user_input,
                identity=self.identity.load(),
                memories=self.memory.retrieve(user_input, self.settings),
                founder_context=self.founder_mode.get_context(),
                settings=self.settings
            )

            # Get response from Brain
            response = self.brain.process(session)
            logger.info(f"SAM: {response.text}")

            # Always print response — useful in text mode
            print(f"\nSAM: {response.text}\n")

            # Speak response (unless in silent/text-only mode)
            if self.settings.tts_engine != "none":
                self.tts.speak(response.text)

            # Save session to memory
            if not self.settings.incognito:
                session.save(user_input=user_input, response=response)

            # Founder Mode capture
            self.founder_mode.capture_if_relevant(user_input, response)

        except Exception as e:
            logger.error(f"Processing error: {e}", exc_info=True)
            error_msg = "I hit an error. Check the logs."
            print(f"\nSAM: {error_msg}\n")
            if self.settings.tts_engine != "none":
                self.tts.speak(error_msg)

    # ─── Commands ─────────────────────────────────────────────────────────

    def _handle_command(self, text: str) -> bool:
        """Handle built-in SAM commands. Returns True if handled."""
        t = text.lower().strip()

        # Mode switching
        if any(p in t for p in ["text mode", "switch to text", "type mode", "silent mode"]):
            self.switch_mode("text")
            return True

        if any(p in t for p in ["voice mode", "switch to voice", "speak mode"]):
            self.switch_mode("voice")
            return True

        # Incognito
        if "incognito" in t and "exit" not in t and "leave" not in t:
            self.settings.incognito = True
            msg = "Incognito mode on. Nothing will be recorded."
            print(f"\nSAM: {msg}\n")
            self.tts.speak(msg)
            return True

        if any(p in t for p in ["exit incognito", "leave incognito"]):
            self.settings.incognito = False
            msg = "Incognito off. Memory is back on."
            print(f"\nSAM: {msg}\n")
            self.tts.speak(msg)
            return True

        # Sleep / Stop
        if any(p in t for p in ["sam sleep", "go to sleep"]):
            msg = "Going to sleep. Call me when you need me."
            print(f"\nSAM: {msg}\n")
            self.tts.speak(msg)
            self.brain.unload()
            return True

        if any(p in t for p in ["sam stop", "shut down", "goodbye sam", "quit"]):
            msg = "Shutting down. Goodbye."
            print(f"\nSAM: {msg}\n")
            self.tts.speak(msg)
            self.stop()
            return True

        return False

    # ─── Mode Switching ───────────────────────────────────────────────────

    def switch_mode(self, mode: str):
        """Switch between voice and text input modes at runtime."""
        if mode == "text":
            self._input_mode = "text"
            self.wake_word.stop()
            msg = "Switched to text mode. Type your messages."
            print(f"\nSAM: {msg}\n")
            self.tts.speak(msg)
            self.text_input.start()
            self.text_input.join()

        elif mode == "voice":
            self._input_mode = "voice"
            self.text_input.stop()
            msg = "Switched to voice mode. Say Hey SAM."
            print(f"\nSAM: {msg}\n")
            self.tts.speak(msg)
            self.wake_word.start()

    # ─── Lifecycle ────────────────────────────────────────────────────────

    def start(self):
        self._running = True

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        ready_msg = "SAM is ready."
        print(f"\nSAM: {ready_msg}\n")
        self.tts.speak(ready_msg)

        if self._input_mode == "text":
            logger.info("Starting in TEXT mode")
            self.text_input.start()
            self.text_input.join()
        else:
            logger.info("Starting in VOICE mode")
            print("\nSAM VOICE MODE — Say 'Hey SAM' to activate")
            print("Say 'text mode' anytime to switch to typing\n")
            self.wake_word.start()  # Blocking

    def stop(self):
        self._running = False
        self.wake_word.stop()
        self.text_input.stop()
        logger.info("SAM stopped.")
        sys.exit(0)

    def _shutdown(self, sig, frame):
        logger.info("Shutdown signal received")
        self.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SAM — Personal AI Assistant")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Start in text input mode (no microphone needed)"
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="Disable TTS — print responses only"
    )
    args = parser.parse_args()

    sam = SAM(start_in_text_mode=args.text)

    if args.silent:
        sam.settings.tts_engine = "none"

    sam.start()
