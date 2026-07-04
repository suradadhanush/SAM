"""
THE EARS — Part 1: Wake Word Detection
Uses openWakeWord for passive 24/7 listening.
Near-zero CPU. Triggers callback when wake word detected.
Falls back to keyboard input if model files missing.
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
        self._use_keyboard = False

    def _load_model(self):
        """Load openWakeWord model with proper error handling."""
        try:
            # Download default models if missing
            import openwakeword
            openwakeword.utils.download_models()

            from openwakeword.model import Model
            self._model = Model(
                wakeword_models=["hey_jarvis"],  # closest to "hey sam" available
                inference_framework="onnx"
            )
            logger.info("openWakeWord model loaded")

        except Exception as e:
            logger.warning(f"openWakeWord failed ({e}) — using keyboard fallback")
            self._model = None
            self._use_keyboard = True

    def _listen_loop(self):
        """Main listening loop."""
        if self._use_keyboard or self._model is None:
            logger.info("Keyboard fallback mode active")
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
                        threading.Thread(
                            target=self.callback,
                            daemon=True
                        ).start()
                        import time
                        time.sleep(2)
                        break

            stream.stop_stream()
            stream.close()
            audio.terminate()

        except Exception as e:
            logger.error(f"Wake word listener error: {e} — switching to keyboard")
            self._keyboard_fallback()

    def _keyboard_fallback(self):
        """
        Press ENTER to trigger SAM.
        This is the active mode until openWakeWord models are confirmed working.
        """
        print("\n" + "="*50)
        print("SAM KEYBOARD MODE")
        print("Press ENTER to speak to SAM")
        print("Type 'quit' to exit")
        print("="*50 + "\n")

        while self._running:
            try:
                user_input = input(">> Press ENTER to activate SAM: ")
                if user_input.lower().strip() == "quit":
                    self._running = False
                    break
                threading.Thread(target=self.callback, daemon=True).start()
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
