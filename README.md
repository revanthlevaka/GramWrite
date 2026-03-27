# GramWrite

**The Invisible Editor for Screenwriters**

> *Write first. Polish never. GramWrite exists in the background.*

GramWrite is a local-first, OS-level AI sidecar that sits quietly beside your screenwriting software and offers grammar suggestions — only when you want them. No interruptions. No cloud. No rewriting your voice.

---

## Philosophy

Professional screenwriters don't write like textbook authors. Fragments are intentional. ALL CAPS are sacred. Pacing is everything.

GramWrite understands this. It knows the difference between a dialogue block and a slugline. It will never touch `EXT. MOJAVE DESERT - NIGHT`. It will never question `He runs.` as a sentence fragment. It waits in the corner — a small glowing dot — until you click it.

That's the whole experience.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     GramWrite v1.0                       │
│                                                          │
│  ┌─────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │ watcher │───▶│fountain_     │───▶│   engine.py    │  │
│  │ .py     │    │parser.py     │    │                │  │
│  │         │    │              │    │  Ollama /       │  │
│  │ OS      │    │  classify    │    │  LM Studio      │  │
│  │ Accessib│    │  dialogue?   │    │  (local only)  │  │
│  │ -ility  │    │  action?     │    │                │  │
│  │ API     │    │  slugline?   │    │  qwen3.5:0.8b  │  │
│  └─────────┘    └──────────────┘    └────────────────┘  │
│       │                │                    │            │
│       └────────────────┴────────────────────┘            │
│                        │                                 │
│                ┌───────▼──────┐                          │
│                │controller.py │                          │
│                │              │                          │
│                │ debounce     │                          │
│                │ dedup        │                          │
│                │ async queue  │                          │
│                └───────┬──────┘                          │
│                        │                                 │
│                ┌───────▼──────┐                          │
│                │   app.py     │                          │
│                │              │                          │
│                │  FloatingDot │                          │
│                │  SuggBubble  │                          │
│                │  PyQt6       │                          │
│                └──────────────┘                          │
└──────────────────────────────────────────────────────────┘

Text flow:  Active window → Extract → Parse → Infer → Display
```

---

## Requirements

- Python 3.10+
- One of:
  - [Ollama](https://ollama.com) with `qwen2.5:0.5b` (recommended)
  - [LM Studio](https://lmstudio.ai) with any small model loaded
- macOS 12+ / Windows 10+ / Ubuntu 20.04+

---

## Installation

### macOS / Linux

```bash
git clone https://github.com/yourorg/gramwrite
cd gramwrite
chmod +x install.sh
./install.sh
```

### Windows

```powershell
git clone https://github.com/yourorg/gramwrite
cd gramwrite
powershell -ExecutionPolicy Bypass -File install.ps1
```

### Manual install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

# macOS accessibility
pip install pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices

# Windows
pip install uiautomation psutil

# Linux
pip install pyatspi
```

---

## Starting GramWrite

```bash
# Standard
./gramwrite.sh               # macOS/Linux
.\gramwrite.bat              # Windows

# With settings panel open
./gramwrite.sh --dashboard

# Debug output
./gramwrite.sh --verbose

# Custom config
./gramwrite.sh --config /path/to/myconfig.yaml
```

---

## Usage

1. **Start your LLM backend**
   ```bash
   ollama serve
   # and ensure your model is pulled:
   ollama pull qwen2.5:0.5b
   ```

2. **Launch GramWrite**
   ```bash
   ./gramwrite.sh
   ```

3. **Write normally** in Fade In, Final Draft, or Highland

4. **GramWrite watches silently** — the dot stays grey while you type

5. **After 2 seconds of inactivity**, GramWrite analyses the current paragraph

6. **If there's a correction**, the dot glows green

7. **Click the dot** to see the suggestion bubble

8. **Copy with one click** — or dismiss

---

## Supported Apps

| App | macOS | Windows | Linux |
|-----|-------|---------|-------|
| Fade In | ✓ | ✓ | ✓ |
| Final Draft | ✓ | ✓ | — |
| Highland 2 | ✓ | — | — |
| Fountain editors | ✓ | ✓ | ✓ |
| Obsidian (Fountain plugin) | ✓ | ✓ | ✓ |

---

## Fountain Grammar Rules

GramWrite respects screenplay syntax:

| Element | Checked? | Why |
|---------|----------|-----|
| `INT. OFFICE - DAY` | No | Slugline — never touch |
| `EXT. DESERT - NIGHT` | No | Slugline — never touch |
| `JOHN` | No | Character name |
| `CUT TO:` | No | Transition |
| `(quietly)` | No | Parenthetical |
| `He runs.` | Light | Action — fragments allowed |
| `Where did you go?` | Yes | Dialogue — full check |
| `I don't know what you want from I.` | Yes | Dialogue — grammar error |

---

## Configuration

Edit `config.yaml`:

```yaml
backend: auto          # auto | ollama | lmstudio
model: qwen3.5:0.8b    # any model in your backend
sensitivity: medium    # low | medium | high
debounce_seconds: 2.0  # seconds of inactivity before check
max_context_chars: 300 # characters extracted per check
system_prompt: |
  You are a Hollywood script doctor.
  # ... (fully editable)
```

---

## Privacy Pledge

**GramWrite never sends your text to the internet.**

- All inference runs locally via Ollama or LM Studio
- No telemetry, analytics, or crash reporting
- No user accounts or authentication
- No network calls except to `localhost`
- Your screenplay stays on your machine

This is a commitment, not just a feature. The source is open and auditable.

---

## Performance

| Model | Size | Avg latency | RAM |
|-------|------|-------------|-----|
| qwen3.5:0.8b | 400MB | ~50–80ms | ~600MB |
| qwen3.5:1.5b | 1GB | ~100–150ms | ~1.2GB |
| llama3.2:1b | 1.2GB | ~80–120ms | ~1.5GB |

GramWrite only processes short text segments (~300 chars), keeping inference fast even on modest hardware.

---

## Development

```bash
# Clone and install in dev mode
git clone https://github.com/yourorg/gramwrite
cd gramwrite
python -m venv .venv && source .venv/bin/activate
pip install -e ".[macos]"  # or [windows] or [linux]

# Run tests
python -m pytest tests/ -v

# Run directly
python -m gramwrite --verbose
```

### Project Structure

```
gramwrite/
├── gramwrite/
│   ├── __init__.py
│   ├── __main__.py      ← Entry point
│   ├── engine.py        ← LLM backend connector
│   ├── watcher.py       ← OS text extraction
│   ├── fountain_parser.py ← Screenplay syntax parser
│   ├── controller.py    ← Async pipeline orchestrator
│   ├── app.py           ← Floating UI (PyQt6)
│   └── dashboard.py     ← Settings panel
├── config.yaml          ← User configuration
├── requirements.txt
├── setup.py
├── install.sh           ← macOS/Linux installer
├── install.ps1          ← Windows installer
├── index.html           ← Landing page
└── README.md
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-idea`
3. Keep changes minimal and focused
4. Test on your target platform
5. Open a pull request with a clear description

**What we want:**
- Better OS text extraction reliability
- More screenplay app support
- Performance improvements
- Bug fixes

**What we don't want:**
- Cloud features
- User accounts
- Rewriting AI (beyond grammar)
- Complex UI additions

---

## License

MIT — see [LICENSE](LICENSE)

---

*Built for writers who trust their instincts.*
