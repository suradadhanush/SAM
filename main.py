"""
SAM — Personal AI Assistant
Self-learning Autonomous Mind with Hermes Intelligence & Taste Heuristics Architecture

Entry point. Starts the ears, loads identity, enters the main loop.
"""

import sys
import signal
import logging
from pathlib import Path

# Setup logging before anything else
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
from ears.stt import SpeechToText
from core.brain import Brain
from core.session import Session
from mouth.tts import TextToSpeech
from memory.identity import Identity
from memory.retrieve import MemoryRetriever
from founder_mode.manager import FounderModeManager


class SAM:
    def __init__(self):
        logger.info("SAM initialising...")
        self.settings = Settings()
        self.identity = Identity()
        self.memory = MemoryRetriever()
        self.founder_mode = FounderModeManager()
        self.brain = Brain(self.settings)
        self.tts = TextToSpeech(self.settings)
        self.stt = SpeechToText(self.settings)
        self.wake_word = WakeWordListener(self.settings, callback=self.on_wake)
        self._running = False

    def on_wake(self):
        """Called by openWakeWord when wake word is detected."""
        logger.info("Wake word detected — activating SAM")
        try:
            # Transcribe speech
            user_input = self.stt.listen()
            if not user_input or user_input.strip() == "":
                logger.info("No speech detected after wake word")
                return

            logger.info(f"User said: {user_input}")

            # Handle special commands
            if self._handle_command(user_input):
                return

            # Build session context
            session = Session(
                user_input=user_input,
                identity=self.identity.load(),
                memories=self.memory.retrieve(user_input),
                founder_context=self.founder_mode.get_context(),
                settings=self.settings
            )

            # Get response from Brain
            response = self.brain.process(session)
            logger.info(f"SAM response: {response.text}")

            # Speak response
            self.tts.speak(response.text)

            # Post-session memory extraction
            session.save(user_input=user_input, response=response)

            # Check if Founder Mode should capture anything
            self.founder_mode.capture_if_relevant(user_input, response)

        except Exception as e:
            logger.error(f"Error in wake callback: {e}", exc_info=True)
            self.tts.speak("I hit an error. Check the logs.")

    def _handle_command(self, text: str) -> bool:
        """Handle built-in SAM commands. Returns True if handled."""
        text_lower = text.lower().strip()

        if any(phrase in text_lower for phrase in ["sam sleep", "go to sleep", "sleep mode"]):
            self.tts.speak("Going to sleep. Call me when you need me.")
            self.brain.unload()
            return True

        if any(phrase in text_lower for phrase in ["sam stop", "shut down", "goodbye sam"]):
            self.tts.speak("Shutting down. Goodbye.")
            self.stop()
            return True

        if "incognito" in text_lower:
            self.tts.speak("Switching to incognito mode. Nothing will be recorded.")
            self.settings.incognito = True
            return True

        if "exit incognito" in text_lower or "leave incognito" in text_lower:
            self.tts.speak("Leaving incognito mode. Memory is back on.")
            self.settings.incognito = False
            return True

        return False

    def start(self):
        """Start SAM — wake word listener runs, everything else on demand."""
        self._running = True
        logger.info("SAM is awake. Listening for wake word...")

        # Graceful shutdown on SIGINT / SIGTERM
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        self.tts.speak("SAM is ready.")
        self.wake_word.start()  # Blocking loop

    def stop(self):
        self._running = False
        self.wake_word.stop()
        logger.info("SAM stopped.")
        sys.exit(0)

    def _shutdown(self, sig, frame):
        logger.info("Shutdown signal received")
        self.stop()


if __name__ == "__main__":
    sam = SAM()
    sam.start()
