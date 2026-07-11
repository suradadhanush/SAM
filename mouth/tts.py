"""
THE MOUTH — Text to Speech
Cross-platform: macOS + Windows

Primary:  Kokoro TTS (82M params, Apache 2.0, best quality)
Fallback: Piper TTS (fastest, MIT)
Last resort: macOS `say` or Windows `pyttsx3`
"""

import logging
import os
import tempfile
import subprocess
import platform

logger = logging.getLogger("SAM.TTS")

PLATFORM = platform.system()
IS_MAC = PLATFORM == "Darwin"
IS_WIN = PLATFORM == "Windows"


class TextToSpeech:
    def __init__(self, settings):
        self.settings = settings
        self._kokoro_pipeline = None
        self._kokoro_loaded = False
        self._pyttsx3_engine = None
        # Latency fix: engines that fail once are skipped for the rest of
        # this run instead of being retried every single turn. In real
        # testing, Kokoro/Piper failing-then-falling-through was costing
        # ~10+ seconds of wasted retry time on every response. Clears
        # naturally on restart, so fixing the underlying issue (e.g.
        # installing Piper) takes effect next run.
        self._known_bad_engines = set()
        logger.info(f"TTS initialised for platform: {PLATFORM}")

    def speak(self, text: str):
        if not text or not text.strip():
            return
        text = self._clean_for_speech(text)
        logger.info(f"Speaking: {text[:80]}...")

        for engine in self._get_engine_order():
            if engine.__name__ in self._known_bad_engines:
                continue
            try:
                engine(text)
                return
            except Exception as e:
                logger.warning(f"TTS engine failed ({engine.__name__}): {e} "
                                f"— skipping it for the rest of this session")
                self._known_bad_engines.add(engine.__name__)

        self._speak_print(text)

    def _get_engine_order(self):
        engine_name = getattr(self.settings, "tts_engine", "kokoro")
        if engine_name == "kokoro":
            return [self._speak_kokoro, self._speak_piper, self._speak_system]
        elif engine_name == "piper":
            return [self._speak_piper, self._speak_kokoro, self._speak_system]
        elif engine_name == "system":
            return [self._speak_system]
        elif engine_name == "none":
            return [self._speak_print]
        return [self._speak_kokoro, self._speak_piper, self._speak_system]

    # ─── Kokoro ───────────────────────────────────────────────────────────

    def _speak_kokoro(self, text: str):
        if not self._kokoro_loaded:
            self._load_kokoro()
        if self._kokoro_pipeline is None:
            raise RuntimeError("Kokoro not available")

        import numpy as np
        voice = getattr(self.settings, "kokoro_voice", "af_bella")
        speed = getattr(self.settings, "speech_rate", 1.0)
        sample_rate = 24000

        audio_chunks = []
        for result in self._kokoro_pipeline(text, voice=voice, speed=speed):
            # Kokoro yields (graphemes, phonemes, audio) tuples
            if isinstance(result, (tuple, list)):
                chunk = result[-1]
            else:
                chunk = result

            if chunk is None:
                continue

            # Ensure it's a proper 1D numpy array
            try:
                chunk = np.array(chunk, dtype=np.float32).flatten()
                if chunk.size > 0:
                    audio_chunks.append(chunk)
            except Exception:
                continue

        if not audio_chunks:
            raise RuntimeError("Kokoro produced no audio")

        audio = np.concatenate(audio_chunks)
        self._play_audio_array(audio, sample_rate)

    def _load_kokoro(self):
        try:
            from kokoro import KPipeline
            self._kokoro_pipeline = KPipeline(lang_code="a")
            self._kokoro_loaded = True
            logger.info("Kokoro TTS loaded")
        except ImportError:
            logger.warning("Kokoro not installed")
            self._kokoro_loaded = True
            self._kokoro_pipeline = None

    # ─── Piper ────────────────────────────────────────────────────────────

    def _speak_piper(self, text: str):
        import shutil
        piper_cmd = shutil.which("piper")
        if not piper_cmd:
            raise RuntimeError("Piper not found in PATH")

        model = getattr(self.settings, "piper_model", "en_US-lessac-medium")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                [piper_cmd, "--model", model, "--output_file", tmp_path],
                input=text.encode(),
                capture_output=True,
                check=True,
                timeout=30
            )
            self._play_audio_file(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # ─── System TTS ───────────────────────────────────────────────────────

    def _speak_system(self, text: str):
        if IS_MAC:
            subprocess.run(["say", text], timeout=60, check=True)
        elif IS_WIN:
            self._speak_pyttsx3(text)
        else:
            raise RuntimeError("No system TTS on this platform")

    def _speak_pyttsx3(self, text: str):
        if self._pyttsx3_engine is None:
            import pyttsx3
            self._pyttsx3_engine = pyttsx3.init()
        self._pyttsx3_engine.say(text)
        self._pyttsx3_engine.runAndWait()

    def _speak_print(self, text: str):
        print(f"\n[SAM]: {text}\n")

    # ─── Audio Playback ───────────────────────────────────────────────────

    def _play_audio_array(self, audio, sample_rate: int):
        try:
            import sounddevice as sd
            sd.play(audio, sample_rate)
            sd.wait()
            return
        except Exception as e:
            logger.warning(f"sounddevice failed: {e}")

        try:
            import soundfile as sf
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, audio, sample_rate)
                self._play_audio_file(tmp.name)
                os.unlink(tmp.name)
        except Exception as e:
            raise RuntimeError(f"Audio playback failed: {e}")

    def _play_audio_file(self, path: str):
        if IS_MAC:
            subprocess.run(["afplay", path], timeout=120, check=True)
        elif IS_WIN:
            try:
                ps_cmd = f'$p=New-Object System.Media.SoundPlayer("{path}");$p.PlaySync()'
                subprocess.run(["powershell", "-Command", ps_cmd], timeout=120, check=True, capture_output=True)
            except Exception:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME)
        else:
            for cmd in [["aplay", path], ["paplay", path]]:
                try:
                    subprocess.run(cmd, timeout=120, check=True, capture_output=True)
                    return
                except Exception:
                    continue

    # ─── Text Cleaning ────────────────────────────────────────────────────

    def _clean_for_speech(self, text: str) -> str:
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
