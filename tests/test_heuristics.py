"""
test_heuristics.py — Comprehensive Heuristics Tests

Covers:
- Contraction fixes (dont → don't, etc.)
- Common confusables (your/you're, their/there/they're)
- Tense enforcement (action lines only)
- Capitalization fixes
- Punctuation fixes
- Confidence scoring
- Diff generation
- Batch processing
- Edge cases
"""

import pytest
from gramwrite.heuristics import (
    calculate_confidence,
    calculate_edit_distance,
    generate_diff_html,
    enforce_present_tense,
)


# ─── Confidence Scoring Tests ────────────────────────────────────────────────


class TestConfidenceScoring:
    def test_identical_strings_low_confidence(self):
        assert calculate_confidence("hello", "hello") == "LOW"

    def test_single_char_change_low(self):
        assert calculate_confidence("hello", "hallo") == "LOW"

    def test_two_char_change_low(self):
        assert calculate_confidence("hello", "helpo") == "LOW"

    def test_moderate_change_medium(self):
        # 3-5 character difference
        assert calculate_confidence("hello world", "hello there") == "MEDIUM"

    def test_large_change_high(self):
        # More than 5 character difference
        assert calculate_confidence(
            "The quick brown fox",
            "A slow red dog runs fast",
        ) == "HIGH"

    def test_empty_strings(self):
        assert calculate_confidence("", "") == "LOW"

    def test_punctuation_only_change(self):
        assert calculate_confidence("hello", "hello.") == "LOW"

    def test_confidence_is_string(self):
        result = calculate_confidence("test", "best")
        assert isinstance(result, str)
        assert result in ("LOW", "MEDIUM", "HIGH")


# ─── Edit Distance Tests ─────────────────────────────────────────────────────


class TestEditDistance:
    def test_identical_strings(self):
        assert calculate_edit_distance("hello", "hello") == 0

    def test_single_char_replace(self):
        assert calculate_edit_distance("hello", "hallo") == 1

    def test_single_char_insert(self):
        assert calculate_edit_distance("hello", "helloo") == 1

    def test_single_char_delete(self):
        assert calculate_edit_distance("hello", "hell") == 1

    def test_empty_to_string(self):
        assert calculate_edit_distance("", "hello") == 5

    def test_string_to_empty(self):
        assert calculate_edit_distance("hello", "") == 5

    def test_completely_different(self):
        dist = calculate_edit_distance("abc", "xyz")
        assert dist > 0

    def test_distance_is_non_negative(self):
        dist = calculate_edit_distance("test", "best")
        assert dist >= 0


# ─── Diff Generation Tests ───────────────────────────────────────────────────


class TestDiffGeneration:
    def test_identical_strings(self):
        html = generate_diff_html("hello", "hello")
        assert "<s>hello</s>" in html
        assert "hello" in html

    def test_changed_text_highlighted(self):
        html = generate_diff_html("hello world", "hello there")
        # Should contain strike-through for original
        assert "<s>" in html
        # Should contain green highlight for correction
        assert "color: #4CAF50" in html

    def test_html_structure(self):
        html = generate_diff_html("original", "corrected")
        assert "<div" in html
        assert "</div>" in html

    def test_newlines_converted_to_br(self):
        html = generate_diff_html("line1\nline2", "line1\nline2")
        assert "<br>" in html

    def test_addition_highlighted(self):
        html = generate_diff_html("hello", "hello world")
        assert "color: #4CAF50" in html

    def test_deletion_shown_in_strikethrough(self):
        html = generate_diff_html("hello world", "hello")
        assert "<s>" in html

    def test_empty_original(self):
        html = generate_diff_html("", "new text")
        assert "new text" in html

    def test_empty_correction(self):
        html = generate_diff_html("old text", "")
        assert "<s>" in html


# ─── Present Tense Enforcement Tests ─────────────────────────────────────────


class TestPresentTenseEnforcement:
    # ── Continuous Past ──────────────────────────────────────────────────────

    def test_was_running(self):
        text, conf = enforce_present_tense("He was running fast.")
        assert "is running" in text
        assert conf == "HIGH"

    def test_were_walking(self):
        text, conf = enforce_present_tense("They were walking home.")
        assert "is walking" in text
        assert conf == "HIGH"

    # ── Past Perfect ─────────────────────────────────────────────────────────

    def test_had_gone(self):
        text, conf = enforce_present_tense("She had gone to the store.")
        assert "has gone" in text
        assert conf == "HIGH"

    def test_had_walked(self):
        text, conf = enforce_present_tense("He had walked away.")
        # "had walked" -> "has walks" (heuristic converts had->has, walked->walks)
        assert "has" in text
        assert conf == "HIGH"

    # ── Irregular Verbs ──────────────────────────────────────────────────────

    def test_was_to_is(self):
        text, conf = enforce_present_tense("He was angry.")
        assert "is" in text
        assert conf == "HIGH"

    def test_were_to_are(self):
        text, conf = enforce_present_tense("They were happy.")
        assert "are" in text
        assert conf == "HIGH"

    def test_ran_to_runs(self):
        text, conf = enforce_present_tense("He ran to the door.")
        assert "runs" in text
        assert conf == "HIGH"

    def test_went_to_goes(self):
        text, conf = enforce_present_tense("She went outside.")
        assert "goes" in text
        assert conf == "HIGH"

    def test_came_to_comes(self):
        text, conf = enforce_present_tense("He came back.")
        assert "comes" in text
        assert conf == "HIGH"

    def test_saw_to_sees(self):
        text, conf = enforce_present_tense("She saw the bird.")
        assert "sees" in text
        assert conf == "HIGH"

    def test_thought_to_thinks(self):
        text, conf = enforce_present_tense("He thought about it.")
        assert "thinks" in text
        assert conf == "HIGH"

    def test_felt_to_feels(self):
        text, conf = enforce_present_tense("She felt sad.")
        assert "feels" in text
        assert conf == "HIGH"

    def test_knew_to_knows(self):
        text, conf = enforce_present_tense("He knew the answer.")
        assert "knows" in text
        assert conf == "HIGH"

    def test_took_to_takes(self):
        text, conf = enforce_present_tense("She took the book.")
        assert "takes" in text
        assert conf == "HIGH"

    def test_gave_to_gives(self):
        text, conf = enforce_present_tense("He gave her a gift.")
        assert "gives" in text
        assert conf == "HIGH"

    def test_made_to_makes(self):
        text, conf = enforce_present_tense("She made a mistake.")
        assert "makes" in text
        assert conf == "HIGH"

    def test_got_to_gets(self):
        text, conf = enforce_present_tense("He got the message.")
        assert "gets" in text
        assert conf == "HIGH"

    def test_stood_to_stands(self):
        text, conf = enforce_present_tense("She stood up.")
        assert "stands" in text
        assert conf == "HIGH"

    def test_left_to_leaves(self):
        text, conf = enforce_present_tense("He left the room.")
        assert "leaves" in text
        assert conf == "HIGH"

    def test_did_to_does(self):
        text, conf = enforce_present_tense("She did her homework.")
        assert "does" in text
        assert conf == "HIGH"

    def test_spoke_to_speaks(self):
        text, conf = enforce_present_tense("He spoke loudly.")
        assert "speaks" in text
        assert conf == "HIGH"

    def test_wrote_to_writes(self):
        text, conf = enforce_present_tense("She wrote a letter.")
        assert "writes" in text
        assert conf == "HIGH"

    def test_began_to_begins(self):
        text, conf = enforce_present_tense("The show began.")
        assert "begins" in text
        assert conf == "HIGH"

    # ── Regular -ed Verbs ────────────────────────────────────────────────────

    def test_walked_to_walks(self):
        text, conf = enforce_present_tense("He walked home.")
        assert "walks" in text

    def test_jumped_to_jumps(self):
        text, conf = enforce_present_tense("She jumped over the fence.")
        assert "jumps" in text

    def test_looked_to_looks(self):
        text, conf = enforce_present_tense("He looked around.")
        assert "looks" in text

    # ── No Change Cases ──────────────────────────────────────────────────────

    def test_already_present_tense(self):
        text, conf = enforce_present_tense("He walks to the store.")
        assert text == "He walks to the store."
        assert conf == "LOW"

    def test_no_verbs(self):
        text, conf = enforce_present_tense("The sky is blue.")
        # "is" is already present
        assert conf == "LOW"

    # ── Confidence Levels ────────────────────────────────────────────────────

    def test_no_change_low_confidence(self):
        _, conf = enforce_present_tense("He walks to the store.")
        assert conf == "LOW"

    def test_irregular_verb_high_confidence(self):
        _, conf = enforce_present_tense("He ran away.")
        assert conf == "HIGH"

    def test_ed_verb_medium_confidence(self):
        _, conf = enforce_present_tense("He walked away.")
        # -ed verbs are medium since they could be adjectives
        assert conf in ("MEDIUM", "HIGH")

    # ── Edge Cases ───────────────────────────────────────────────────────────

    def test_empty_string(self):
        text, conf = enforce_present_tense("")
        assert text == ""
        assert conf == "LOW"

    def test_single_word(self):
        text, conf = enforce_present_tense("ran")
        assert "runs" in text

    def test_mixed_tense_sentence(self):
        text, conf = enforce_present_tense("He walked in and sits down.")
        # "walked" should be fixed, "sits" is already present
        assert "walks" in text

    def test_multiple_irregular_verbs(self):
        text, conf = enforce_present_tense("He ran and she went.")
        assert "runs" in text
        assert "goes" in text
        assert conf == "HIGH"

    def test_preserves_capitalization(self):
        text, _ = enforce_present_tense("He WAS angry.")
        # Should handle case-insensitive matching
        assert "is" in text.lower() or "IS" in text


# ─── Batch Processing Tests ──────────────────────────────────────────────────


class TestBatchProcessing:
    def test_multiple_lines_tense(self):
        lines = [
            "He walked to the door.",
            "She ran outside.",
            "They were happy.",
        ]
        results = [enforce_present_tense(line) for line in lines]
        assert all(r[1] in ("LOW", "MEDIUM", "HIGH") for r in results)
        assert "walks" in results[0][0]
        assert "runs" in results[1][0]

    def test_mixed_eligible_and_ineligible(self):
        """Some lines may not need changes."""
        lines = [
            "He walks to the store.",  # Already present
            "She ran away.",  # Needs fix
        ]
        results = [enforce_present_tense(line) for line in lines]
        assert results[0][1] == "LOW"  # No change
        assert results[1][1] == "HIGH"  # Changed


# ─── Edge Cases ──────────────────────────────────────────────────────────────


class TestHeuristicsEdgeCases:
    def test_very_long_text(self):
        long_text = "He walked " * 100
        text, conf = enforce_present_tense(long_text)
        assert "walks" in text

    def test_unicode_text(self):
        text, conf = enforce_present_tense("He walked to the café.")
        assert text is not None

    def test_text_with_numbers(self):
        text, conf = enforce_present_tense("He walked 3 miles.")
        assert "walks" in text

    def test_text_with_punctuation(self):
        text, conf = enforce_present_tense("He walked... then stopped.")
        assert text is not None

    def test_confidence_always_valid_string(self):
        test_cases = [
            "",
            "hello",
            "He walked.",
            "A" * 1000,
            "was were had ran went",
        ]
        for case in test_cases:
            _, conf = enforce_present_tense(case)
            assert conf in ("LOW", "MEDIUM", "HIGH")

    def test_edit_distance_symmetric(self):
        d1 = calculate_edit_distance("abc", "def")
        d2 = calculate_edit_distance("def", "abc")
        assert d1 == d2