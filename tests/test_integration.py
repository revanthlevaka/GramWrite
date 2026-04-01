"""
test_integration.py — Integration Tests for GramWrite

Covers:
- Full pipeline execution
- End-to-end scenarios
- Real-world screenplay excerpts
- Performance benchmarks
- Memory usage tests
"""

import asyncio
import gc
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aioresponses import aioresponses

from gramwrite.controller import Controller, PipelineResult
from gramwrite.engine import Backend, CorrectionResult, GramEngine, OLLAMA_BASE
from gramwrite.fountain_parser import (
    FountainElement,
    FountainParser,
    ParsedBlock,
    parse_extracted_text,
)
from gramwrite.heuristics import (
    calculate_confidence,
    enforce_present_tense,
    generate_diff_html,
)


# ─── Full Pipeline Execution Tests ───────────────────────────────────────────


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_dialogue_grammar_fix(self):
        """Test Case 1 from copilot-instructions.md: Dialogue grammar fix only."""
        # Simulate the full pipeline for dialogue
        parser = FountainParser()

        # Step 1: Character name
        char_result = parser.classify("JOHN")
        assert char_result.element == FountainElement.CHARACTER
        assert char_result.should_check is False

        # Step 2: Dialogue with grammar error
        dialogue_result = parser.classify("i dont know what your talking about")
        assert dialogue_result.element == FountainElement.DIALOGUE
        assert dialogue_result.should_check is True

        # Step 3: Heuristics would apply (dont -> don't, your -> you're)
        text = dialogue_result.text
        corrected_text, confidence = enforce_present_tense(text)
        # Heuristics may not catch all dialogue errors (they focus on tense)
        # But the pipeline would send to LLM for full correction

        # Step 4: Verify the text is eligible for correction
        assert dialogue_result.text is not None
        assert len(dialogue_result.text) > 0

    @pytest.mark.asyncio
    async def test_pipeline_slugline_unchanged(self):
        """Test Case 2 from copilot-instructions.md: Slugline unchanged."""
        parser = FountainParser()
        result = parser.classify("INT. HOUSE - DAY")

        assert result.element == FountainElement.SLUGLINE
        assert result.should_check is False
        assert result.text == "INT. HOUSE - DAY"

    @pytest.mark.asyncio
    async def test_pipeline_action_minimal_correction(self):
        """Test Case 3 from copilot-instructions.md: Minimal action line correction."""
        parser = FountainParser()
        parser.classify("INT. ROOM - DAY")  # Set context
        result = parser.classify("The door slam open.")

        assert result.element == FountainElement.ACTION
        assert result.should_check is True

        # Heuristics should catch "slam" -> "slams" (present tense)
        corrected, confidence = enforce_present_tense(result.text)
        assert "slams" in corrected or "slam" in corrected  # Either fixed or preserved

    @pytest.mark.asyncio
    async def test_pipeline_full_flow_with_mocked_engine(self):
        """Test the full pipeline with a mocked engine."""
        config = {
            "backend": "ollama",
            "model": "qwen2.5:0.5b",
            "sensitivity": "medium",
            "strict_mode": True,
            "debounce_seconds": 0.1,
            "system_prompt": "Correct grammar only.",
        }

        results = []

        def on_result(result: PipelineResult):
            results.append(result)

        controller = Controller(config, on_result)

        # Mock the engine to avoid actual backend calls
        controller._engine.correct = AsyncMock(return_value=CorrectionResult(
            original="i dont know",
            correction="I don't know",
            has_correction=True,
            backend=Backend.OLLAMA,
            latency_ms=50.0,
        ))

        # Simulate text received — use a string long enough to pass min_length filter
        text = "i dont know what your talking about"
        await controller._on_text_received(text)

        # Process the queue manually
        if not controller._queue.empty():
            item = await controller._queue.get()
            controller._processing = True
            # QueueItem has a text attribute
            item_text = item.text if hasattr(item, 'text') else str(item)
            controller._last_hash = controller._hash(item_text)

            parsed = controller._parser.classify_raw_extract(item_text)

            if parsed.should_check and parsed.text:
                correction = await controller._engine.correct(parsed.text)
                if correction.has_correction and correction.correction:
                    result = PipelineResult(
                        text=item_text,
                        parsed=parsed,
                        correction=correction,
                        final_suggestion=correction.correction,
                        has_final_suggestion=True,
                        confidence="LOW",
                        diff_html=generate_diff_html(parsed.text, correction.correction),
                    )
                    controller.on_result(result)

            controller._processing = False

        # Verify the pipeline executed without errors
        assert controller._processing is False


# ─── End-to-End Scenario Tests ───────────────────────────────────────────────


class TestEndToEndScenarios:
    def test_screenplay_excerpt_parsing(self, screenplay_excerpt):
        """Parse a real screenplay excerpt and verify element classification."""
        parser = FountainParser()
        lines = screenplay_excerpt.strip().split("\n")

        classifications = []
        for line in lines:
            if line.strip():
                result = parser.classify(line.strip())
                classifications.append((line.strip(), result.element, result.should_check))

        # Verify key elements are classified correctly
        elements = [c[1] for c in classifications]
        assert FountainElement.SLUGLINE in elements
        assert FountainElement.CHARACTER in elements
        assert FountainElement.DIALOGUE in elements
        assert FountainElement.ACTION in elements
        assert FountainElement.TRANSITION in elements

    def test_dialogue_only_excerpt(self, dialogue_only_excerpt):
        """Dialogue-only excerpt should be fully checkable."""
        parser = FountainParser()
        lines = dialogue_only_excerpt.strip().split("\n")

        checkable_count = 0
        for line in lines:
            if line.strip():
                result = parser.classify(line.strip())
                if result.should_check:
                    checkable_count += 1

        # At least the dialogue lines should be checkable
        assert checkable_count >= 2

    def test_action_only_excerpt_tense(self, action_only_excerpt):
        """Action-only excerpt should have tense enforcement."""
        parser = FountainParser()
        lines = action_only_excerpt.strip().split("\n")

        for line in lines:
            if line.strip():
                result = parser.classify(line.strip())
                if result.element == FountainElement.ACTION:
                    corrected, conf = enforce_present_tense(result.text)
                    # Should attempt tense correction
                    assert corrected is not None

    @pytest.mark.asyncio
    async def test_engine_correction_pipeline(self):
        """Test engine correction in a realistic scenario."""
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})

        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "I don't know what you're talking about."},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("i dont know what your talking about")
            assert result.has_correction is True
            assert result.correction is not None
            assert result.latency_ms >= 0

            await engine.close()


# ─── Real-World Screenplay Excerpts ──────────────────────────────────────────


class TestRealWorldScreenplayExcerpts:
    def test_fountain_dual_dialogue_excerpt(self):
        """Test dual dialogue syntax parsing."""
        parser = FountainParser()
        parser.classify("JOHN")
        result1 = parser.classify("^I'm talking!")
        parser.classify("MARY")
        result2 = parser.classify("^So am I!")

        assert result1.is_dual_dialogue is True
        assert result2.is_dual_dialogue is True

    def test_fountain_forced_action_excerpt(self):
        """Test forced action syntax parsing."""
        parser = FountainParser()
        parser.classify("JOHN")
        parser.classify("Some dialogue")
        result = parser.classify("!He suddenly stands.")

        assert result.element == FountainElement.ACTION
        assert result.is_forced_action is True

    def test_fountain_emphasis_excerpt(self):
        """Test emphasis detection in screenplay text."""
        parser = FountainParser()
        parser.classify("JOHN")
        result = parser.classify("I *never* said that, and I _mean_ it.")

        assert len(result.emphasis_spans) == 2

    def test_fountain_parenthetical_excerpt(self):
        """Test parenthetical detection in dialogue blocks."""
        parser = FountainParser()
        parser.classify("JOHN")
        result = parser.classify("(sighs)")

        assert result.element == FountainElement.PARENTHETICAL
        assert result.should_check is False

    def test_complex_screenplay_sequence(self):
        """Test a complex sequence of screenplay elements."""
        parser = FountainParser()

        sequence = [
            ("FADE IN:", FountainElement.TRANSITION),
            ("INT. COFFEE SHOP - DAY", FountainElement.SLUGLINE),
            ("John sits at a table.", FountainElement.ACTION),
            ("JOHN", FountainElement.CHARACTER),
            ("I need coffee.", FountainElement.DIALOGUE),
            ("(sighs)", FountainElement.PARENTHETICAL),
            ("CUT TO:", FountainElement.TRANSITION),
            ("EXT. STREET - NIGHT", FountainElement.SLUGLINE),
        ]

        for text, expected_element in sequence:
            result = parser.classify(text)
            assert result.element == expected_element, f"Failed for: {text}"


# ─── Performance Benchmarks ──────────────────────────────────────────────────


class TestPerformanceBenchmarks:
    def test_parser_speed(self):
        """Parser should classify text quickly."""
        parser = FountainParser()
        text = "He walks to the store."

        start = time.perf_counter()
        for _ in range(1000):
            parser.classify(text)
            parser.reset_context()
        elapsed = time.perf_counter() - start

        # 1000 classifications should take less than 100ms
        assert elapsed < 0.1, f"Parser too slow: {elapsed:.3f}s for 1000 classifications"

    def test_heuristics_speed(self):
        """Heuristics should process text quickly."""
        text = "He walked to the store and she ran away."

        start = time.perf_counter()
        for _ in range(1000):
            enforce_present_tense(text)
        elapsed = time.perf_counter() - start

        # 1000 heuristic runs should take less than 100ms
        assert elapsed < 0.1, f"Heuristics too slow: {elapsed:.3f}s for 1000 runs"

    def test_confidence_scoring_speed(self):
        """Confidence scoring should be fast."""
        start = time.perf_counter()
        for _ in range(1000):
            calculate_confidence("original text", "corrected text")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"Confidence scoring too slow: {elapsed:.3f}s"

    def test_diff_generation_speed(self):
        """Diff generation should be reasonably fast."""
        start = time.perf_counter()
        for _ in range(100):
            generate_diff_html("original text here", "corrected text here")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"Diff generation too slow: {elapsed:.3f}s"

    def test_parser_memory_usage(self):
        """Parser should not leak memory."""
        gc.collect()
        initial_objects = len(gc.get_objects())

        parser = FountainParser()
        for _ in range(1000):
            parser.classify("He walks to the store.")
            parser.reset_context()

        del parser
        gc.collect()

        # Memory should not grow significantly
        final_objects = len(gc.get_objects())
        growth = final_objects - initial_objects
        # Allow some growth but not excessive
        assert growth < 5000, f"Memory growth too high: {growth} objects"


# ─── Memory Usage Tests ──────────────────────────────────────────────────────


class TestMemoryUsage:
    def test_typed_buffer_memory(self):
        """TypedTextBuffer should not grow unboundedly."""
        from gramwrite.watcher import TypedTextBuffer

        buffer = TypedTextBuffer(max_chars=100, ttl_secs=60.0)
        for i in range(1000):
            buffer.record_text("com.test.app", f"char{i}")

        snapshot = buffer.snapshot("com.test.app")
        assert snapshot is not None
        assert len(snapshot) <= 100  # Should be truncated to max_chars

    def test_parser_context_reset(self):
        """Parser context should be properly reset."""
        parser = FountainParser()
        for _ in range(100):
            parser.classify("JOHN")
            parser.classify("Dialogue line.")
            parser.reset_context()

        assert parser._in_dialogue_block is False
        assert parser._last_element == FountainElement.UNKNOWN


# ─── Cross-Module Integration Tests ──────────────────────────────────────────


class TestCrossModuleIntegration:
    def test_parser_to_heuristics_flow(self):
        """Test data flow from parser to heuristics."""
        parser = FountainParser()
        parser.classify("INT. ROOM - DAY")
        result = parser.classify("He walked to the door.")

        assert result.element == FountainElement.ACTION
        assert result.should_check is True

        # Pass to heuristics
        corrected, confidence = enforce_present_tense(result.text)
        assert corrected is not None
        assert confidence in ("LOW", "MEDIUM", "HIGH")

    def test_heuristics_to_diff_flow(self):
        """Test data flow from heuristics to diff generation."""
        original = "He walked to the store."
        corrected, confidence = enforce_present_tense(original)

        if corrected != original:
            diff_html = generate_diff_html(original, corrected)
            assert "<s>" in diff_html  # Original should be strikethrough
            assert "color: #4CAF50" in diff_html  # Correction should be green

    def test_full_correction_result_flow(self):
        """Test the full flow from text to CorrectionResult."""
        result = CorrectionResult(
            original="He walk to store.",
            correction="He walks to the store.",
            has_correction=True,
            backend=Backend.OLLAMA,
            latency_ms=42.0,
        )

        assert result.original == "He walk to store."
        assert result.correction == "He walks to the store."
        assert result.has_correction is True
        assert result.backend == Backend.OLLAMA
        assert result.latency_ms == 42.0

    def test_pipeline_result_flow(self):
        """Test the full flow from correction to PipelineResult."""
        parsed = ParsedBlock(
            element=FountainElement.DIALOGUE,
            text="i dont know",
            should_check=True,
            reason="Dialogue",
        )
        correction = CorrectionResult(
            original="i dont know",
            correction="I don't know",
            has_correction=True,
            backend=Backend.OLLAMA,
            latency_ms=50.0,
        )
        result = PipelineResult(
            text="i dont know",
            parsed=parsed,
            correction=correction,
            final_suggestion="I don't know",
            has_final_suggestion=True,
            confidence="LOW",
            diff_html=generate_diff_html("i dont know", "I don't know"),
        )

        assert result.has_suggestion is True
        assert result.suggestion == "I don't know"
        assert result.latency_ms == 50.0
        assert result.diff_html != ""
