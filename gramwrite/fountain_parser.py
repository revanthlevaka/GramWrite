"""
fountain_parser.py — Fountain Screenplay Syntax Parser

Classifies text blocks according to Fountain syntax rules and determines
whether grammar checking should apply to each block.

Supports:
- Scene headings (sluglines): INT./EXT./EST.
- Character names (ALL CAPS, with extensions like (V.O.), (O.S.))
- Dialogue blocks (including dual dialogue with ^ prefix)
- Parentheticals: (beat), (whispering)
- Action lines (including forced action with ! prefix)
- Transitions: CUT TO:, FADE OUT:, etc.
- Emphasis spans: *text* and _text_
- Line breaks: <br>, <br/>, double spaces
- Fountain notes: [[ ... ]]
- Centered text: > text <

Usage:
    # Stateful parsing (recommended for multi-line context)
    parser = FountainParser()
    result = parser.classify("INT. HOUSE - DAY")
    
    # Stateless convenience function
    result = parse_extracted_text("He walked in.")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FountainElement(Enum):
    """Enumeration of Fountain screenplay element types."""
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
    """
    Represents a classified Fountain text block.
    
    Attributes:
        element: The type of Fountain element detected
        text: The cleaned text content (prefixes stripped if applicable)
        should_check: Whether grammar checking should apply to this block
        reason: Explanation of why checking is/isn't applied
        is_dual_dialogue: True if this is dual dialogue (^ prefix)
        is_forced_action: True if this is forced action (! prefix)
        emphasis_spans: List of (start, end) tuples for emphasis markers
        has_line_breaks: True if line breaks detected in text
    """
    element: FountainElement
    text: str
    should_check: bool
    reason: str
    is_dual_dialogue: bool = False
    is_forced_action: bool = False
    emphasis_spans: list[tuple[int, int]] = field(default_factory=list)
    has_line_breaks: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
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
# All patterns are pre-compiled for efficiency.

# Scene headings (sluglines): INT./EXT./EST./INT/EXT./EXT/INT./I/E.
# Matches standard Fountain slugline format with optional time of day.
_RE_SLUGLINE = re.compile(
    r"^(INT|EXT|EST|INT/EXT|EXT/INT|I/E)[.\s]",
    re.IGNORECASE,
)

# Forced slugline: leading dot (.) forces scene heading classification
_RE_FORCED_SLUGLINE = re.compile(r"^\.")

# Character names: ALL CAPS lines, optionally with parenthetical extensions
# Handles: "JOHN", "MARY JANE", "JOHN CARTER, JR.", "O'NEIL (V.O.)", "POLICE OFFICER (O.S.)"
# Allows commas, periods, apostrophes, and hyphens in names
_RE_CHARACTER = re.compile(
    r"^[A-Z][A-Z\s\-\'\.,]+(\s*\(.*\))?\s*$"
)

# Parenthetical: text enclosed in parentheses, typically stage directions
# Matches: "(beat)", "(whispering)", "(sighs)"
_RE_PARENTHETICAL = re.compile(r"^\(.*\)\s*$")

# Transitions: standard screenplay transitions
# Matches: "CUT TO:", "FADE OUT.", "SMASH CUT TO:", "DISSOLVE TO:", etc.
# Allows trailing colon, period, or whitespace
_RE_TRANSITION = re.compile(
    r"^(FADE\s+(IN|OUT|TO)|CUT\s+TO|SMASH\s+CUT\s+TO|MATCH\s+CUT\s+TO|DISSOLVE\s+TO|"
    r"IRIS\s+(IN|OUT)|WIPE\s+TO|INTERCUT\s+WITH|TITLE\s+CARD|THE\s+END)[:.\s]*$",
    re.IGNORECASE,
)

# Forced transition: trailing > forces transition classification
_RE_FORCED_TRANSITION = re.compile(r"^>.*[^<]$")

# Centered text: enclosed in > and < markers
_RE_CENTERED = re.compile(r"^>\s*.*\s*<$")

# Fountain note: enclosed in [[ ]]
_RE_NOTE = re.compile(r"^\[\[.*\]\]$")

# Section markers: # through ######
_RE_SECTION = re.compile(r"^#{1,6}\s")

# Synopsis marker: = prefix
_RE_SYNOPSIS = re.compile(r"^=\s")

# Threshold for detecting ALL CAPS lines (70% uppercase letters)
_CAPS_RATIO_THRESHOLD = 0.7

# Dual dialogue: ^ prefix indicates simultaneous dialogue (Fountain syntax)
_RE_DUAL_DIALOGUE = re.compile(r"^\^")

# Forced action: ! prefix forces action line classification
_RE_FORCED_ACTION = re.compile(r"^!")

# Emphasis patterns: *text* or _text_ (italic/bold markers)
# Matches non-greedy content between matching delimiters
_RE_EMPHASIS = re.compile(r"(\*[^*]+\*|_[^_]+_)")

# Line breaks: HTML-style (<br>, <br/>, <br />) or double-space at end
_RE_LINE_BREAK = re.compile(r"(<br\s*/?>|\s{2,})")


class FountainParser:
    """
    Stateful Fountain screenplay syntax parser.
    
    Tracks context across lines to correctly identify dialogue blocks,
    character names, and other screenplay elements. Maintains state
    between classify() calls to handle multi-line screenplay structures.
    
    Grammar checking rules:
    - Dialogue lines: ALWAYS checked (primary target)
    - Action lines: Checked lightly (preserve stylistic fragments)
    - Sluglines, transitions, character names, parentheticals: NEVER checked
    - Dual dialogue: Treated as dialogue (checked)
    - Forced action: Treated as action (checked)
    
    Example:
        parser = FountainParser()
        
        # Parse screenplay line by line
        result = parser.classify("INT. HOUSE - DAY")
        assert result.element == FountainElement.SLUGLINE
        assert result.should_check is False
        
        result = parser.classify("JOHN")
        assert result.element == FountainElement.CHARACTER
        
        result = parser.classify("I don't know what you're talking about.")
        assert result.element == FountainElement.DIALOGUE
        assert result.should_check is True
    """

    def __init__(self):
        """Initialize parser with clean state."""
        self._last_element: FountainElement = FountainElement.UNKNOWN
        self._in_dialogue_block: bool = False

    def classify(self, text: str) -> ParsedBlock:
        """
        Classify a single block of Fountain screenplay text.
        
        Analyzes the text against Fountain syntax rules and returns
        a ParsedBlock with element type, grammar check flag, and
        metadata about emphasis spans and line breaks.
        
        Args:
            text: A single line or paragraph of screenplay text
            
        Returns:
            ParsedBlock with classification results and metadata
            
        Note:
            This method maintains state between calls. For stateless
            parsing, use parse_extracted_text() instead.
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
        # Character names are ALL CAPS, typically short (<= 40 chars),
        # and have <= 6 words. This prevents matching long ALL CAPS action lines.
        if (_RE_CHARACTER.match(stripped) 
            and len(stripped.split()) <= 6 
            and len(stripped) <= 40):
            self._in_dialogue_block = True
            self._last_element = FountainElement.CHARACTER
            return self._no_check(FountainElement.CHARACTER, stripped, "Character name",
                                  emphasis_spans=emphasis_spans, has_line_breaks=has_line_breaks)

        # ── Dual Dialogue ─────────────────────────────────────────────────────
        if _RE_DUAL_DIALOGUE.match(stripped):
            self._in_dialogue_block = True
            self._last_element = FountainElement.DIALOGUE
            clean_text = stripped[1:].strip()  # Remove ^ prefix
            # Re-detect emphasis on cleaned text for accurate positions
            clean_emphasis = self._detect_emphasis(clean_text)
            return ParsedBlock(
                element=FountainElement.DIALOGUE,
                text=clean_text,
                should_check=True,
                reason="Dual dialogue block — grammar check applies",
                is_dual_dialogue=True,
                emphasis_spans=clean_emphasis,
                has_line_breaks=has_line_breaks,
            )

        # ── Forced Action ─────────────────────────────────────────────────────
        if _RE_FORCED_ACTION.match(stripped):
            self._in_dialogue_block = False
            self._last_element = FountainElement.ACTION
            clean_text = stripped[1:].strip()  # Remove ! prefix
            # Re-detect emphasis on cleaned text for accurate positions
            clean_emphasis = self._detect_emphasis(clean_text)
            return ParsedBlock(
                element=FountainElement.ACTION,
                text=clean_text,
                should_check=True,
                reason="Forced action line — grammar check applies",
                is_forced_action=True,
                emphasis_spans=clean_emphasis,
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

        # Skip all-caps action lines (emphasis / sound effects) ONLY if short.
        # Long ALL CAPS lines are likely stylistic action, not sound effects.
        if self._is_mostly_caps(stripped) and len(stripped) <= 50:
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
        
        Handles multi-line extracts by processing each line sequentially
        and returning the classification of the last meaningful line.
        This maintains proper context building across lines.
        
        Args:
            raw: Multi-line text extract from screen reader or accessibility API
            
        Returns:
            ParsedBlock classification of the last non-empty line
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
        """
        Reset parser state machine.
        
        Call this when switching to a different window, document,
        or screenplay context to avoid stale state affecting classification.
        """
        self._last_element = FountainElement.UNKNOWN
        self._in_dialogue_block = False

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _no_check(
        element: FountainElement, text: str, reason: str,
        emphasis_spans: list[tuple[int, int]] | None = None,
        has_line_breaks: bool = False,
    ) -> ParsedBlock:
        """
        Create a ParsedBlock that should NOT be grammar checked.
        
        Used for screenplay structural elements like sluglines,
        character names, transitions, and parentheticals.
        
        Args:
            element: The Fountain element type
            text: The text content
            reason: Explanation for why checking is disabled
            emphasis_spans: Detected emphasis span positions
            has_line_breaks: Whether line breaks were detected
            
        Returns:
            ParsedBlock with should_check=False
        """
        return ParsedBlock(
            element=element,
            text=text,
            should_check=False,
            reason=reason,
            emphasis_spans=emphasis_spans or [],
            has_line_breaks=has_line_breaks,
        )

    @staticmethod
    def _is_mostly_caps(text: str) -> bool:
        """
        Check if text is predominantly uppercase letters.
        
        Used to detect ALL CAPS action lines (sound effects, emphasis)
        which should not be grammar checked.
        
        Args:
            text: The text to analyze
            
        Returns:
            True if >= 70% of alphabetic characters are uppercase
        """
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False
        caps = sum(1 for c in letters if c.isupper())
        return (caps / len(letters)) >= _CAPS_RATIO_THRESHOLD

    @staticmethod
    def _detect_emphasis(text: str) -> list[tuple[int, int]]:
        """
        Detect emphasis spans (*text* or _text_) and return their positions.
        
        Scans the text for Fountain emphasis markers and returns
        a list of (start, end) tuples indicating the character positions
        of each emphasis span, including the delimiters.
        
        Args:
            text: The text to scan for emphasis markers
            
        Returns:
            List of (start, end) tuples for each emphasis span found.
            Empty list if no emphasis detected.
            
        Example:
            >>> _detect_emphasis("He *really* meant it.")
            [(4, 11)]  # "*really*" spans positions 4-11
        """
        spans: list[tuple[int, int]] = []
        for match in _RE_EMPHASIS.finditer(text):
            spans.append((match.start(), match.end()))
        return spans

    @property
    def in_dialogue(self) -> bool:
        """
        Check if parser is currently in a dialogue block context.
        
        Returns:
            True if the last classified element started a dialogue block
        """
        return self._in_dialogue_block


# ─── Convenience function ─────────────────────────────────────────────────────


def parse_extracted_text(text: str) -> ParsedBlock:
    """
    Stateless convenience wrapper for single-shot text classification.
    
    Creates a fresh parser instance, classifies the text, and returns
    the result. Use this for one-off classifications where context
    tracking is not needed.
    
    For multi-line or stateful parsing, create a FountainParser()
    instance directly and call classify() repeatedly.
    
    Args:
        text: The screenplay text to classify
        
    Returns:
        ParsedBlock with classification results
        
    Example:
        >>> result = parse_extracted_text("INT. HOUSE - DAY")
        >>> result.element
        <FountainElement.SLUGLINE: 'slugline'>
        >>> result.should_check
        False
    """
    parser = FountainParser()
    return parser.classify_raw_extract(text)
