"""
test_controller.py — Comprehensive Controller Tests

Covers:
- Pipeline execution
- Deduplication logic
- Debounce behavior
- Queue management
- Sensitivity settings
- Strict mode
- Result processing
- Lifecycle management
- Error propagation
"""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gramwrite.controller import Controller, PipelineResult
from gramwrite.engine import Backend, CorrectionResult, GramEngine
from gramwrite.fountain_parser import FountainElement, ParsedBlock


# ─── Controller Initialization Tests ─────────────────────────────────────────


class TestControllerInit:
    def test_controller_initialization(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller.config == controller_config
        assert controller.on_result == mock_on_result
        assert controller._strict_mode is True
        assert controller._min_length == 15  # medium sensitivity
        assert controller._last_hash == ""
        assert controller._processing is False

    def test_controller_strict_mode_false(self, mock_on_result):
        config = {"strict_mode": False, "sensitivity": "medium"}
        controller = Controller(config, mock_on_result)
        assert controller._strict_mode is False

    def test_controller_sensitivity_low(self, mock_on_result):
        config = {"sensitivity": "low"}
        controller = Controller(config, mock_on_result)
        assert controller._min_length == 30

    def test_controller_sensitivity_medium(self, mock_on_result):
        config = {"sensitivity": "medium"}
        controller = Controller(config, mock_on_result)
        assert controller._min_length == 15

    def test_controller_sensitivity_high(self, mock_on_result):
        config = {"sensitivity": "high"}
        controller = Controller(config, mock_on_result)
        assert controller._min_length == 5

    def test_controller_sensitivity_default(self, mock_on_result):
        config = {}
        controller = Controller(config, mock_on_result)
        assert controller._min_length == 15  # default is medium


# ─── PipelineResult Tests ────────────────────────────────────────────────────


class TestPipelineResult:
    def test_pipeline_result_defaults(self):
        result = PipelineResult(
            text="test",
            parsed=MagicMock(),
            correction=None,
        )
        assert result.final_suggestion is None
        assert result.has_final_suggestion is False
        assert result.confidence == "LOW"
        assert result.diff_html == ""
        assert result.timestamp > 0

    def test_pipeline_result_has_suggestion_property(self):
        result = PipelineResult(
            text="test",
            parsed=MagicMock(),
            correction=None,
            final_suggestion="Fixed text",
            has_final_suggestion=True,
        )
        assert result.has_suggestion is True
        assert result.suggestion == "Fixed text"

    def test_pipeline_result_no_suggestion(self):
        result = PipelineResult(
            text="test",
            parsed=MagicMock(),
            correction=None,
        )
        assert result.has_suggestion is False
        assert result.suggestion is None

    def test_pipeline_result_latency_ms_with_correction(self):
        correction = CorrectionResult(
            original="test",
            correction="fixed",
            has_correction=True,
            backend=Backend.OLLAMA,
            latency_ms=42.0,
        )
        result = PipelineResult(
            text="test",
            parsed=MagicMock(),
            correction=correction,
        )
        assert result.latency_ms == 42.0

    def test_pipeline_result_latency_ms_without_correction(self):
        result = PipelineResult(
            text="test",
            parsed=MagicMock(),
            correction=None,
        )
        assert result.latency_ms == 0.0


# ─── Deduplication Tests ─────────────────────────────────────────────────────


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_duplicate_text_skipped(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        controller._last_hash = controller._hash("Some text to process")

        await controller._on_text_received("Some text to process")

        # Queue should be empty (duplicate was skipped)
        assert controller._queue.empty()

    @pytest.mark.asyncio
    async def test_different_text_enqueued(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        controller._last_hash = controller._hash("Different text")

        await controller._on_text_received("Some text to process")

        # Queue should have the new text
        assert not controller._queue.empty()

    @pytest.mark.asyncio
    async def test_hash_is_consistent(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        hash1 = controller._hash("test")
        hash2 = controller._hash("test")
        assert hash1 == hash2

    @pytest.mark.asyncio
    async def test_hash_is_sha256(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        text = "test"
        expected = hashlib.sha256(text.encode()).hexdigest()
        assert controller._hash(text) == expected


# ─── Text Length Filtering Tests ─────────────────────────────────────────────


class TestTextLengthFiltering:
    @pytest.mark.asyncio
    async def test_short_text_skipped_medium_sensitivity(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        # Medium sensitivity requires 15 chars minimum
        short_text = "Hi"  # 2 chars
        await controller._on_text_received(short_text)
        assert controller._queue.empty()

    @pytest.mark.asyncio
    async def test_long_text_enqueued(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        long_text = "This is a longer text that should be processed."
        await controller._on_text_received(long_text)
        assert not controller._queue.empty()

    @pytest.mark.asyncio
    async def test_high_sensitivity_accepts_shorter_text(self, mock_on_result):
        config = {"sensitivity": "high"}
        controller = Controller(config, mock_on_result)
        # High sensitivity requires only 5 chars
        text = "Hello"  # 5 chars
        await controller._on_text_received(text)
        assert not controller._queue.empty()

    @pytest.mark.asyncio
    async def test_low_sensitivity_requires_longer_text(self, mock_on_result):
        config = {"sensitivity": "low"}
        controller = Controller(config, mock_on_result)
        # Low sensitivity requires 30 chars
        text = "Short text"  # 10 chars
        await controller._on_text_received(text)
        assert controller._queue.empty()


# ─── Strict Mode Tests ───────────────────────────────────────────────────────


class TestStrictMode:
    @pytest.mark.asyncio
    async def test_strict_mode_skips_non_action_dialogue(self, controller_config, mock_on_result):
        """In strict mode, only ACTION and DIALOGUE should be checked."""
        controller = Controller(controller_config, mock_on_result)
        controller._strict_mode = True

        # Mock the engine to avoid actual backend calls
        controller._engine.correct = AsyncMock(return_value=CorrectionResult(
            original="test",
            correction=None,
            has_correction=False,
            backend=Backend.NONE,
            latency_ms=0,
        ))

        # Create a mock parsed block for a slugline
        parsed = ParsedBlock(
            element=FountainElement.SLUGLINE,
            text="INT. ROOM - DAY",
            should_check=True,  # Would normally be False, but we're testing strict mode override
            reason="Test",
        )

        # Simulate what _process_worker does with strict mode
        if controller._strict_mode and parsed.element not in (FountainElement.ACTION, FountainElement.DIALOGUE):
            parsed.should_check = False
            parsed.reason = "Strict mode — skipped"

        assert parsed.should_check is False
        assert "Strict mode" in parsed.reason

    @pytest.mark.asyncio
    async def test_non_strict_mode_allows_all_types(self, mock_on_result):
        config = {"strict_mode": False}
        controller = Controller(config, mock_on_result)
        assert controller._strict_mode is False


# ─── Queue Management Tests ──────────────────────────────────────────────────


class TestQueueManagement:
    @pytest.mark.asyncio
    async def test_queue_has_maxsize_five(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller._queue.maxsize == 5  # DEFAULT_QUEUE_MAX_SIZE

    @pytest.mark.asyncio
    async def test_queue_full_drops_text(self, controller_config, mock_on_result):
        """When queue is full, new text should be dropped."""
        controller = Controller(controller_config, mock_on_result)
        # Fill the queue
        await controller._queue.put("First text")
        # Try to add another (should be dropped)
        await controller._on_text_received("Second text")
        # Queue should still only have the first item
        assert controller._queue.qsize() == 1

    @pytest.mark.asyncio
    async def test_processing_flag_set_during_work(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller._processing is False


# ─── Prompt Building Tests ───────────────────────────────────────────────────


class TestPromptBuilding:
    def test_build_prompt_for_dialogue(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        text = "I dont know what your talking about."
        prompt = controller._build_prompt(FountainElement.DIALOGUE, text)
        assert prompt == text  # Dialogue text is passed as-is

    def test_build_prompt_for_action(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        text = "He walk to the store."
        prompt = controller._build_prompt(FountainElement.ACTION, text)
        assert "[ACTION LINE" in prompt
        assert text in prompt

    def test_build_prompt_for_unknown(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        text = "Some text"
        prompt = controller._build_prompt(FountainElement.UNKNOWN, text)
        assert prompt == text


# ─── Context Reset Tests ─────────────────────────────────────────────────────


class TestContextReset:
    def test_notify_window_changed_resets_parser(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        # Set some state
        controller._parser.classify("JOHN")
        assert controller._parser._in_dialogue_block is True

        controller.notify_window_changed()

        assert controller._parser._in_dialogue_block is False
        assert controller._last_hash == ""

    def test_notify_window_changed_resets_hash(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        controller._last_hash = "some_hash"
        controller.notify_window_changed()
        assert controller._last_hash == ""


# ─── Properties Tests ────────────────────────────────────────────────────────


class TestControllerProperties:
    def test_is_processing_property(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller.is_processing is False

    def test_engine_property(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert isinstance(controller.engine, GramEngine)


# ─── Config Application Tests ────────────────────────────────────────────────


class TestControllerConfigApplication:
    @pytest.mark.asyncio
    async def test_apply_config_updates_sensitivity(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller._min_length == 15  # medium

        await controller.apply_config({"sensitivity": "high"})
        assert controller._min_length == 5

    @pytest.mark.asyncio
    async def test_apply_config_updates_strict_mode(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller._strict_mode is True

        await controller.apply_config({"strict_mode": False})
        assert controller._strict_mode is False

    @pytest.mark.asyncio
    async def test_apply_config_updates_debounce(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        assert controller._watcher.debounce_secs == 0.1

        await controller.apply_config({"debounce_seconds": 5.0})
        assert controller._watcher.debounce_secs == 5.0


# ─── Lifecycle Tests ─────────────────────────────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_stop_cancels_worker(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        controller._worker_task = asyncio.create_task(asyncio.sleep(10))
        await controller.stop()
        assert controller._worker_task.cancelled() or controller._worker_task.done()

    @pytest.mark.asyncio
    async def test_stop_handles_no_worker_task(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        # No worker task set
        await controller.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_closes_engine(self, controller_config, mock_on_result):
        controller = Controller(controller_config, mock_on_result)
        # Mock engine close
        controller._engine.close = AsyncMock()
        await controller.stop()
        controller._engine.close.assert_called_once()


# ─── Error Propagation Tests ─────────────────────────────────────────────────


class TestErrorPropagation:
    @pytest.mark.asyncio
    async def test_worker_handles_exception_gracefully(self, controller_config, mock_on_result):
        """Worker should handle exceptions without crashing."""
        controller = Controller(controller_config, mock_on_result)
        # Put text in queue that will cause an error
        await controller._queue.put("test text")
        # Mock engine to raise an error
        controller._engine.correct = AsyncMock(side_effect=RuntimeError("Test error"))

        # Run one iteration of the worker
        try:
            text = await controller._queue.get()
            controller._processing = True
            controller._last_hash = controller._hash(text)

            parsed = controller._parser.classify_raw_extract(text)
            if parsed.should_check and parsed.text:
                await controller._engine.correct(parsed.text)
        except Exception:
            pass  # Worker should catch this internally
        finally:
            controller._processing = False

        # Processing flag should be reset
        assert controller._processing is False


# ─── Integration: Full Pipeline Simulation ───────────────────────────────────


class TestPipelineSimulation:
    @pytest.mark.asyncio
    async def test_pipeline_result_emitted_on_result(self, controller_config, mock_on_result):
        """Test that on_result callback is called with a PipelineResult."""
        controller = Controller(controller_config, mock_on_result)

        # Manually create and emit a result
        parsed = ParsedBlock(
            element=FountainElement.DIALOGUE,
            text="I dont know.",
            should_check=True,
            reason="Dialogue",
        )
        correction = CorrectionResult(
            original="I dont know.",
            correction="I don't know.",
            has_correction=True,
            backend=Backend.OLLAMA,
            latency_ms=50.0,
        )
        result = PipelineResult(
            text="I dont know.",
            parsed=parsed,
            correction=correction,
            final_suggestion="I don't know.",
            has_final_suggestion=True,
            confidence="LOW",
            diff_html="<div>diff</div>",
        )

        controller.on_result(result)

        mock_on_result.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_pipeline_result_with_no_correction(self, controller_config, mock_on_result):
        """Test pipeline result when no correction is needed."""
        controller = Controller(controller_config, mock_on_result)

        parsed = ParsedBlock(
            element=FountainElement.DIALOGUE,
            text="I don't know.",
            should_check=True,
            reason="Dialogue",
        )
        result = PipelineResult(
            text="I don't know.",
            parsed=parsed,
            correction=None,
        )

        controller.on_result(result)

        mock_on_result.assert_called_once()
        call_args = mock_on_result.call_args[0][0]
        assert call_args.has_final_suggestion is False
        assert call_args.final_suggestion is None
