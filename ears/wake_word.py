"""
THE EARS — Part 1: Wake Word Detection
Uses openWakeWord for passive 24/7 listening.
Near-zero CPU. Triggers callback when wake word detected.
Whisper is NOT used here — this is purely detection.
"""

import logging
import threading
import numpy as np
from typing import Callable

logger = logging.getLogger("SAM.WakeWord")


class WakeWordListener:
    def __init__(self, settings, callback: Callable):
        self.settings = settings
        self.callback = callback
        self._running = False
        self._thread = None
        self._model = None

    def _load_model(self):
        """Load openWakeWord model."""
        try:
            from openwakeword.model import Model
            self._model = Model(
                wakeword_models=[],          # Uses default "hey jarvis" style models
                inference_framework="onnx"
            )
            logger.info("openWakeWord model loaded")
        except ImportError:
            logger.warning("openWakeWord not installed — falling back to keyboard trigger")
            self._model = None

    def _listen_loop(self):
        """
        Main listening loop.
        Reads audio chunks, feeds to openWakeWord, fires callback on detection.
        """
        if self._model is None:
            logger.info("Keyboard fallback mode: press Enter to trigger SAM")
            self._keyboard_fallback()
            return

        try:
            import pyaudio
            CHUNK = 1280
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000

            audio = pyaudio.PyAudio()
            stream = audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )

            logger.info(f"Listening for wake word: '{self.settings.wake_word}'")

            while self._running:
                audio_chunk = np.frombuffer(
                    stream.read(CHUNK, exception_on_overflow=False),
                    dtype=np.int16
                )
                prediction = self._model.predict(audio_chunk)

                for model_name, score in prediction.items():
                    if score >= self.settings.wake_word_threshold:
                        logger.info(f"Wake word detected (score: {score:.2f})")
                        # Fire callback in separate thread so listener stays active
                        threading.Thread(
                            target=self.callback,
                            daemon=True
                        ).start()
                        # Brief pause to avoid double-trigger
                        import time
                        time.sleep(2)
                        break

            stream.stop_stream()
            stream.close()
            audio.terminate()

        except Exception as e:
            logger.error(f"Wake word listener error: {e}", exc_info=True)

    def _keyboard_fallback(self):
        """
        Fallback for testing without a microphone or openWakeWord.
        Press Enter to simulate wake word detection.
        """
        print("\n[SAM] Keyboard fallback mode. Press ENTER to speak to SAM. Type 'quit' to exit.\n")
        while self._running:
            try:
                user_input = input()
                if user_input.lower() == "quit":
                    self._running = False
                    break
                self.callback()
            except (EOFError, KeyboardInterrupt):
                break

    def start(self):
        """Start listening. Blocks until stop() is called."""
        self._running = True
        self._load_model()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        self._thread.join()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Wake word listener stopped")
