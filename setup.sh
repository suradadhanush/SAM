#!/bin/bash
# SAM Setup Script
# Run once on your Mac after cloning the repo.
# Usage: chmod +x setup.sh && ./setup.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "  ╔═══════════════════════════════════╗"
echo "  ║          SAM — Setup              ║"
echo "  ║  Personal AI. Fully Local.        ║"
echo "  ╚═══════════════════════════════════╝"
echo -e "${NC}"

# ─── Check macOS ──────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}ERROR: SAM setup requires macOS${NC}"
    exit 1
fi

# ─── Check Apple Silicon ──────────────────────────────────────────────────
CHIP=$(uname -m)
if [[ "$CHIP" != "arm64" ]]; then
    echo -e "${YELLOW}WARNING: Intel Mac detected. Performance will be significantly lower.${NC}"
    echo -e "${YELLOW}SAM is optimised for Apple Silicon (M1/M2/M3).${NC}"
fi

echo -e "${GREEN}[1/8] Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo "Python3 not found. Installing via Homebrew..."
    if ! command -v brew &> /dev/null; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    fi
    brew install python3
fi
if command -v python3.11 >/dev/null 2>&1; then
    PYTHON=python3.11
elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
else
    PYTHON=python3
fi

PYTHON_VERSION=$($PYTHON --version)
echo "  Found: $PYTHON_VERSION"

echo -e "${GREEN}[2/8] Installing Ollama...${NC}"
if ! command -v ollama &> /dev/null; then
    echo "  Downloading Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    echo "  Ollama installed"
else
    echo "  Ollama already installed"
fi

echo -e "${GREEN}[3/8] Starting Ollama...${NC}"
ollama serve &>/dev/null &
OLLAMA_PID=$!
sleep 3

echo -e "${GREEN}[4/8] Pulling AI models (this takes time — grab a coffee)...${NC}"

# Detect RAM to pull right model
RAM_GB=$(sysctl -n hw.memsize | awk '{print int($1/1073741824)}')
echo "  Detected RAM: ${RAM_GB}GB"

if [ "$RAM_GB" -ge 32 ]; then
    MODEL="qwen2.5:32b"
elif [ "$RAM_GB" -ge 16 ]; then
    MODEL="qwen2.5:14b"
else
    MODEL="qwen2.5:7b"
fi

echo "  Pulling brain model: $MODEL"
ollama pull $MODEL

echo "  Pulling embedding model: nomic-embed-text"
ollama pull nomic-embed-text

echo "  Pulling vision model: moondream"
ollama pull moondream

echo -e "${GREEN}[5/8] Creating Python virtual environment...${NC}"

if command -v python3.11 >/dev/null 2>&1; then
    PYTHON=python3.11
elif command -v python3.12 >/dev/null 2>&1; then
    PYTHON=python3.12
else
    PYTHON=python3
fi

echo "  Using Python: $($PYTHON --version)"

$PYTHON -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet

echo -e "${GREEN}[6/8] Installing Python packages...${NC}"
pip install -r requirements.txt --quiet

echo "  Installing Playwright browsers..."
playwright install chromium

echo -e "${GREEN}[7/8] Creating directory structure...${NC}"
mkdir -p logs
mkdir -p memory/store/chroma
mkdir -p founder_mode/store
mkdir -p founder_mode/export
mkdir -p skills/compiled
mkdir -p skills/library

echo -e "${GREEN}[8/8] Installing launchd agent (auto-start on boot)...${NC}"
PLIST_PATH="$HOME/Library/LaunchAgents/ai.sam.assistant.plist"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>ai.sam.assistant</string>
    <key>ProgramArguments</key>
    <array>
        <string>$SCRIPT_DIR/.venv/bin/python3</string>
        <string>$SCRIPT_DIR/main.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/logs/sam.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/logs/sam_error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH" 2>/dev/null || true
echo "  launchd agent installed at $PLIST_PATH"

echo ""
echo -e "${BLUE}╔═══════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║                 SAM Setup Complete!                  ║${NC}"
echo -e "${BLUE}╠═══════════════════════════════════════════════════════╣${NC}"
echo -e "${BLUE}║  Brain model: ${GREEN}$MODEL${BLUE}                       ║${NC}"
echo -e "${BLUE}║                                                       ║${NC}"
echo -e "${BLUE}║  To start SAM now:                                    ║${NC}"
echo -e "${BLUE}║  ${GREEN}source .venv/bin/activate && python main.py${BLUE}        ║${NC}"
echo -e "${BLUE}║                                                       ║${NC}"
echo -e "${BLUE}║  SAM will auto-start on every boot via launchd.      ║${NC}"
echo -e "${BLUE}║  Say ${GREEN}'Hey SAM'${BLUE} to wake it.                         ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════╝${NC}"
echo ""
