#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# GramWrite — macOS / Linux Installer
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

GRAMWRITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$GRAMWRITE_DIR/.venv"
PYTHON_MIN="3.10"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

log()  { echo -e "${CYAN}▸${RESET} $*"; }
ok()   { echo -e "${GREEN}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "${RED}✗${RESET} $*" >&2; }
head() { echo -e "\n${BOLD}$*${RESET}"; }

# ── Banner ─────────────────────────────────────────────────────────────────────
echo -e "${DIM}"
echo "  ┌─────────────────────────────────────────┐"
echo "  │  G R A M W R I T E   v1.2.2             │"
echo "  │  The Invisible Editor for Screenwriters  │"
echo "  └─────────────────────────────────────────┘"
echo -e "${RESET}"

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS=$(uname -s)
case "$OS" in
    Darwin) PLATFORM="macos" ;;
    Linux)  PLATFORM="linux" ;;
    *)
        err "Unsupported OS: $OS"
        err "Use install.ps1 for Windows."
        exit 1
        ;;
esac
log "Detected platform: $PLATFORM"

# ── Python check ──────────────────────────────────────────────────────────────
head "Checking Python…"

PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$cmd"
            ok "Found $cmd ($ver)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    err "Python $PYTHON_MIN+ required."
    if [ "$PLATFORM" = "macos" ]; then
        echo "    Install via Homebrew:  brew install python@3.11"
    else
        echo "    Install via apt:       sudo apt install python3.11 python3.11-venv"
    fi
    exit 1
fi

# ── Virtual environment ────────────────────────────────────────────────────────
head "Setting up virtual environment…"

if [ -d "$VENV_DIR" ]; then
    warn "Existing venv found at .venv — reinstalling"
    rm -rf "$VENV_DIR"
fi

"$PYTHON" -m venv "$VENV_DIR"
ok "Virtual environment created at .venv"

source "$VENV_DIR/bin/activate"

# Upgrade pip silently
pip install --upgrade pip --quiet

# ── Core dependencies ─────────────────────────────────────────────────────────
head "Installing core dependencies…"

pip install aiohttp PyQt6 PyYAML --quiet
ok "Core packages installed"

# ── Platform-specific ─────────────────────────────────────────────────────────
head "Installing platform-specific packages ($PLATFORM)…"

if [ "$PLATFORM" = "macos" ]; then
    log "Installing pyobjc (Accessibility API)…"
    pip install \
        "pyobjc-framework-Cocoa>=10.0" \
        "pyobjc-framework-ApplicationServices>=10.0" \
        --quiet && ok "pyobjc installed" || warn "pyobjc failed — text extraction may not work"

elif [ "$PLATFORM" = "linux" ]; then
    log "Installing pyatspi (AT-SPI2)…"
    pip install "pyatspi>=2.46.0" --quiet && ok "pyatspi installed" \
        || warn "pyatspi failed — falling back to xclip method"

    # Check for xdotool / xclip
    for tool in xdotool xclip; do
        if command -v "$tool" &>/dev/null; then
            ok "$tool found"
        else
            warn "$tool not found — install with: sudo apt install $tool"
        fi
    done
fi

# ── Install GramWrite package ─────────────────────────────────────────────────
head "Installing GramWrite…"
pip install -e . --quiet
ok "GramWrite installed (editable mode)"

# ── Optional Harper helper ────────────────────────────────────────────────────
head "Checking optional Harper backend…"

HARPER_DIR="$GRAMWRITE_DIR/gramwrite/native/harper"
HARPER_OK=false

if command -v npm &>/dev/null; then
    log "Installing Harper helper dependencies…"
    if npm install --prefix "$HARPER_DIR" --silent; then
        ok "Harper helper installed"
        HARPER_OK=true
    else
        warn "Harper helper install failed — run: npm install --prefix \"$HARPER_DIR\""
    fi
else
    warn "npm not found — Harper backend will stay unavailable until Node.js is installed."
fi

# ── Check LLM Backend ─────────────────────────────────────────────────────────
head "Checking local backends…"

BACKEND_OK=false

if [ "$PLATFORM" = "macos" ]; then
    log "Apple Foundation Models can also be selected inside GramWrite on Apple Intelligence-enabled Macs."
fi

# Check Ollama
if curl -sf "http://localhost:11434/api/tags" &>/dev/null; then
    ok "Ollama is running at localhost:11434"
    BACKEND_OK=true
    # Pull default model if not present
    if ! curl -sf "http://localhost:11434/api/tags" | grep -q "qwen3.5"; then
        log "Pulling qwen3.5:0.8b (this may take a moment)…"
        ollama pull qwen3.5:0.8b && ok "qwen3.5:0.8b ready" || warn "Could not pull model — pull manually: ollama pull qwen3.5:0.8b"
    else
        ok "qwen3.5:0.8b already available"
    fi
elif command -v ollama &>/dev/null; then
    warn "Ollama installed but not running."
    echo "    Start with:  ollama serve"
    echo "    Then pull:   ollama pull qwen3.5:0.8b"
else
    warn "Ollama not found. Install from https://ollama.com"
fi

# Check LM Studio
if curl -sf "http://localhost:1234/v1/models" &>/dev/null; then
    ok "LM Studio is running at localhost:1234"
    BACKEND_OK=true
fi

if [ "$HARPER_OK" = true ]; then
    ok "Harper helper is ready"
    BACKEND_OK=true
fi

if [ "$BACKEND_OK" = false ]; then
    warn "No local backend detected. GramWrite needs Ollama, LM Studio, Apple Foundation Models, or Harper to function."
    echo ""
    echo "    Ollama (recommended, free):"
    echo "      https://ollama.com → install → ollama pull qwen3.5:0.8b"
    echo ""
    echo "    LM Studio:"
    echo "      https://lmstudio.ai → download qwen3.5 → start local server"
    echo ""
    echo "    Harper (English grammar checker):"
    echo "      Install Node.js, then run: npm install --prefix \"$HARPER_DIR\""
    if [ "$PLATFORM" = "macos" ]; then
        echo ""
        echo "    Apple Foundation Models:"
        echo "      Available on Apple Intelligence-enabled Macs from inside GramWrite."
    fi
fi

# ── macOS Accessibility ────────────────────────────────────────────────────────
if [ "$PLATFORM" = "macos" ]; then
    head "macOS Accessibility Permissions"
    echo ""
    echo "    GramWrite needs Accessibility access to read text from Fade In,"
    echo "    Final Draft, and Highland."
    echo ""
    echo "    Go to:  System Settings → Privacy & Security → Accessibility"
    echo "    Add Terminal (or your Python interpreter) to the allowed list."
    echo ""
fi

# ── Create launch script ──────────────────────────────────────────────────────
head "Creating launch script…"

cat > "$GRAMWRITE_DIR/gramwrite.sh" << 'EOF'
#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/.venv/bin/activate"
exec python -m gramwrite "$@"
EOF
chmod +x "$GRAMWRITE_DIR/gramwrite.sh"
ok "Created gramwrite.sh"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}Installation complete.${RESET}"
echo ""
echo "  Start GramWrite:  ./gramwrite.sh"
echo "  With settings:    ./gramwrite.sh --dashboard"
echo "  Debug mode:       ./gramwrite.sh --verbose"
echo ""
echo -e "${DIM}  Write first. Polish never. GramWrite exists in the background.${RESET}"
echo ""
