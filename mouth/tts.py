"""
THE MOUTH — Text to Speech
Cross-platform: macOS + Windows

Primary:  Kokoro TTS (82M params, Apache 2.0, best quality)
Fallback: Piper TTS (fastest, MIT)
Last resort: macOS `say` or Windows `pyttsx3`

Platform is auto-detected at runtime. Zero config needed.
"""

import logging
import os
import sys
import tempfile
import subprocess
import platform
from pathlib import Path

logger = logging.getLogger("SAM.TTS")

PLATFORM = platform.system()  # "Darwin" | "Windows" | "Linux"
IS_MAC = PLATFORM == "Darwin"
IS_WIN = PLATFORM == "Windows"


class TextToSpeech:
    def __init__(self, settings):
        self.settings = settings
        self._kokoro_pipeline = None
        self._kokoro_loaded = False
        self._pyttsx3_engine = None
        logger.info(f"TTS initialised for platform: {PLATFORM}")

    # ─── Public ───────────────────────────────────────────────────────────

    def speak(self, text: str):
        """Convert text to speech and play it. Fully cross-platform."""
        if not text or not text.strip():
            return

        text = self._clean_for_speech(text)
        logger.info(f"Speaking: {text[:80]}...")

        # Try in priority order — stop at first success
        engines = self._get_engine_order()
        for engine in engines:
            try:
                engine(text)
                return
            except Exception as e:
                logger.warning(f"TTS engine failed ({engine.__name__}): {e}")
                continue

        # Absolute last resort — print to console so user isn't left silent
        logger.error("All TTS engines failed — printing to console")
        print(f"\n[SAM]: {text}\n")

    # ─── Engine Priority ──────────────────────────────────────────────────

    def _get_engine_order(self):
        """Return ordered list of TTS methods to try based on settings + platform."""
        engine_name = getattr(self.settings, "tts_engine", "kokoro")

        if engine_name == "kokoro":
            order = [self._speak_kokoro, self._speak_piper, self._speak_system]
        elif engine_name == "piper":
            order = [self._speak_piper, self._speak_kokoro, self._speak_system]
        elif engine_name == "system":
            order = [self._speak_system]
        elif engine_name == "none":
            # Silent mode — just print
            order = [self._speak_print]
        else:
            order = [self._speak_kokoro, self._speak_piper, self._speak_system]

        return order

    # ─── Kokoro ───────────────────────────────────────────────────────────

    def _speak_kokoro(self, text: str):
        """Kokoro TTS — best quality, Apache 2.0."""
        if not self._kokoro_loaded:
            self._load_kokoro()

        if self._kokoro_pipeline is None:
            raise RuntimeError("Kokoro not available")

        # Kokoro returns a generator of (graphemes, phonemes, audio) tuples
        import numpy as np
        voice = getattr(self.settings, "kokoro_voice", "af_bella")
        speed = getattr(self.settings, "speech_rate", 1.0)
        
        audio_chunks = []
        sample_rate = 24000  # Kokoro default
        
        for result in self._kokoro_pipeline(text, voice=voice, speed=speed):
            # result is (graphemes, phonemes, audio) in newer Kokoro
            if isinstance(result, tuple):
                audio_chunk = result[-1]  # audio is always last
            else:
                audio_chunk = result
            if audio_chunk is not None:
                audio_chunks.append(audio_chunk)
        
        if audio_chunks:
            audio = np.concatenate(audio_chunks)
            self._play_audio_array(audio, sample_rate)

    def _load_kokoro(self):
        try:
            from kokoro import KPipeline
            self._kokoro_pipeline = KPipeline(lang_code="a")
            self._kokoro_loaded = True
            logger.info("Kokoro TTS loaded")
        except ImportError:
            logger.warning("Kokoro not installed — pip install kokoro")
            self._kokoro_loaded = True
            self._kokoro_pipeline = None

    # ─── Piper ────────────────────────────────────────────────────────────

    def _speak_piper(self, text: str):
        """Piper TTS — fastest, MIT, cross-platform binary."""
        piper_cmd = self._find_piper()
        if not piper_cmd:
            raise RuntimeError("Piper binary not found in PATH")

        model = getattr(self.settings, "piper_model", "en_US-lessac-medium")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [piper_cmd, "--model", model, "--output_file", tmp_path]
            subprocess.run(
                cmd,
                input=text.encode(),
                capture_output=True,
                check=True,
                timeout=30
            )
            self._play_audio_file(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _find_piper(self):
        """Find piper binary cross-platform."""
        import shutil
        # Try PATH first
        found = shutil.which("piper")
        if found:
            return found
        # Windows common locations
        if IS_WIN:
            candidates = [
                r"C:\piper\piper.exe",
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "piper", "piper.exe")
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
        return None

    # ─── System TTS ───────────────────────────────────────────────────────

    def _speak_system(self, text: str):
        """
        Platform-native TTS as last resort.
        macOS: `say` command
        Windows: pyttsx3 (wraps SAPI5)
        """
        if IS_MAC:
            self._speak_mac_say(text)
        elif IS_WIN:
            self._speak_pyttsx3(text)
        else:
            raise RuntimeError("No system TTS available on this platform")

    def _speak_mac_say(self, text: str):
        """macOS built-in say command."""
        subprocess.run(["say", text], timeout=60, check=True)

    def _speak_pyttsx3(self, text: str):
        """Windows SAPI5 via pyttsx3."""
        if self._pyttsx3_engine is None:
            try:
                import pyttsx3
                self._pyttsx3_engine = pyttsx3.init()
                rate = self._pyttsx3_engine.getProperty("rate")
                self._pyttsx3_engine.setProperty("rate", int(rate * getattr(self.settings, "speech_rate", 1.0)))
                logger.info("pyttsx3 (Windows SAPI5) loaded")
            except ImportError:
                raise RuntimeError("pyttsx3 not installed — pip install pyttsx3")

        self._pyttsx3_engine.say(text)
        self._pyttsx3_engine.runAndWait()

    def _speak_print(self, text: str):
        """Silent mode — print instead of speak."""
        print(f"\n[SAM]: {text}\n")

    # ─── Audio Playback ───────────────────────────────────────────────────

    def _play_audio_array(self, audio, sample_rate: int):
        """
        Play a numpy audio array.
        Tries sounddevice first (cross-platform), falls back to file-based playback.
        """
        try:
            import sounddevice as sd
            sd.play(audio, sample_rate)
            sd.wait()
            return
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"sounddevice playback failed: {e}")

        # Fallback: write to file and play via platform method
        try:
            import soundfile as sf
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, audio, sample_rate)
                self._play_audio_file(tmp.name)
                os.unlink(tmp.name)
        except Exception as e:
            raise RuntimeError(f"All audio playback methods failed: {e}")

    def _play_audio_file(self, path: str):
        """
        Play a WAV/audio file cross-platform.
        macOS: afplay
        Windows: PowerShell / winsound
        """
        if IS_MAC:
            subprocess.run(["afplay", path], timeout=120, check=True)

        elif IS_WIN:
            # Try PowerShell media player first (no dependencies)
            try:
                ps_cmd = (
                    f'$player = New-Object System.Media.SoundPlayer("{path}"); '
                    f'$player.PlaySync()'
                )
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    timeout=120,
                    check=True,
                    capture_output=True
                )
            except Exception:
                # Fallback to winsound (built into Python on Windows)
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)

        else:
            # Linux fallback
            for cmd in [["aplay", path], ["paplay", path], ["ffplay", "-nodisp", "-autoexit", path]]:
                try:
                    subprocess.run(cmd, timeout=120, check=True, capture_output=True)
                    return
                except Exception:
                    continue
            raise RuntimeError("No audio player found on Linux")

    # ─── Text Cleaning ────────────────────────────────────────────────────

    def _clean_for_speech(self, text: str) -> str:
        """Strip markdown and symbols that sound bad when spoken."""
        import re
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        text = re.sub(r'#{1,6}\s', '', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        text = re.sub(r'^[\-\*]\s', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n+', '. ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
