"""
fountain_parser.py — Fountain Screenplay Syntax Parser
Classifies text blocks and determines whether grammar checking applies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FountainElement(Enum):
    SLUGLINE = "slugline"
    ACTION = "action"
    CHARACTER = "character"
    DIALOGUE = "dialogue"
    PARENTHETICAL = "parenthetical"
    TRANSITION = "transition"
    CENTERED = "centered"
    NOTE = "note"
    UNKNOWN = "unknown"


@dataclass
class ParsedBlock:
    element: FountainElement
    text: str
    should_check: bool
    reason: str  # Why we are / aren't checking this block
    is_dual_dialogue: bool = False
    is_forced_action: bool = False
    emphasis_spans: list[tuple[int, int]] | None = None
    has_line_breaks: bool = False

    def to_dict(self) -> dict:
        return {
            "type": self.element.value,
            "text": self.text,
            "should_check": self.should_check,
            "reason": self.reason,
            "is_dual_dialogue": self.is_dual_dialogue,
            "is_forced_action": self.is_forced_action,
            "emphasis_spans": self.emphasis_spans,
            "has_line_breaks": self.has_line_breaks,
        }


# ─── Compiled regex patterns ──────────────────────────────────────────────────

# INT./EXT./EST. sluglines, with optional .NIGHT / .DAY / dash variants
_RE_SLUGLINE = re.compile(
    r"^(INT|EXT|EST|INT/EXT|EXT/INT|I/E)[.\s]",
    re.IGNORECASE,
)

# Fountain forced slugline (leading dot)
_RE_FORCED_SLUGLINE = re.compile(r"^\.")

# ALL CAPS line — character name (may have extension in parens: JOHN (V.O.))
# Allow commas in names (e.g. "JOHN CARTER, JR.") and periods / apostrophes.
_RE_CHARACTER = re.compile(r"^[A-Z][A-Z\s\-\'\.,]+(\s*\(.*\))?\s*$")

# Parenthetical: (beat), (quietly), etc.
_RE_PARENTHETICAL = re.compile(r"^\(.*\)\s*$")

# Common transitions
_RE_TRANSITION = re.compile(
    r"^(FADE\s+(IN|OUT|TO)|CUT\s+TO|SMASH\s+CUT|MATCH\s+CUT|DISSOLVE\s+TO|"
    r"IRIS\s+(IN|OUT)|WIPE\s+TO|INTERCUT\s+WITH|TITLE\s+CARD|THE\s+END)[:\s]*$",
    re.IGNORECASE,
)

# Fountain forced transition (trailing >)
_RE_FORCED_TRANSITION = re.compile(r"^>.*[^<]$")

# Centered text: > TEXT <
_RE_CENTERED = re.compile(r"^>\s*.*\s*<$")

# Fountain note: [[ ... ]]
_RE_NOTE = re.compile(r"^\[\[.*\]\]$")

# Section / synopsis markers
_RE_SECTION = re.compile(r"^#{1,6}\s")
_RE_SYNOPSIS = re.compile(r"^=\s")

# Mostly uppercase — heuristic threshold for "action-like" ALL CAPS
_CAPS_RATIO_THRESHOLD = 0.7

# Dual dialogue: ^ prefix (Fountain syntax for simultaneous dialogue)
_RE_DUAL_DIALOGUE = re.compile(r"^\^")

# Forced action: ! prefix to force action line classification
_RE_FORCED_ACTION = re.compile(r"^!")

# Emphasis: *text* or _text_ patterns
_RE_EMPHASIS = re.compile(r"(\*[^*]+\*|_[^_]+_)")

# Line breaks: <br>, <br/>, <br /> or double space at end of line
_RE_LINE_BREAK = re.compile(r"(<br\s*/?>|\s{2,})")


class FountainParser:
    """
    Stateful Fountain parser.

    Tracks context across lines so dialogue blocks are correctly
    identified even without full document parsing.
    """

    def __init__(self):
        self._last_element: FountainElement = FountainElement.UNKNOWN
        self._in_dialogue_block: bool = False

    def classify(self, text: str) -> ParsedBlock:
        """
        Classify a block of text (single paragraph / extracted segment).
        Returns ParsedBlock with element type and check flag.
        """
        stripped = text.strip()

        if not stripped:
            return ParsedBlock(
                element=FountainElement.UNKNOWN,
                text=stripped,
                should_check=False,
                reason="Empty text",
            )

        # ── Detect emphasis spans early (preserve in result) ──────────────────
        emphasis_spans = self._detect_emphasis(stripped)

        # ── Detect line breaks ────────────────────────────────────────────────
        has_line_breaks = bool(_RE_LINE_BREAK.search(stripped))

        # ── Notes ─────────────────────────────────────────────────────────────
        if _RE_NOTE.match(stripped):
            return self._no_check(FountainElement.NOTE, stripped, "Fountain note block",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Sections / Synopsis ───────────────────────────────────────────────
        if _RE_SECTION.match(stripped) or _RE_SYNOPSIS.match(stripped):
            return self._no_check(FountainElement.UNKNOWN, stripped, "Fountain structure marker",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Centered ──────────────────────────────────────────────────────────
        if _RE_CENTERED.match(stripped):
            return self._no_check(FountainElement.CENTERED, stripped, "Centered text",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Sluglines ─────────────────────────────────────────────────────────
        if _RE_SLUGLINE.match(stripped) or _RE_FORCED_SLUGLINE.match(stripped):
            self._in_dialogue_block = False
            self._last_element = FountainElement.SLUGLINE
            return self._no_check(FountainElement.SLUGLINE, stripped, "Scene heading / slugline",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Transitions ───────────────────────────────────────────────────────
        if _RE_TRANSITION.match(stripped) or _RE_FORCED_TRANSITION.match(stripped):
            self._in_dialogue_block = False
            self._last_element = FountainElement.TRANSITION
            return self._no_check(FountainElement.TRANSITION, stripped, "Transition directive",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Parenthetical ─────────────────────────────────────────────────────
        if _RE_PARENTHETICAL.match(stripped):
            return self._no_check(
                FountainElement.PARENTHETICAL, stripped, "Parenthetical / wryly",
                emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks
            )

        # ── Character name ────────────────────────────────────────────────────
        if _RE_CHARACTER.match(stripped) and len(stripped.split()) <= 6:
            self._in_dialogue_block = True
            self._last_element = FountainElement.CHARACTER
            return self._no_check(FountainElement.CHARACTER, stripped, "Character name",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Dual Dialogue ─────────────────────────────────────────────────────
        if _RE_DUAL_DIALOGUE.match(stripped):
            self._in_dialogue_block = True
            self._last_element = FountainElement.DIALOGUE
            clean_text = stripped[1:].strip()  # Remove ^ prefix
            return ParsedBlock(
                element=FountainElement.DIALOGUE,
                text=clean_text,
                should_check=True,
                reason="Dual dialogue block — grammar check applies",
                is_dual_dialogue=True,
                emphasis_spans=emphasis_spans,
                has_line_breaks=has_line_breaks,
            )

        # ── Forced Action ─────────────────────────────────────────────────────
        if _RE_FORCED_ACTION.match(stripped):
            self._in_dialogue_block = False
            self._last_element = FountainElement.ACTION
            clean_text = stripped[1:].strip()  # Remove ! prefix
            return ParsedBlock(
                element=FountainElement.ACTION,
                text=clean_text,
                should_check=True,
                reason="Forced action line — grammar check applies",
                is_forced_action=True,
                emphasis_spans=emphasis_spans,
                has_line_breaks=has_line_breaks,
            )

        # ── Dialogue ──────────────────────────────────────────────────────────
        if self._in_dialogue_block:
            self._last_element = FountainElement.DIALOGUE
            return ParsedBlock(
                element=FountainElement.DIALOGUE,
                text=stripped,
                should_check=True,
                reason="Dialogue block — grammar check applies",
                emphasis_spans=emphasis_spans,
                has_line_breaks=has_line_breaks,
            )

        # ── Action lines ─────────────────────────────────────────────────────
        # After a slugline or transition, next non-character text is action.
        # Allow stylistic fragments; still check for obvious errors.
        self._in_dialogue_block = False
        self._last_element = FountainElement.ACTION

        # Skip all-caps action lines (emphasis / sound effects)
        if self._is_mostly_caps(stripped):
            return self._no_check(
                FountainElement.ACTION, stripped, "All-caps action / sound effect",
                emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks
            )

        return ParsedBlock(
            element=FountainElement.ACTION,
            text=stripped,
            should_check=True,
            reason="Action line — light grammar check (preserve fragments)",
            emphasis_spans=emphasis_spans,
            has_line_breaks=has_line_breaks,
        )

    def classify_raw_extract(self, raw: str) -> ParsedBlock:
        """
        Classify raw text extracted from an OS accessibility API.
        Handles multi-line extracts by finding the most relevant segment.
        """
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if not lines:
            return ParsedBlock(
                element=FountainElement.UNKNOWN,
                text="",
                should_check=False,
                reason="Empty extract",
            )

        # Walk lines to build context; return classification of last line
        result: Optional[ParsedBlock] = None
        for line in lines:
            result = self.classify(line)

        return result  # type: ignore[return-value]

    def reset_context(self):
        """Reset state machine — call when window/document changes."""
        self._last_element = FountainElement.UNKNOWN
        self._in_dialogue_block = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _no_check(
        element: FountainElement, text: str, reason: str,
        emphasis_spans: list[tuple[int, int]] | None = None,
        has_line_breaks: bool = False,
    ) -> ParsedBlock:
        return ParsedBlock(
            element=element,
            text=text,
            should_check=False,
            reason=reason,
            emphasis_spans=emphasis_spans,
            has_line_breaks=has_line_breaks,
        )

    @staticmethod
    def _is_mostly_caps(text: str) -> bool:
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False
        caps = sum(1 for c in letters if c.isupper())
        return (caps / len(letters)) >= _CAPS_RATIO_THRESHOLD

    @staticmethod
    def _detect_emphasis(text: str) -> list[tuple[int, int]]:
        """
        Detect emphasis spans (*text* or _text_) and return their positions.
        Returns a list of (start, end) tuples for each emphasis span found.
        """
        spans: list[tuple[int, int]] = []
        for match in _RE_EMPHASIS.finditer(text):
            spans.append((match.start(), match.end()))
        return spans

    @property
    def in_dialogue(self) -> bool:
        return self._in_dialogue_block


# ─── Convenience function ─────────────────────────────────────────────────────


def parse_extracted_text(text: str) -> ParsedBlock:
    """
    Stateless convenience wrapper. Creates a fresh parser instance.
    Use FountainParser() directly for stateful/multi-line processing.
    """
    parser = FountainParser()
    return parser.classify_raw_extract(text)
