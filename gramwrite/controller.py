"""
controller.py — GramWrite Central Orchestration Pipeline
Watcher → Parser → Engine → UI

Manages async processing, deduplication, and debounce logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .engine import GramEngine, CorrectionResult
from .fountain_parser import FountainParser, ParsedBlock, FountainElement
from .watcher import Watcher
from .heuristics import calculate_confidence, generate_diff_html, enforce_present_tense

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Unified result object passed to the UI layer."""
    text: str
    parsed: ParsedBlock
    correction: Optional[CorrectionResult]
    final_suggestion: Optional[str] = None
    has_final_suggestion: bool = False
    confidence: str = "LOW"
    diff_html: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def has_suggestion(self) -> bool:
        return self.has_final_suggestion

    @property
    def suggestion(self) -> Optional[str]:
        return self.final_suggestion

    @property
    def latency_ms(self) -> float:
        if self.correction:
            return self.correction.latency_ms
        return 0.0


class Controller:
    """
    Orchestrates the full GramWrite pipeline.

    Responsibilities:
    - Receive text from Watcher
    - Route through FountainParser (skip non-dialogue/action)
    - Send eligible text to GramEngine
    - Deduplicate identical requests
    - Emit results to UI callback
    - Respect sensitivity settings
    """

    def __init__(
        self,
        config: dict,
        on_result: Callable[[PipelineResult], None],
    ):
        self.config = config
        self.on_result = on_result

        self._engine = GramEngine(config)
        self._parser = FountainParser()
        self._watcher = Watcher(config, self._on_text_received)

        self._last_hash: str = ""
        self._processing = False
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._worker_task: Optional[asyncio.Task] = None

        self._strict_mode = config.get("strict_mode", True)
        sensitivity = config.get("sensitivity", "medium")
        self._min_length = {"low": 30, "medium": 15, "high": 5}.get(sensitivity, 15)

    async def start(self):
        """Start the controller and all sub-systems."""
        logger.info("Controller starting…")

        # Detect backend early
        backend = await self._engine.detect_backend()
        logger.info("Grammar backend: %s", backend.value)

        # Start background worker
        self._worker_task = asyncio.create_task(self._process_worker())

        # Start watcher (blocks until stopped)
        await self._watcher.run()

    async def stop(self):
        """Graceful shutdown."""
        self._watcher.stop()
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        await self._engine.close()
        logger.info("Controller stopped")

    async def _on_text_received(self, text: str):
        """
        Called by Watcher after debounce. Enqueues text for processing.
        Drops if queue is full (previous job still running).
        """
        text_hash = self._hash(text)

        # Skip identical text
        if text_hash == self._last_hash:
            logger.debug("Skipping duplicate text (hash match)")
            return

        # Skip too-short segments based on sensitivity
        if len(text.strip()) < self._min_length:
            logger.debug("Skipping short text (len=%d)", len(text.strip()))
            return

        try:
            self._queue.put_nowait(text)
            logger.debug("Text enqueued (len=%d)", len(text))
        except asyncio.QueueFull:
            logger.debug("Queue full — dropping text (inference in progress)")

    async def _process_worker(self):
        """
        Background coroutine that processes queued text segments.
        Runs engine inference, emits results to UI.
        """
        while True:
            try:
                text = await self._queue.get()
                self._processing = True

                text_hash = self._hash(text)
                self._last_hash = text_hash

                # Parse Fountain element type
                parsed = self._parser.classify_raw_extract(text)
                logger.debug(
                    "Parsed: type=%s should_check=%s",
                    parsed.element.value,
                    parsed.should_check,
                )

                # Apply strict mode
                if self._strict_mode and parsed.element not in (FountainElement.ACTION, FountainElement.DIALOGUE):
                    parsed.should_check = False
                    parsed.reason = "Strict mode — skipped"

                correction: Optional[CorrectionResult] = None
                final_suggestion: Optional[str] = None
                has_final_suggestion = False
                confidence = "LOW"
                diff_html = ""

                if parsed.should_check and parsed.text:
                    text_to_check = parsed.text
                    # 1. Action Line Heuristics
                    if parsed.element == FountainElement.ACTION:
                        text_to_check, heuristic_conf = enforce_present_tense(text_to_check)
                        if text_to_check != parsed.text:
                            confidence = heuristic_conf
                            
                    # 2. Build context-aware prompt
                    prompt_text = self._build_prompt(parsed.element, text_to_check)
                    correction = await self._engine.correct(prompt_text)

                    if correction.error:
                        logger.warning("Engine error: %s", correction.error)
                    
                    # 3. Determine final suggestion
                    if correction.has_correction and correction.correction is not None:
                        final_suggestion = correction.correction
                        has_final_suggestion = True
                        calc_conf = calculate_confidence(parsed.text, final_suggestion)
                        # Promote confidence if LLM did a major fix, otherwise keep heuristic
                        if confidence == "LOW" or calc_conf == "HIGH":
                            confidence = calc_conf
                            
                        logger.info("Correction found (%.0fms): %r → %r", correction.latency_ms, parsed.text[:60], final_suggestion)
                    elif text_to_check != parsed.text:
                        # LLM didn't suggest more changes, but our heuristic did
                        final_suggestion = text_to_check
                        has_final_suggestion = True
                        logger.info("Heuristic correction applied: %r → %r", parsed.text[:60], final_suggestion)

                    # 4. Generate Diff HTML
                    if has_final_suggestion and final_suggestion:
                        diff_html = generate_diff_html(parsed.text, final_suggestion)

                result = PipelineResult(
                    text=text,
                    parsed=parsed,
                    correction=correction,
                    final_suggestion=final_suggestion,
                    has_final_suggestion=has_final_suggestion,
                    confidence=confidence,
                    diff_html=diff_html
                )

                # Emit to UI (always, so UI can update idle state)
                self.on_result(result)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Worker error: %s", e)
            finally:
                self._processing = False
                try:
                    self._queue.task_done()
                except ValueError:
                    pass

    def _build_prompt(self, element: FountainElement, text: str) -> str:
        """
        Build context-appropriate prompt for the engine.
        Action lines get a different instruction prefix.
        """
        if element == FountainElement.DIALOGUE:
            return text
        elif element == FountainElement.ACTION:
            # Action lines: be extra lenient about fragments
            return (
                f"[ACTION LINE — stylistic fragments are intentional]\n{text}"
            )
        return text

    def notify_window_changed(self):
        """
        Call when the active window/document changes.
        Resets parser context so dialogue state is not carried over.
        """
        self._parser.reset_context()
        self._last_hash = ""
        logger.debug("Parser context reset (window change)")

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    @property
    def is_processing(self) -> bool:
        return self._processing

    @property
    def engine(self) -> GramEngine:
        return self._engine
