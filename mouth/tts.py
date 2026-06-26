"""
THE MOUTH — Text to Speech
Primary: Kokoro TTS (82M params, Apache 2.0, best quality)
Fallback: Piper TTS (fastest, MIT, low RAM)
Speaks SAM's responses out loud.
"""

import logging
import os
import tempfile
import subprocess
from pathlib import Path

logger = logging.getLogger("SAM.TTS")


class TextToSpeech:
    def __init__(self, settings):
        self.settings = settings
        self._kokoro_pipeline = None
        self._kokoro_loaded = False

    def speak(self, text: str):
        """Convert text to speech and play it."""
        if not text or not text.strip():
            return

        # Clean text for speech — remove markdown artifacts
        text = self._clean_for_speech(text)

        logger.info(f"Speaking: {text[:80]}...")

        try:
            if self.settings.tts_engine == "kokoro":
                self._speak_kokoro(text)
            else:
                self._speak_piper(text)
        except Exception as e:
            logger.error(f"TTS error with {self.settings.tts_engine}: {e}")
            logger.info("Trying piper fallback...")
            try:
                self._speak_piper(text)
            except Exception as e2:
                logger.error(f"Piper fallback also failed: {e2}")
                # Last resort — system say command on macOS
                self._speak_system(text)

    def _speak_kokoro(self, text: str):
        """Speak using Kokoro TTS."""
        if not self._kokoro_loaded:
            self._load_kokoro()

        if self._kokoro_pipeline is None:
            raise RuntimeError("Kokoro not available")

        audio, sample_rate = self._kokoro_pipeline(
            text,
            voice=self.settings.kokoro_voice,
            speed=self.settings.speech_rate
        )

        self._play_audio(audio, sample_rate)

    def _load_kokoro(self):
        """Lazy load Kokoro pipeline."""
        try:
            from kokoro import KPipeline
            self._kokoro_pipeline = KPipeline(lang_code="a")  # American English
            self._kokoro_loaded = True
            logger.info("Kokoro TTS loaded")
        except ImportError:
            logger.warning("Kokoro not installed — will use Piper")
            self._kokoro_loaded = True
            self._kokoro_pipeline = None

    def _speak_piper(self, text: str):
        """Speak using Piper TTS via command line."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                "piper",
                "--model", self.settings.piper_model,
                "--output_file", tmp_path
            ]
            subprocess.run(
                cmd,
                input=text.encode(),
                capture_output=True,
                check=True,
                timeout=30
            )
            self._play_file(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _speak_system(self, text: str):
        """macOS built-in say command — last resort."""
        subprocess.run(["say", text], timeout=30)

    def _play_audio(self, audio, sample_rate: int):
        """Play audio numpy array."""
        try:
            import sounddevice as sd
            sd.play(audio, sample_rate)
            sd.wait()
        except ImportError:
            # Save and play via afplay (macOS)
            import soundfile as sf
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, audio, sample_rate)
                self._play_file(tmp.name)
                os.unlink(tmp.name)

    def _play_file(self, path: str):
        """Play audio file using macOS afplay."""
        subprocess.run(["afplay", path], timeout=60)

    def _clean_for_speech(self, text: str) -> str:
        """Remove markdown and symbols that sound bad when spoken."""
        import re
        # Remove markdown
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'#{1,6}\s', '', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        # Remove bullet points
        text = re.sub(r'^[\-\*]\s', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s', '', text, flags=re.MULTILINE)
        # Clean up whitespace
        text = re.sub(r'\n+', '. ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
