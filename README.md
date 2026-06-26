# SAM — Personal AI Assistant

**Self-learning Autonomous Mind with Hermes Intelligence & Taste Heuristics Architecture**

> Fully local · Privacy-first · Voice-controlled · Self-improving · Founder Mode

---

## What SAM Does

- Listens for your wake word 24/7 at near-zero CPU cost
- Understands your speech via Whisper STT
- Thinks with Qwen 2.5 14B running entirely on your machine
- Speaks back with Kokoro TTS
- Controls your Mac — mouse, keyboard, apps, browser, terminal
- Remembers everything across sessions via ChromaDB + SQLite
- Learns your taste, decisions, and reasoning via **Founder Mode**
- Zero cloud. Zero API keys. Zero subscription.

---

## Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Chip | M2 (Apple Silicon) | M3 |
| RAM | 16GB | 16GB+ |
| Storage | 256GB free | 512GB |
| macOS | Ventura (13) | Sonoma (14) |

---

## Setup (One Time)

```bash
# 1. Clone the repo
git clone https://github.com/suradadhanush/SAM
cd SAM

# 2. Run setup (installs everything — takes 15-30 min first time)
chmod +x setup.sh
./setup.sh
```

Setup does all of this automatically:
- Installs Ollama
- Pulls Qwen 2.5 14B (auto-selects model based on your RAM)
- Pulls nomic-embed-text (embeddings)
- Pulls Moondream (vision)
- Creates Python virtual environment
- Installs all Python packages
- Installs Playwright + Chromium
- Sets up launchd agent so SAM starts on every boot

---

## Running SAM

### Start SAM

```bash
# Activate virtual environment
source .venv/bin/activate

# Start SAM
python main.py
```

Or if already set up with launchd, SAM starts automatically on boot.

### Wake SAM

Say: **"Hey SAM"**

First time after boot: SAM loads Qwen (~20 seconds). Says *"SAM is ready."*

After first load: responds immediately until you say *"SAM sleep"* or shut down.

---

## Voice Commands

| You say | SAM does |
|---|---|
| "Hey SAM, what's 15% of 3400?" | Calculates and tells you |
| "Hey SAM, open Safari" | Opens Safari via AppleScript |
| "Hey SAM, take a screenshot" | Takes screenshot |
| "Hey SAM, read my screen" | Describes what's on screen |
| "Hey SAM, go to github.com" | Opens URL in browser |
| "Hey SAM, run ls in terminal" | Executes terminal command |
| "Hey SAM, incognito mode" | Switches to incognito — nothing stored |
| "Hey SAM, exit incognito" | Back to normal mode |
| "SAM sleep" | Unloads model from RAM |
| "SAM stop" | Shuts down completely |

---

## Founder Mode

Founder Mode is SAM's taste layer — the feature no competitor has.

Every time you:
- Reject something and explain why → stored permanently
- Make a decision → stored with your reasoning
- Express a preference → captured

Next session SAM starts already knowing your taste.

### Manual Founder Mode CLI

```bash
# Add a decision
python sam_cli.py decision "Using FastAPI over Flask" "Django is overkill for skill endpoints, FastAPI is faster" --category tech

# Add a rejection
python sam_cli.py rejection "Dark mode with pure black background" "Too harsh on eyes, prefer dark grey #1a1a1a" --category design

# View all decisions
python sam_cli.py founder

# Export full decision log
python sam_cli.py export
```

---

## CLI Reference

```bash
# Status check
python sam_cli.py status

# View logs (last 50 lines)
python sam_cli.py logs

# View recent memories
python sam_cli.py memory

# View Founder Mode
python sam_cli.py founder

# List compiled skills
python sam_cli.py skills

# Export Founder Mode to JSON
python sam_cli.py export
```

---

## Architecture

```
SAM/
├── main.py              ← Entry point
├── sam_cli.py           ← CLI management tool
├── setup.sh             ← One-command setup
├── requirements.txt     ← Python dependencies
├── config/
│   ├── settings.py      ← All config with auto-detection
│   └── settings.yaml    ← Override any setting here
├── ears/
│   ├── wake_word.py     ← openWakeWord (24/7, ~0% CPU)
│   └── stt.py           ← Whisper STT (activates on wake)
├── core/
│   ├── brain.py         ← Qwen 2.5 14B via Ollama
│   └── session.py       ← Session context management
├── mouth/
│   └── tts.py           ← Kokoro TTS + Piper fallback
├── hands/
│   ├── control/         ← PyAutoGUI + AppleScript
│   ├── vision/          ← Moondream screen reader
│   ├── browser/         ← Playwright browser agent
│   └── terminal/        ← Sandboxed terminal runner
├── memory/
│   ├── identity.py      ← User profile (always loaded)
│   ├── store.py         ← ChromaDB + SQLite write
│   └── retrieve.py      ← Semantic memory search
├── founder_mode/
│   └── manager.py       ← Decisions, rejections, taste profile
├── agent/
│   └── react_loop.py    ← ReAct multi-step task execution
├── skills/
│   └── compiler.py      ← Auto-compiles repeated tasks
└── logs/                ← Runtime logs
```

---

## Session Flow

```
Boot → openWakeWord starts (always on, ~0% CPU)
     ↓
"Hey SAM" detected
     ↓
Whisper STT activated → transcribes speech
     ↓
Identity loaded + memories retrieved + Founder Mode context injected
     ↓
Qwen 2.5 14B processes full context
     ↓
Agent decides: conversation | control | browser | terminal | vision
     ↓
Action executed (if needed) → observed → next step decided (ReAct)
     ↓
Kokoro TTS speaks response
     ↓
Memory extracted + saved
     ↓
Back to listening
```

---

## Privacy

- **Zero cloud.** Nothing leaves your machine. Ever.
- **Incognito mode.** Cryptographically no storage — not even locally.
- **Your data is yours.** All memory in local SQLite + ChromaDB.
- **Open source.** AGPL v3. Audit every line.

---

## License

AGPL v3 for open source use.
Commercial license available for products built on SAM.

---

## Built By

Dhanush Surada — Visakhapatnam, India
github.com/suradadhanush | linkedin.com/in/dhanushsurada

Waitlist: smtg-is-cmg.carrd.co
