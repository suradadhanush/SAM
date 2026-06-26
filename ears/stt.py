"""
THE EARS — Part 2: Speech to Text
Uses faster-whisper (whisper.cpp Python bindings) for transcription.
Only activates AFTER wake word is detected.
Records until silence, then transcribes.
"""

import logging
import tempfile
import os
import time
import numpy as np
from pathlib import Path

logger = logging.getLogger("SAM.STT")


class SpeechToText:
    def __init__(self, settings):
        self.settings = settings
        self._model = None
        self._model_loaded = False

    def _load_model(self):
        """Lazy load Whisper model — only when needed."""
        if self._model_loaded:
            return

        logger.info(f"Loading Whisper model: {self.settings.whisper_model}")
        try:
            from faster_whisper import WhisperModel

            device = "auto"
            compute_type = "int8"

            # Apple Silicon detection
            import platform
            if platform.processor() == "arm" or "Apple" in platform.processor():
                device = "cpu"
                compute_type = "int8"

            self._model = WhisperModel(
                self.settings.whisper_model,
                device=device,
                compute_type=compute_type
            )
            self._model_loaded = True
            logger.info("Whisper model loaded")

        except ImportError:
            logger.warning("faster-whisper not installed. Using speech_recognition fallback.")
            self._model = None
            self._model_loaded = True

    def _record_audio(self) -> np.ndarray:
        """
        Record audio from microphone until silence or timeout.
        Returns numpy array of audio samples.
        """
        import pyaudio

        CHUNK = 1024
        FORMAT = pyaudio.paFloat32
        CHANNELS = 1
        RATE = 16000
        SILENCE_THRESHOLD = self.settings.silence_threshold
        TIMEOUT = self.settings.recording_timeout
        SILENCE_DURATION = 1.5  # seconds of silence before stopping

        audio = pyaudio.PyAudio()
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        logger.info("Recording...")
        frames = []
        silent_chunks = 0
        max_silent_chunks = int(RATE / CHUNK * SILENCE_DURATION)
        start_time = time.time()
        speaking_started = False

        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            chunk = np.frombuffer(data, dtype=np.float32)
            frames.append(chunk)

            volume = np.abs(chunk).mean()

            if volume > SILENCE_THRESHOLD:
                speaking_started = True
                silent_chunks = 0
            elif speaking_started:
                silent_chunks += 1
                if silent_chunks >= max_silent_chunks:
                    logger.info("Silence detected — stopping recording")
                    break

            if time.time() - start_time > TIMEOUT:
                logger.info("Recording timeout reached")
                break

        stream.stop_stream()
        stream.close()
        audio.terminate()

        return np.concatenate(frames) if frames else np.array([])

    def listen(self) -> str:
        """
        Record speech and transcribe to text.
        Returns transcribed string or empty string on failure.
        """
        self._load_model()

        try:
            audio_data = self._record_audio()

            if audio_data.size == 0:
                return ""

            if self._model is None:
                return self._fallback_transcribe(audio_data)

            # Save to temp file for Whisper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            import soundfile as sf
            sf.write(tmp_path, audio_data, 16000)

            logger.info("Transcribing...")
            segments, info = self._model.transcribe(
                tmp_path,
                language="en",
                beam_size=5,
                vad_filter=True
            )

            transcript = " ".join(seg.text for seg in segments).strip()
            os.unlink(tmp_path)

            logger.info(f"Transcribed: '{transcript}'")
            return transcript

        except Exception as e:
            logger.error(f"STT error: {e}", exc_info=True)
            return ""

    def _fallback_transcribe(self, audio_data: np.ndarray) -> str:
        """Fallback using speech_recognition library."""
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                import soundfile as sf
                sf.write(tmp.name, audio_data, 16000)
                with sr.AudioFile(tmp.name) as source:
                    audio = recognizer.record(source)
                os.unlink(tmp.name)
            return recognizer.recognize_google(audio)
        except Exception as e:
            logger.error(f"Fallback STT error: {e}")
            return ""
