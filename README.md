# GramWrite

## The Invisible Editor for Screenwriters

> **Write first. Stay in flow. GramWrite waits.**

GramWrite is a **local-first, OS-level AI sidecar** that lives quietly beside your screenwriting software.
It offers grammar suggestions **only when you ask for them**.

No interruptions.
No cloud.
No rewriting your voice.

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

* Runs entirely on **Ollama or LM Studio**
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
engine.py          → Local LLM inference  
controller.py      → Async orchestration (debounce, queue)  
app.py             → Floating UI (PyQt6)  
```

### Pipeline

* **Watcher** captures active window text
* **Parser** identifies screenplay elements
* **Engine** runs local inference
* **Controller** ensures smooth async flow
* **UI** displays minimal suggestions

---

## Requirements

* Python 3.10+
* One of:

  * Ollama (**Qwen3.5:0.8B recommended**)
  * LM Studio (any small local model)
* macOS 12+ / Windows 10+ / Ubuntu 20.04+

---

## Installation

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

---

## Usage

### 1. Start your LLM backend

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

Edit `config.yaml`:

```yaml
backend: auto
model: qwen3.5:0.8b
sensitivity: medium
debounce_seconds: 2.0
max_context_chars: 300
```

You can also customize the system prompt.

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
