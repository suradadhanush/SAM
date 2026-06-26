"""
SAM Configuration — All settings in one place.
Edit config/settings.yaml to change behaviour without touching code.
"""

import yaml
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


CONFIG_PATH = Path(__file__).parent / "settings.yaml"
BASE_DIR = Path(__file__).parent.parent


@dataclass
class Settings:
    # Identity
    assistant_name: str = "SAM"
    user_name: str = "Dhanush"

    # Brain
    ollama_host: str = "http://localhost:11434"
    primary_model: str = "qwen2.5:14b"
    fallback_model: str = "qwen2.5:7b"
    model_context_length: int = 8192
    temperature: float = 0.7
    max_tokens: int = 1024

    # Ears
    wake_word: str = "hey sam"
    wake_word_threshold: float = 0.5
    whisper_model: str = "base.en"          # tiny.en / base.en / small.en
    whisper_device: str = "auto"            # auto detects Apple Silicon
    recording_timeout: float = 8.0          # seconds to record after wake word
    silence_threshold: float = 0.01

    # Mouth
    tts_engine: str = "kokoro"              # kokoro | piper
    kokoro_voice: str = "af_bella"         # Kokoro voice name
    piper_model: str = "en_US-lessac-medium"
    speech_rate: float = 1.0

    # Vision
    vision_model: str = "moondream"         # moondream | llava
    screenshot_quality: int = 85

    # Memory
    chroma_path: str = str(BASE_DIR / "memory" / "store" / "chroma")
    sqlite_path: str = str(BASE_DIR / "memory" / "store" / "episodic.db")
    memory_top_k: int = 5
    embedding_model: str = "nomic-embed-text"

    # Founder Mode
    founder_mode_enabled: bool = True
    founder_mode_path: str = str(BASE_DIR / "founder_mode" / "store")

    # Skills
    skills_path: str = str(BASE_DIR / "skills")
    compiled_skills_path: str = str(BASE_DIR / "skills" / "compiled")

    # Runtime
    incognito: bool = False
    log_level: str = "INFO"
    log_path: str = str(BASE_DIR / "logs" / "sam.log")

    # Hardware (auto-detected on first run)
    detected_ram_gb: Optional[int] = None

    def __post_init__(self):
        self._load_yaml()
        self._detect_hardware()
        self._select_model()

    def _load_yaml(self):
        """Load overrides from settings.yaml if it exists."""
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                data = yaml.safe_load(f) or {}
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def _detect_hardware(self):
        """Detect RAM on macOS and set accordingly."""
        try:
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True
            )
            ram_bytes = int(result.stdout.strip())
            self.detected_ram_gb = ram_bytes // (1024 ** 3)
        except Exception:
            self.detected_ram_gb = 16  # Default assumption

    def _select_model(self):
        """Auto-select model based on detected RAM."""
        if self.detected_ram_gb is None:
            return
        if self.detected_ram_gb >= 32:
            self.primary_model = "qwen2.5:32b"
        elif self.detected_ram_gb >= 16:
            self.primary_model = "qwen2.5:14b"
        else:
            self.primary_model = "qwen2.5:7b"

    def save(self):
        """Persist current settings to YAML."""
        data = {
            k: v for k, v in self.__dict__.items()
            if not k.startswith("_")
        }
        with open(CONFIG_PATH, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
