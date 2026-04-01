# GramWrite

## The Invisible Editor for Screenwriters

> **Write first. Stay in flow. GramWrite waits.**

GramWrite is a **local-first, OS-level AI sidecar** that lives quietly beside your screenwriting software.
It offers grammar suggestions **only when you ask for them**.

No interruptions.
No cloud.
No rewriting your voice.

---

## What's New in v1.2.2
- **Inline Word-Level Diffs**: Suggestions now highlight exactly which words changed using color-coded text.
- **Confidence Indicators**: Every suggestion includes a built-in confidence score (HIGH/MEDIUM/LOW) visually mapped to a color indicator near the header.
- **Strict Screenplay Mode**: Configurable strict mode guarantees elements like character names, parentheticals, and sluglines are 100% ignored.
- **Present Tense Enforcement**: GramWrite heuristically detects past tense action lines and attempts to convert them to present tense.
- **Multilingual Support**: The underlying LLM is now instructed to detect the original language and correct it directly without translating.
- **Apple Foundation Models Toggle**: macOS users can now choose Apple's on-device Foundation Models backend instead of Ollama or LM Studio when their Mac supports Apple Intelligence.
- **Harper Backend Option**: Harper is now available as an optional fast local English grammar backend alongside Ollama, LM Studio, and Apple Foundation Models.
- **DMG Packaging Workflow**: macOS builds can now be wrapped as a drag-and-drop `.dmg` for non-technical installs.

---

## Why GramWrite Exists

Most writing tools are built for essays.

Screenwriting is different.

* Fragments are intentional
* ALL CAPS are sacred
* Pacing is everything

Traditional grammar tools don’t understand this.
They interrupt. They over-correct. They break flow.

> **GramWrite does the opposite.**

It understands screenplay structure and **respects your voice**.

---

## Core Principles

### 1. Invisible by Default

GramWrite never interrupts your writing.

* A small floating dot sits quietly
* It activates only after you pause
* You choose when to engage

> No popups. No distractions. No broken flow.

---

### 2. Screenplay-Aware Intelligence

GramWrite understands **Fountain syntax and screenplay structure**.

It will never touch:

* `INT. OFFICE - DAY` (Sluglines)
* `JOHN` (Character names)
* `CUT TO:` (Transitions)
* `(quietly)` (Parentheticals)

It only checks what matters:

* Dialogue
* Real grammar errors

---

### 3. Local-First. Private by Design

Your script stays yours.

* Runs entirely on **Ollama, LM Studio, Harper, or Apple Foundation Models on supported Macs**
* No telemetry
* No accounts
* No internet calls

> **No data leaves your machine. Ever.**

---

### 4. Respect the Writer

GramWrite does not try to be creative.

* No rewriting
* No “better phrasing” suggestions
* No style changes

> It fixes mistakes. That’s it.

---
## Supported Fountain Syntax

GramWrite's built-in parser understands standard Fountain screenplay syntax. It correctly identifies and classifies screenplay elements so grammar checking is applied only where appropriate.

| Syntax | Example | Behavior |
|--------|---------|----------|
| **Sluglines** | `INT. OFFICE - DAY` | Detected via `INT.`, `EXT.`, `EST.`, `I/E` prefixes. Never checked. |
| **Character Names** | `JOHN CARTER, JR.` | ALL CAPS with optional comma suffixes. Never checked. |
| **Dialogue** | `I need to tell you something.` | Tracked across multiple lines. Grammar checked by default. |
| **Parentheticals** | `(quietly)` | Wrapped in parentheses below character names. Never checked. |
| **Transitions** | `CUT TO:` | ALL CAPS ending with colon. Never checked. |
| **Dual Dialogue** | `^JOHN` | Prefixed with `^` for simultaneous dialogue. Never checked. |
| **Forced Action** | `!This is action.` | Prefixed with `!` to force action line parsing. Checked if strict mode allows. |
| **Emphasis** | `*bold*` or `_italic_` | Preserved as spans during parsing. Checked within dialogue. |
| **Line Breaks** | `  ` (double-space) or `<br>` | Preserved in output. |
| **Notes** | `[[TODO: fix this scene]]` | Bracketed notes. Never checked. |
| **Section Markers** | `# Act One` | `#`-prefixed section headers. Never checked. |

### Strict Screenplay Mode

When enabled, GramWrite guarantees that structural elements (sluglines, character names, parentheticals, transitions) are **100% ignored** — only dialogue and action lines receive suggestions.

---
## How It Works

```id="flow"
Active Window → Extract → Parse → Infer → Display
```

1. You write in your preferred screenwriting app
2. GramWrite watches silently
3. After a short pause, it analyzes the current block
4. If a correction exists → the dot glows
5. Click to view suggestion
6. Copy or dismiss

That’s the entire interaction.

---

## Architecture Overview

```id="arch"
watcher.py         → OS-level text extraction  
fountain_parser.py → Screenplay-aware classification  
engine.py          → Local grammar backend inference  
controller.py      → Async orchestration (debounce, queue)  
app.py             → Floating UI (PyQt6)  
```

### Pipeline

* **Watcher** captures active window text
* **Parser** identifies screenplay elements
* **Engine** runs the selected local grammar backend
* **Controller** ensures smooth async flow
* **UI** displays minimal suggestions

---

## Requirements

- Python 3.10+
- One of:
  - [Ollama](https://ollama.com) with `qwen3.5:0.8b` (recommended)
  - [LM Studio](https://lmstudio.ai) with any small model loaded
  - [Harper](https://github.com/Automattic/harper) via the bundled `harper.js` helper and Node.js
  - Apple Foundation Models on an Apple Intelligence-enabled Mac
- macOS 12+ / Windows 10+ / Ubuntu 20.04+

---

## Installation

### macOS Drag-and-Drop

For filmmaker-friendly installs, ship the packaged app as a DMG:

```bash
./scripts/build_macos_dmg.sh
```

That creates `dist/GramWrite-1.2.2.dmg`, which opens as a standard drag-and-drop installer with `GramWrite.app` plus an `Applications` shortcut.

### macOS / Linux

```bash
git clone https://github.com/revanthlevaka/GramWrite
cd GramWrite
chmod +x install.sh
./install.sh
```

### Windows

```powershell
git clone https://github.com/revanthlevaka/GramWrite
cd GramWrite
powershell -ExecutionPolicy Bypass -File install.ps1
```

### Manual

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you want the Harper backend, also install the helper dependencies:

```bash
npm install --prefix gramwrite/native/harper
```

---

## Usage

1. **Start your preferred backend**
   ```bash
   ollama serve
   # and ensure your model is pulled:
   ollama pull qwen3.5:0.8b
   ```

   On supported Macs, you can skip Ollama and LM Studio entirely by selecting `foundation_models` in the dashboard. That backend uses Apple's on-device Foundation Models and does not need a local HTTP server.

   If you install the optional Harper helper, you can also select `harper` in the dashboard. Harper is English-only and does not require a local HTTP server.

2. **Launch GramWrite**
   ```bash
   ./gramwrite.sh
   ```

3. **Write normally** in Fade In, Final Draft, or Highland

4. **GramWrite watches silently** — the dot stays grey while you type

5. **After 2 seconds of inactivity**, GramWrite analyses the current paragraph

6. **If there's a correction**, the dot glows green

7. **Click the dot** to see the suggestion bubble

```bash
ollama serve
ollama pull qwen3.5:0.8b
```

### 2. Launch GramWrite

```bash
./gramwrite.sh
```

### 3. Write normally

Supported tools include:

* Fade In
* Final Draft
* Highland
* Fountain editors
* Obsidian (Fountain plugin)

### 4. Let it work

* Dot stays grey while typing
* After pause → analysis runs
* Dot turns green → suggestion available
* Click to view

---

## Configuration

### Accessing the Settings Dashboard

After installation, you can open the settings dashboard in three ways:

| Method | How |
|---|---|
| **Right-click the dot** | Right-click the floating GramWrite dot → **⚙ Settings** |
| **CLI flag** | `python -m gramwrite --dashboard` |
| **Localhost** | Open `http://localhost:7878` (default port, configurable via `--port`) |

### `config.yaml`

```yaml
backend: auto
model: qwen3.5:0.8b
sensitivity: medium
debounce_seconds: 2.0
max_context_chars: 300
dashboard_port: 7878
```

For Apple's on-device backend on macOS:

```yaml
backend: foundation_models
model: apple.foundation
```

For the Harper backend:

```yaml
backend: harper
model: harper.english
```

You can also customize the system prompt in the dashboard or directly in `config.yaml`.
Harper ignores the system prompt because it uses its own local grammar engine.

> **Tip:** All settings are saved to `config.yaml` automatically when you click **Save Settings** in the dashboard.

## macOS Packaging

Build a local `.app` bundle:

```bash
./scripts/build_macos_app.sh
```

Build a drag-and-drop `.dmg`:

```bash
./scripts/build_macos_dmg.sh
```

On macOS, those scripts build and sign a bundled Foundation Models helper app so the Apple backend can work inside the packaged GramWrite app without asking end users to install developer tools.
---

## Performance

Optimized for speed and low resource usage.

| Model        | Latency   | RAM        |
| ------------ | --------- | ---------- |
| qwen3.5:0.8b | ~40–70ms  | ~500–700MB |
| qwen3.5:1.5b | ~80–120ms | ~1.1GB     |

Small context windows (~300 chars) ensure fast response even on modest hardware.

---

## What GramWrite Is NOT

* Not a writing assistant
* Not a rewriting tool
* Not a cloud SaaS
* Not another Grammarly clone

> It is a **precision tool for professional writers**.

---

## Vision

> Writing is not autocomplete.
> Writing is instinct, rhythm, and intent.

GramWrite exists to protect that.

Future direction:

* Deeper screenplay awareness
* Better app integrations
* Performance optimization
* Integration with local memory systems

---

## Contributing

We welcome focused contributions.

## Credits

* Harper integration is powered by [Harper](https://github.com/Automattic/harper) from Automattic.
* The bundled Harper helper uses the `harper.js` package, which is licensed under Apache-2.0.

### What we want:

* Better OS-level extraction
* More app compatibility
* Performance improvements
* Bug fixes

### What we don’t want:

* Cloud features
* User accounts
* Rewriting AI
* UI bloat

---

## License

MIT

---

## Final Note

> Built for writers who trust their instincts.

If you’ve ever been interrupted mid-scene by a grammar tool that didn’t understand your work…

You already know why this exists.
