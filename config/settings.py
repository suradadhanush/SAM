"""
SAM Configuration
All persistent data lives in ~/.sam_data — outside the SAM install folder.
Wipe SAM, reinstall, clone fresh — your identity and memory survive.
"""

import yaml
import os
import platform
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

CONFIG_PATH = Path(__file__).parent / "settings.yaml"
BASE_DIR = Path(__file__).parent.parent

# All user data lives here — persistent across reinstalls
SAM_DATA_DIR = Path.home() / ".sam_data"

PLATFORM = platform.system()
IS_MAC = PLATFORM == "Darwin"
IS_WIN = PLATFORM == "Windows"


def _ensure_data_dirs():
    """Create ~/.sam_data structure if it doesn't exist."""
    dirs = [
        SAM_DATA_DIR,
        SAM_DATA_DIR / "memory" / "chroma",
        SAM_DATA_DIR / "founder_mode",
        SAM_DATA_DIR / "founder_mode" / "export",
        SAM_DATA_DIR / "skills" / "compiled",
        SAM_DATA_DIR / "logs",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

_ensure_data_dirs()


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
    whisper_model: str = "base.en"
    whisper_device: str = "auto"
    recording_timeout: float = 8.0
    silence_threshold: float = 0.01

    # Mouth
    tts_engine: str = "kokoro"
    kokoro_voice: str = "af_bella"
    piper_model: str = "en_US-lessac-medium"
    speech_rate: float = 1.0

    # Vision
    vision_model: str = "moondream"
    screenshot_quality: int = 85

    # Memory — all in ~/.sam_data
    chroma_path: str = str(SAM_DATA_DIR / "memory" / "chroma")
    sqlite_path: str = str(SAM_DATA_DIR / "memory" / "episodic.db")
    memory_top_k: int = 5
    embedding_model: str = "nomic-embed-text"

    # Founder Mode — in ~/.sam_data
    founder_mode_enabled: bool = True
    founder_mode_path: str = str(SAM_DATA_DIR / "founder_mode")
    # v2: LLM-based auto-capture (Evidence + Confidence). Falls back to a
    # lightweight heuristic if Ollama/the classifier is unavailable.
    founder_mode_llm_capture: bool = True
    founder_mode_classifier_model: Optional[str] = None  # None -> uses primary_model
    founder_mode_min_confidence_to_show: float = 0.3

    # Phase 1 — Planner + Reflection (agent/planner.py, agent/reflection.py)
    # Both default to reusing primary_model if unset.
    planner_model: Optional[str] = None
    reflection_model: Optional[str] = None

    # main.py execution wiring — real autonomous actions. Default False:
    # commands like rm/mv/sudo/kill get refused with a clear message
    # instead of running silently. Opt in deliberately.
    allow_risky_terminal_commands: bool = False

    # Phase 2 — Telegram bridge (ecosystem/telegram_bridge.py).
    # This is an internet-relay bridge, NOT local-WiFi ecosystem — command
    # text passes through Telegram's servers. See docs/PHASE_2_TELEGRAM_BRIDGE.md.
    telegram_bot_token: str = ""       # from @BotFather
    telegram_bot_username: str = ""    # bot's @username, without the @

    # Skills — in ~/.sam_data
    skills_path: str = str(SAM_DATA_DIR / "skills")
    compiled_skills_path: str = str(SAM_DATA_DIR / "skills" / "compiled")

    # Runtime
    incognito: bool = False
    log_level: str = "INFO"
    log_path: str = str(SAM_DATA_DIR / "logs" / "sam.log")

    # Hardware
    detected_ram_gb: Optional[int] = None
    detected_platform: str = PLATFORM

    def __post_init__(self):
        self._load_yaml()
        self._detect_hardware()
        self._select_model()

    def _load_yaml(self):
        # Check ~/.sam_data/settings.yaml first (user overrides)
        user_config = SAM_DATA_DIR / "settings.yaml"
        config_file = user_config if user_config.exists() else CONFIG_PATH
        if config_file.exists():
            with open(config_file) as f:
                data = yaml.safe_load(f) or {}
            for key, value in data.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def _detect_hardware(self):
        try:
            import subprocess
            if IS_MAC:
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True
                )
                self.detected_ram_gb = int(result.stdout.strip()) // (1024 ** 3)
            elif IS_WIN:
                result = subprocess.run(
                    ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                    capture_output=True, text=True
                )
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip().isdigit()]
                if lines:
                    self.detected_ram_gb = int(lines[0]) // (1024 ** 3)
        except Exception:
            self.detected_ram_gb = 16

    def _select_model(self):
        if self.detected_ram_gb is None:
            return
        if self.detected_ram_gb >= 32:
            self.primary_model = "qwen2.5:32b"
        elif self.detected_ram_gb >= 16:
            self.primary_model = "qwen2.5:14b"
        else:
            self.primary_model = "qwen2.5:7b"

    def save(self):
        data = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        with open(SAM_DATA_DIR / "settings.yaml", "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    @staticmethod
    def data_dir() -> Path:
        return SAM_DATA_DIR
