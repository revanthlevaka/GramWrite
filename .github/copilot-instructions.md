# 🧠 GramWrite — Copilot Engineering Doctrine

## 🎯 Project Context

GramWrite is a **local-first, OS-level AI sidecar** for screenwriters.

It runs alongside tools like Fade In and provides **grammar corrections only when explicitly requested**, without interrupting writing flow.

This is NOT a writing assistant.  
This is NOT an AI co-writer.  

This is:
> An invisible, screenplay-aware grammar layer.

---

## 🧬 Core Philosophy

- Invisible by default
- Zero distraction
- Local-first (no network calls)
- Screenplay-aware (Fountain syntax)
- Never rewrite — only correct real mistakes

---

## ⚠️ Critical Constraints

Copilot MUST follow these strictly:

### ❌ NEVER:
- Rewrite text stylistically
- Add new words or sentences
- Modify tone, pacing, or intent
- Touch screenplay structure:
  - Sluglines (INT./EXT.)
  - Character names (ALL CAPS)
  - Transitions (CUT TO:, FADE IN:)
  - Parentheticals

### ✅ ONLY:
- Fix grammar mistakes
- Fix spelling errors
- Improve punctuation where clearly incorrect
- Preserve original voice and structure

---

## 🧱 Architecture Overview

```
Watcher → Fountain Parser → Heuristics → Engine → UI
```

### Modules:

- `watcher.py` → Extracts text context
- `fountain_parser.py` → Classifies screenplay elements
- `heuristics.py` → Pre-LLM rule filtering
- `engine.py` → Routes to grammar backends
- `app.py` → UI layer
- `controller.py` → Orchestration

---

## 🧠 Fountain Parsing Rules (Non-Negotiable)

Copilot must respect:

### Ignore completely:
- Lines starting with `INT.`, `EXT.`, `EST.`
- ALL CAPS lines (character names)
- Transition lines (`CUT TO:` etc.)

### Action lines:
- Allow fragments
- Allow stylistic grammar
- Only fix obvious mistakes

### Dialogue:
- Primary target for grammar correction
- Maintain character voice

---

## 🔍 Parser Enhancements (v1.2.2)

Copilot must support:

- Dual Dialogue (`^text`)
- Forced Action (`!text`)
- Emphasis spans (`*text*`, `_text_`)
- Line breaks (`<br>`, `<br/>`, whitespace)
- Character names with commas

Use structured output:

```python
ParsedBlock(
    type="dialogue" | "action" | "slugline",
    text=str,
    should_check=bool,
    is_dual_dialogue=bool,
    is_forced_action=bool,
    emphasis_spans=list,
    has_line_breaks=bool
)
```

---

## ⚙️ Heuristics Layer (Before LLM)

Copilot should ALWAYS prefer deterministic fixes before LLM:

Examples:

* "dont" → "don't"
* "your" vs "you're"
* Past → present tense (action lines only)

LLM should only be used when:

* Rule-based fix is insufficient
* Context is required

---

## 🤖 Engine Behavior

Supported backends:

* Ollama
* LM Studio
* Harper
* Apple Foundation Models

Copilot must:

* Keep backend abstraction clean
* Avoid backend-specific logic leakage
* Ensure <100ms response target

---

## 🖥 UI Constraints

* Floating minimal UI
* No blocking interactions
* No typing interruptions

States:

* Idle
* Processing
* Suggestion ready

---

## 🚀 Performance Requirements

* App startup < 2 seconds
* Inference < 100ms
* Minimal CPU usage
* No memory leaks

---

## 🔒 Privacy Requirements

* NO external API calls
* NO telemetry
* NO data storage outside local machine

---

## 🧪 Testing Rules

Copilot should generate tests for:

### Case 1:

```
JOHN
i dont know what your talking about
```

Expected:
→ Fix grammar in dialogue only

### Case 2:

```
INT. HOUSE - DAY
```

Expected:
→ No changes

### Case 3:

```
The door slam open.
```

Expected:
→ Minimal correction, preserve style

---

## 🧠 Coding Style

* Use clear, readable Python
* Prefer explicit over clever
* Avoid over-engineering
* Keep functions small and focused
* Use type hints

---

## ⚡ Final Directive

Copilot is NOT building features.

Copilot is enforcing:

* precision
* restraint
* correctness

Every suggestion must answer:

> "Is this a real mistake, or intentional screenplay style?"

If uncertain → DO NOTHING.
