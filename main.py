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
import threading
from dataclasses import replace
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
from agent.react_loop import ReactLoop


class SAM:
    def __init__(self, start_in_text_mode: bool = False):
        logger.info("SAM initialising...")
        self.settings = Settings()
        self.identity = Identity()
        self.memory = MemoryRetriever()
        self.founder_mode = FounderModeManager(settings=self.settings)
        self.brain = Brain(self.settings)
        self.react_loop = ReactLoop(self.settings, founder_mode=self.founder_mode)
        self.tts = TextToSpeech(self.settings)
        self.stt = SpeechToText(self.settings)
        self.wake_word = WakeWordListener(self.settings, callback=self.on_wake_voice)
        self.text_input = TextInputListener(
            callback=self.on_text_input,
            mode_switch_callback=self.switch_mode
        )
        self._running = False
        self._input_mode = "text" if start_in_text_mode else "voice"
        # Concurrency fix (found via real Mac testing): text_input.py and
        # wake_word.py both fire an unsynchronized new thread per trigger.
        # Without this lock, a second message arriving while the first was
        # still processing (10-30+ seconds is normal) ran CONCURRENTLY on a
        # separate thread, touching the same shared, NOT thread-safe state
        # -- the cached Playwright Page in particular, whose sync API is
        # bound to whichever thread created it. That's the exact mechanism
        # behind the real "cannot switch to a different thread (which
        # happens to have exited)" crash seen in testing, and also why
        # typing "stop it" during a running task didn't stop anything -- it
        # just started running concurrently instead of queuing after it.
        # This lock is the single chokepoint both text and voice input
        # converge on, so one lock here covers both input sources.
        self._process_lock = threading.Lock()

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
        """Shared processing pipeline for both voice and text input.
        Serialized via self._process_lock -- see __init__ for why."""
        acquired = self._process_lock.acquire(blocking=False)
        if not acquired:
            print("\n[SAM] Still working on your previous request — "
                  "this will run right after it finishes.\n")
            self._process_lock.acquire()  # now wait our turn

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
            logger.info(f"Brain response — action: {response.action}")

            final_response = response

            # If the Brain decided an action is needed, ACTUALLY execute it.
            # Before this change, main.py only ever spoke response.text —
            # which is the Brain's pre-action claim ("Opening YouTube...")
            # written in the same breath as deciding the action, not a
            # report of anything that happened. Nothing downstream of that
            # ever ran. Now: run the task for real through the ReAct loop
            # (Planner-first, verified with 1 retry, falls back to the
            # adaptive loop if planning fails), and speak/save the loop's
            # actual result instead of the pre-action guess.
            if response.action and response.action not in (None, "none"):
                try:
                    real_result_text = self.react_loop.run_planned_task(
                        task=user_input,
                        brain=self.brain,
                        session=session,
                        founder_context=session.founder_context,
                        initial_response=response
                    )
                    final_response = replace(response, text=real_result_text)
                except Exception as e:
                    logger.error(f"Task execution failed: {e}", exc_info=True)
                    final_response = replace(
                        response,
                        text=f"I tried to do that but hit an error: {e}"
                    )

            logger.info(f"SAM: {final_response.text}")

            # Always print response — useful in text mode
            print(f"\nSAM: {final_response.text}\n")

            # Speak response (unless in silent/text-only mode)
            if self.settings.tts_engine != "none":
                self.tts.speak(final_response.text)

            # Save session to memory — records what actually happened,
            # not the discarded pre-action claim
            if not self.settings.incognito:
                session.save(user_input=user_input, response=final_response)

            # Founder Mode capture — same, sees the real outcome
            self.founder_mode.capture_if_relevant(user_input, final_response)

        except Exception as e:
            logger.error(f"Processing error: {e}", exc_info=True)
            error_msg = "I hit an error. Check the logs."
            print(f"\nSAM: {error_msg}\n")
            if self.settings.tts_engine != "none":
                self.tts.speak(error_msg)
        finally:
            self._process_lock.release()

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
