"""
test_parser.py — Comprehensive Fountain Parser Tests

Covers:
- Slugline detection (INT., EXT., EST., INT/EXT, I/E, etc.)
- Character name recognition (with commas, extensions, apostrophes)
- Dialogue detection (context-aware)
- Action line detection (including all-caps skip)
- Transition detection (standard and forced)
- Parenthetical detection
- Dual dialogue (^text)
- Forced action (!text)
- Emphasis spans (*text*, _text_)
- Line breaks (<br>, double space)
- should_check logic for each element type
- Edge cases and malformed input
- classify_raw_extract for multi-line extracts
- Context state machine behavior
"""

import pytest
from gramwrite.fountain_parser import (
    FountainParser,
    FountainElement as ParserState,
    ParsedBlock,
    parse_extracted_text,
)


# ─── Basic / Empty Input Tests ───────────────────────────────────────────────


def test_empty_string(parser):
    result = parser.classify("")
    assert result.element == ParserState.UNKNOWN
    assert result.should_check is False
    assert result.reason == "Empty text"


def test_whitespace_only(parser):
    result = parser.classify("   \n\t  ")
    assert result.element == ParserState.UNKNOWN
    assert result.should_check is False


def test_none_like_input(parser):
    """Empty string after strip should be treated as unknown."""
    result = parser.classify("")
    assert result.text == ""


# ─── Slugline Detection Tests ────────────────────────────────────────────────


class TestSluglines:
    def test_int_slugline(self, parser):
        assert parser.classify("INT. OFFICE - DAY").element == ParserState.SLUGLINE

    def test_ext_slugline(self, parser):
        assert parser.classify("EXT. HIGHWAY - NIGHT").element == ParserState.SLUGLINE

    def test_est_slugline(self, parser):
        assert parser.classify("EST. CITY SKYLINE - DAWN").element == ParserState.SLUGLINE

    def test_int_ext_slugline(self, parser):
        assert parser.classify("INT/EXT. CAR - MOVING").element == ParserState.SLUGLINE

    def test_ext_int_slugline(self, parser):
        assert parser.classify("EXT/INT. BUILDING - DAY").element == ParserState.SLUGLINE

    def test_ie_slugline(self, parser):
        assert parser.classify("I/E. CAR - CONTINUOUS").element == ParserState.SLUGLINE

    def test_slugline_case_insensitive(self, parser):
        assert parser.classify("int. office - day").element == ParserState.SLUGLINE

    def test_slugline_with_various_time_markers(self, parser):
        assert parser.classify("INT. ROOM - LATER").element == ParserState.SLUGLINE
        parser.reset_context()
        assert parser.classify("EXT. PARK - MOMENTS LATER").element == ParserState.SLUGLINE

    def test_forced_slugline_with_dot(self, parser):
        assert parser.classify(".INT. SECRET ROOM - NIGHT").element == ParserState.SLUGLINE

    def test_slugline_resets_dialogue_context(self, parser):
        parser.classify("JOHN")
        parser.classify("Some dialogue")
        result = parser.classify("INT. NEW SCENE - DAY")
        assert result.element == ParserState.SLUGLINE
        assert result.should_check is False
        assert parser._in_dialogue_block is False

    def test_slugline_not_checked(self, parser):
        result = parser.classify("INT. HOUSE - DAY")
        assert result.should_check is False
        assert "slugline" in result.reason.lower() or "scene" in result.reason.lower()


# ─── Character Name Recognition Tests ────────────────────────────────────────


class TestCharacterNames:
    def test_simple_character(self, parser):
        assert parser.classify("JOHN").element == ParserState.CHARACTER

    def test_multi_word_character(self, parser):
        parser.reset_context()
        assert parser.classify("MARY JANE").element == ParserState.CHARACTER

    def test_character_with_extension(self, parser):
        parser.reset_context()
        assert parser.classify("POLICE OFFICER (O.S.)").element == ParserState.CHARACTER

    def test_character_with_vo(self, parser):
        parser.reset_context()
        assert parser.classify("NARRATOR (V.O.)").element == ParserState.CHARACTER

    def test_character_with_comma_jr(self, parser):
        parser.reset_context()
        assert parser.classify("JOHN CARTER, JR.").element == ParserState.CHARACTER

    def test_character_with_apostrophe(self, parser):
        parser.reset_context()
        assert parser.classify("O'NEIL (V.O.)").element == ParserState.CHARACTER

    def test_lowercase_not_character(self, parser):
        parser.reset_context()
        assert parser.classify("John").element == ParserState.ACTION

    def test_character_sets_dialogue_context(self, parser):
        parser.classify("JOHN")
        assert parser._in_dialogue_block is True

    def test_character_not_checked(self, parser):
        result = parser.classify("JOHN")
        assert result.should_check is False
        assert "character" in result.reason.lower()

    def test_too_many_words_not_character(self, parser):
        """Character names should be limited to ~6 words."""
        parser.reset_context()
        long_name = "A B C D E F G"
        result = parser.classify(long_name)
        # Should fall through to action since too many words
        assert result.element != ParserState.CHARACTER


# ─── Dialogue Detection Tests ────────────────────────────────────────────────


class TestDialogue:
    def test_dialogue_after_character(self, parser):
        parser.classify("JOHN")
        result = parser.classify("I can't believe you did that.")
        assert result.element == ParserState.DIALOGUE
        assert result.should_check is True

    def test_multiline_dialogue(self, parser):
        parser.classify("MARY")
        parser.classify("First line of dialogue.")
        result = parser.classify("Second line continues.")
        assert result.element == ParserState.DIALOGUE
        assert result.should_check is True

    def test_dialogue_text_preserved(self, parser):
        parser.classify("JOHN")
        result = parser.classify("Hello world.")
        assert result.text == "Hello world."

    def test_dialogue_reason(self, parser):
        parser.classify("JOHN")
        result = parser.classify("Some text.")
        assert "dialogue" in result.reason.lower()


# ─── Action Line Detection Tests ─────────────────────────────────────────────


class TestActionLines:
    def test_simple_action(self, parser):
        parser.reset_context()
        result = parser.classify("He walked across the room.")
        assert result.element == ParserState.ACTION
        assert result.should_check is True

    def test_action_after_slugline(self, parser):
        parser.classify("INT. ROOM - DAY")
        result = parser.classify("The sun shines through the window.")
        assert result.element == ParserState.ACTION

    def test_action_after_transition(self, parser):
        parser.classify("CUT TO:")
        result = parser.classify("A dark alley.")
        assert result.element == ParserState.ACTION

    def test_all_caps_action_not_checked(self, parser):
        """All-caps action lines (sound effects) should not be checked."""
        parser.reset_context()
        result = parser.classify("BAM! CRASH! BOOM!")
        assert result.element == ParserState.ACTION
        assert result.should_check is False

    def test_action_reason(self, parser):
        parser.reset_context()
        result = parser.classify("He walks to the door.")
        assert "action" in result.reason.lower()

    def test_action_preserves_text(self, parser):
        parser.reset_context()
        text = "The cat sat on the mat."
        result = parser.classify(text)
        assert result.text == text


# ─── Transition Detection Tests ──────────────────────────────────────────────


class TestTransitions:
    def test_cut_to(self, parser):
        assert parser.classify("CUT TO:").element == ParserState.TRANSITION

    def test_fade_out(self, parser):
        parser.reset_context()
        assert parser.classify("FADE OUT.").element == ParserState.TRANSITION

    def test_fade_in(self, parser):
        parser.reset_context()
        assert parser.classify("FADE IN:").element == ParserState.TRANSITION

    def test_fade_to(self, parser):
        parser.reset_context()
        assert parser.classify("FADE TO:").element == ParserState.TRANSITION

    def test_smash_cut(self, parser):
        parser.reset_context()
        assert parser.classify("SMASH CUT TO:").element == ParserState.TRANSITION

    def test_match_cut(self, parser):
        parser.reset_context()
        assert parser.classify("MATCH CUT TO:").element == ParserState.TRANSITION

    def test_dissolve_to(self, parser):
        parser.reset_context()
        assert parser.classify("DISSOLVE TO:").element == ParserState.TRANSITION

    def test_forced_transition(self, parser):
        parser.reset_context()
        assert parser.classify("> FADE OUT.").element == ParserState.TRANSITION

    def test_transition_resets_dialogue(self, parser):
        parser.classify("JOHN")
        parser.classify("Some dialogue")
        result = parser.classify("CUT TO:")
        assert result.element == ParserState.TRANSITION
        assert parser._in_dialogue_block is False

    def test_transition_not_checked(self, parser):
        result = parser.classify("CUT TO:")
        assert result.should_check is False


# ─── Parenthetical Detection Tests ───────────────────────────────────────────


class TestParentheticals:
    def test_simple_parenthetical(self, parser):
        assert parser.classify("(sighs)").element == ParserState.PARENTHETICAL

    def test_parenthetical_with_spaces(self, parser):
        assert parser.classify(" (whispering) ").element == ParserState.PARENTHETICAL

    def test_beat(self, parser):
        parser.reset_context()
        assert parser.classify("(beat)").element == ParserState.PARENTHETICAL

    def test_parenthetical_not_checked(self, parser):
        result = parser.classify("(sighs)")
        assert result.should_check is False

    def test_parenthetical_reason(self, parser):
        result = parser.classify("(beat)")
        assert "parenthetical" in result.reason.lower()


# ─── Dual Dialogue Tests ─────────────────────────────────────────────────────


class TestDualDialogue:
    def test_dual_dialogue_detection(self, parser):
        result = parser.classify("^I'm talking at the same time!")
        assert result.element == ParserState.DIALOGUE
        assert result.is_dual_dialogue is True
        assert result.text == "I'm talking at the same time!"
        assert result.should_check is True

    def test_dual_dialogue_strips_prefix(self, parser):
        result = parser.classify("^Hello world")
        assert result.text == "Hello world"

    def test_dual_dialogue_sets_context(self, parser):
        parser.classify("^First line of dual dialogue")
        result = parser.classify("Second line continues")
        assert result.element == ParserState.DIALOGUE

    def test_dual_dialogue_reason(self, parser):
        result = parser.classify("^Dual dialogue line")
        assert "dual" in result.reason.lower()


# ─── Forced Action Tests ─────────────────────────────────────────────────────


class TestForcedAction:
    def test_forced_action_detection(self, parser):
        result = parser.classify("!This is forced action")
        assert result.element == ParserState.ACTION
        assert result.is_forced_action is True
        assert result.text == "This is forced action"
        assert result.should_check is True

    def test_forced_action_strips_prefix(self, parser):
        result = parser.classify("!Hello world")
        assert result.text == "Hello world"

    def test_forced_action_breaks_dialogue(self, parser):
        parser.classify("JOHN")
        parser.classify("Some dialogue here")
        result = parser.classify("!Forced action line")
        assert result.element == ParserState.ACTION
        assert result.is_forced_action is True
        assert parser._in_dialogue_block is False

    def test_forced_action_reason(self, parser):
        result = parser.classify("!Forced text")
        assert "forced" in result.reason.lower()


# ─── Emphasis Detection Tests ────────────────────────────────────────────────


class TestEmphasis:
    def test_emphasis_asterisk(self, parser):
        result = parser.classify("He *really* meant it.")
        assert result.emphasis_spans is not None
        assert len(result.emphasis_spans) == 1
        start, end = result.emphasis_spans[0]
        assert result.text[start:end] == "*really*"

    def test_emphasis_underscore(self, parser):
        result = parser.classify("She _whispered_ softly.")
        assert result.emphasis_spans is not None
        assert len(result.emphasis_spans) == 1
        start, end = result.emphasis_spans[0]
        assert result.text[start:end] == "_whispered_"

    def test_emphasis_multiple(self, parser):
        result = parser.classify("He *shouted* and _cried_ at once.")
        assert result.emphasis_spans is not None
        assert len(result.emphasis_spans) == 2

    def test_emphasis_in_dialogue(self, parser):
        parser.classify("JOHN")
        result = parser.classify("I *never* said that!")
        assert result.element == ParserState.DIALOGUE
        assert result.emphasis_spans is not None
        assert len(result.emphasis_spans) == 1

    def test_no_emphasis(self, parser):
        result = parser.classify("Just a normal line.")
        assert result.emphasis_spans is not None
        assert len(result.emphasis_spans) == 0

    def test_emphasis_preserved_in_action(self, parser):
        parser.reset_context()
        result = parser.classify("He *slowly* opened the door.")
        assert len(result.emphasis_spans) == 1


# ─── Line Break Tests ────────────────────────────────────────────────────────


class TestLineBreaks:
    def test_line_break_html_br(self, parser):
        result = parser.classify("First line<br>Second line")
        assert result.has_line_breaks is True

    def test_line_break_html_br_self_closing(self, parser):
        result = parser.classify("First line<br/>Second line")
        assert result.has_line_breaks is True

    def test_line_break_html_br_with_space(self, parser):
        result = parser.classify("First line<br />Second line")
        assert result.has_line_breaks is True

    def test_line_break_double_space(self, parser):
        result = parser.classify("First line  Second line")
        assert result.has_line_breaks is True

    def test_no_line_breaks(self, parser):
        result = parser.classify("Just a normal line.")
        assert result.has_line_breaks is False

    def test_line_breaks_in_action(self, parser):
        result = parser.classify("He walked in.<br>She looked up.")
        assert result.element == ParserState.ACTION
        assert result.has_line_breaks is True


# ─── Special Element Tests ───────────────────────────────────────────────────


class TestSpecialElements:
    def test_fountain_note(self, parser):
        result = parser.classify("[[This is a note]]")
        assert result.element == ParserState.NOTE
        assert result.should_check is False

    def test_centered_text(self, parser):
        result = parser.classify("> CENTERED TEXT <")
        assert result.element == ParserState.CENTERED
        assert result.should_check is False

    def test_section_marker(self, parser):
        result = parser.classify("# ACT ONE")
        assert result.should_check is False

    def test_synopsis_marker(self, parser):
        result = parser.classify("= This is a synopsis line")
        assert result.should_check is False


# ─── should_check Logic Tests ────────────────────────────────────────────────


class TestShouldCheck:
    def test_slugline_not_checked(self, parser):
        assert parser.classify("INT. ROOM - DAY").should_check is False

    def test_character_not_checked(self, parser):
        assert parser.classify("JOHN").should_check is False

    def test_transition_not_checked(self, parser):
        assert parser.classify("CUT TO:").should_check is False

    def test_parenthetical_not_checked(self, parser):
        assert parser.classify("(beat)").should_check is False

    def test_dialogue_checked(self, parser):
        parser.classify("JOHN")
        assert parser.classify("Hello world.").should_check is True

    def test_action_checked(self, parser):
        parser.reset_context()
        assert parser.classify("He walks to the store.").should_check is True

    def test_all_caps_action_not_checked(self, parser):
        parser.reset_context()
        assert parser.classify("BANG! CRASH!").should_check is False

    def test_dual_dialogue_checked(self, parser):
        assert parser.classify("^Dual line").should_check is True

    def test_forced_action_checked(self, parser):
        assert parser.classify("!Forced text").should_check is True


# ─── Context State Machine Tests ─────────────────────────────────────────────


class TestContextStateMachine:
    def test_reset_context(self, parser):
        parser.classify("JOHN")
        assert parser._in_dialogue_block is True
        parser.reset_context()
        assert parser._in_dialogue_block is False

    def test_in_dialogue_property(self, parser):
        assert parser.in_dialogue is False
        parser.classify("JOHN")
        assert parser.in_dialogue is True

    def test_context_carries_across_lines(self, parser):
        parser.classify("JOHN")
        parser.classify("Line one.")
        parser.classify("Line two.")
        result = parser.classify("Line three.")
        assert result.element == ParserState.DIALOGUE

    def test_slugline_breaks_dialogue_context(self, parser):
        parser.classify("JOHN")
        parser.classify("Dialogue here.")
        parser.classify("INT. NEW SCENE - DAY")
        parser.classify("Action text.")
        result = parser.classify("More action.")
        assert result.element == ParserState.ACTION

    def test_fresh_parser_starts_unknown(self, parser):
        assert parser._last_element == ParserState.UNKNOWN
        assert parser._in_dialogue_block is False


# ─── classify_raw_extract Tests ──────────────────────────────────────────────


class TestClassifyRawExtract:
    def test_multi_line_extract(self, parser):
        text = "INT. ROOM - DAY\nHe walks in."
        result = parser.classify_raw_extract(text)
        assert result.element == ParserState.ACTION

    def test_empty_extract(self, parser):
        result = parser.classify_raw_extract("")
        assert result.element == ParserState.UNKNOWN
        assert result.should_check is False

    def test_whitespace_only_extract(self, parser):
        result = parser.classify_raw_extract("   \n\n  ")
        assert result.element == ParserState.UNKNOWN

    def test_extract_with_dialogue_context(self, parser):
        text = "JOHN\nI don't know."
        result = parser.classify_raw_extract(text)
        assert result.element == ParserState.DIALOGUE

    def test_extract_preserves_last_line_classification(self, parser):
        text = "INT. ROOM - DAY\nHe walks in.\nBANG!"
        result = parser.classify_raw_extract(text)
        # Last line is all caps, so it's action but not checked
        assert result.element == ParserState.ACTION


# ─── parse_extracted_text Convenience Function Tests ─────────────────────────


class TestParseExtractedText:
    def test_stateless_wrapper_slugline(self):
        result = parse_extracted_text("INT. ROOM - DAY")
        assert result.element == ParserState.SLUGLINE

    def test_stateless_wrapper_action(self):
        result = parse_extracted_text("He walks to the store.")
        assert result.element == ParserState.ACTION

    def test_stateless_wrapper_creates_fresh_parser(self):
        """Each call should use a fresh parser (no context carryover)."""
        parse_extracted_text("JOHN")
        result = parse_extracted_text("Some text.")
        # Without context, this should be action, not dialogue
        assert result.element == ParserState.ACTION


# ─── ParsedBlock Tests ───────────────────────────────────────────────────────


class TestParsedBlock:
    def test_to_dict(self, parser):
        result = parser.classify("INT. ROOM - DAY")
        d = result.to_dict()
        assert d["type"] == "slugline"
        assert d["text"] == "INT. ROOM - DAY"
        assert d["should_check"] is False
        assert d["is_dual_dialogue"] is False
        assert d["is_forced_action"] is False
        assert d["has_line_breaks"] is False

    def test_to_dict_with_dual_dialogue(self, parser):
        result = parser.classify("^Dual line")
        d = result.to_dict()
        assert d["is_dual_dialogue"] is True

    def test_to_dict_with_forced_action(self, parser):
        result = parser.classify("!Forced text")
        d = result.to_dict()
        assert d["is_forced_action"] is True


# ─── Edge Cases and Malformed Input ──────────────────────────────────────────


class TestEdgeCases:
    def test_very_long_line(self, parser):
        long_text = "A" * 10000
        result = parser.classify(long_text)
        assert result.element == ParserState.ACTION
        assert result.should_check is True

    def test_unicode_text(self, parser):
        result = parser.classify("He said café.")
        assert result.element == ParserState.ACTION

    def test_special_characters(self, parser):
        result = parser.classify("@#$%^&*()")
        # Should not crash, classify as something
        assert result is not None

    def test_mixed_case_slugline(self, parser):
        assert parser.classify("Int. Office - Day").element == ParserState.SLUGLINE

    def test_slugline_without_time_marker(self, parser):
        assert parser.classify("INT. OFFICE").element == ParserState.SLUGLINE

    def test_character_with_hyphen(self, parser):
        parser.reset_context()
        assert parser.classify("MARY-JANE").element == ParserState.CHARACTER

    def test_empty_parenthetical(self, parser):
        result = parser.classify("()")
        assert result.element == ParserState.PARENTHETICAL

    def test_transition_lowercase(self, parser):
        parser.reset_context()
        assert parser.classify("cut to:").element == ParserState.TRANSITION

    def test_action_with_numbers(self, parser):
        parser.reset_context()
        result = parser.classify("He has 3 apples and 2 oranges.")
        assert result.element == ParserState.ACTION

    def test_action_with_quotes(self, parser):
        parser.reset_context()
        result = parser.classify('He said "hello".')
        assert result.element == ParserState.ACTION
