"""
controller.py — GramWrite Central Orchestration Pipeline
Watcher → Parser → Heuristics → Engine → UI

Manages async processing, deduplication, debounce logic, queue management,
sensitivity settings, strict mode, and lifecycle management.

Architecture:
    - Async-first design with proper error propagation
    - Hash-based deduplication with TTL cache
    - Configurable debounce intervals
    - Priority queue with overflow handling
    - Sensitivity-aware processing (Low/Medium/High)
    - Strict mode for comprehensive grammar checking
    - Clean lifecycle management (startup/shutdown)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .engine import GramEngine, CorrectionResult
from .fountain_parser import FountainParser, ParsedBlock, FountainElement
from .watcher import Watcher
from .heuristics import calculate_confidence, generate_diff_html, enforce_present_tense

logger = logging.getLogger(__name__)


# ─── Enums ───────────────────────────────────────────────────────────────────

class SensitivityLevel(Enum):
    """Sensitivity levels for grammar checking."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Priority(Enum):
    """Priority levels for queue items."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    """Single cache entry with TTL support."""
    result: "PipelineResult"
    created_at: float
    ttl_seconds: float

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


@dataclass
class QueueItem:
    """Item in the processing queue with priority."""
    text: str
    priority: Priority
    enqueued_at: float = field(default_factory=time.monotonic)
    hash_value: str = ""

    def __post_init__(self):
        if not self.hash_value:
            self.hash_value = hashlib.sha256(self.text.encode()).hexdigest()


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
    processing_time_ms: float = 0.0
    was_cached: bool = False
    error: Optional[str] = None

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
        return self.processing_time_ms


class Controller:
    """
    Orchestrates the full GramWrite pipeline.

    Responsibilities:
    - Receive text from Watcher
    - Route through FountainParser (skip non-dialogue/action)
    - Apply heuristics before LLM processing
    - Send eligible text to GramEngine
    - Deduplicate identical requests with TTL cache
    - Emit results to UI callback
    - Respect sensitivity settings and strict mode
    - Manage async queue with priority handling
    - Handle graceful lifecycle management

    Pipeline Flow:
        Watcher → Parser → Heuristics → Engine → Result Processing → UI
    """

    # Default configuration values
    DEFAULT_DEBOUNCE_SECONDS = 2.0
    DEFAULT_CACHE_TTL = 300.0  # 5 minutes
    DEFAULT_CACHE_MAX_SIZE = 100
    DEFAULT_QUEUE_MAX_SIZE = 5
    DEFAULT_INFERENCE_TIMEOUT = 10.0  # seconds
    DEFAULT_MIN_LENGTHS = {
        SensitivityLevel.LOW: 30,
        SensitivityLevel.MEDIUM: 15,
        SensitivityLevel.HIGH: 5,
    }
    DEFAULT_CONFIDENCE_THRESHOLDS = {
        SensitivityLevel.LOW: 0.8,
        SensitivityLevel.MEDIUM: 0.6,
        SensitivityLevel.HIGH: 0.3,
    }

    def __init__(
        self,
        config: dict,
        on_result: Callable[[PipelineResult], None],
    ):
        self.config = config
        self.on_result = on_result

        # Core components
        self._engine = GramEngine(config)
        self._parser = FountainParser()
        self._watcher = Watcher(config, self._on_text_received)

        # Pipeline state
        self._processing = False
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._debounce_task: Optional[asyncio.Task] = None

        # Queue management
        self._queue_max_size = int(config.get("queue_max_size", self.DEFAULT_QUEUE_MAX_SIZE))
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=self._queue_max_size)
        self._overflow_count = 0

        # Deduplication cache
        self._cache_ttl = float(config.get("cache_ttl", self.DEFAULT_CACHE_TTL))
        self._cache_max_size = int(config.get("cache_max_size", self.DEFAULT_CACHE_MAX_SIZE))
        self._result_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._last_hash: str = ""

        # Debounce configuration
        self._debounce_seconds = float(config.get("debounce_seconds", self.DEFAULT_DEBOUNCE_SECONDS))
        self._pending_text: Optional[str] = None
        self._pending_priority: Priority = Priority.NORMAL

        # Sensitivity settings
        self._sensitivity = SensitivityLevel(config.get("sensitivity", "medium").lower())
        self._min_length = self.DEFAULT_MIN_LENGTHS[self._sensitivity]
        self._confidence_threshold = self.DEFAULT_CONFIDENCE_THRESHOLDS[self._sensitivity]

        # Strict mode
        self._strict_mode = config.get("strict_mode", True)

        # Timeout configuration
        self._inference_timeout = float(config.get("inference_timeout", self.DEFAULT_INFERENCE_TIMEOUT))

        logger.info(
            "Controller initialized: sensitivity=%s strict=%s debounce=%.1fs cache_ttl=%.0fs",
            self._sensitivity.value,
            self._strict_mode,
            self._debounce_seconds,
            self._cache_ttl,
        )

    # ─── Lifecycle Management ─────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the controller and all sub-systems.

        Sequence:
        1. Detect grammar backend
        2. Start background worker
        3. Start watcher (blocks until stopped)
        """
        logger.info("Controller starting…")
        self._running = True

        try:
            # Detect backend early
            backend = await self._engine.detect_backend()
            logger.info("Grammar backend: %s", backend.value)

            # Start background worker
            self._worker_task = asyncio.create_task(self._process_worker())
            logger.info("Worker task started")

            # Start watcher (blocks until stopped)
            await self._watcher.run()

        except asyncio.CancelledError:
            logger.info("Controller start cancelled")
            raise
        except Exception as e:
            logger.exception("Controller start failed: %s", e)
            self._running = False
            raise

    async def stop(self) -> None:
        """
        Graceful shutdown of all components.

        Sequence:
        1. Stop watcher
        2. Cancel debounce task
        3. Cancel worker task
        4. Close engine resources
        5. Clear cache
        """
        logger.info("Controller stopping…")
        self._running = False

        # Stop watcher
        try:
            self._watcher.stop()
        except Exception as e:
            logger.warning("Error stopping watcher: %s", e)

        # Cancel debounce task
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            try:
                await self._debounce_task
            except asyncio.CancelledError:
                pass

        # Cancel worker task
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        # Close engine resources
        try:
            await self._engine.close()
        except Exception as e:
            logger.warning("Error closing engine: %s", e)

        # Clear cache
        self._result_cache.clear()
        self._pending_text = None

        logger.info("Controller stopped")

    async def apply_config(self, config: dict) -> None:
        """
        Apply runtime configuration changes.

        Updates:
        - Sensitivity level and thresholds
        - Strict mode
        - Debounce interval
        - Cache settings
        - Engine configuration
        """
        updated_config = dict(config)
        self.config.clear()
        self.config.update(updated_config)

        # Update strict mode
        self._strict_mode = self.config.get("strict_mode", True)

        # Update sensitivity
        sensitivity_str = self.config.get("sensitivity", "medium").lower()
        try:
            self._sensitivity = SensitivityLevel(sensitivity_str)
        except ValueError:
            logger.warning("Invalid sensitivity '%s', defaulting to medium", sensitivity_str)
            self._sensitivity = SensitivityLevel.MEDIUM

        self._min_length = self.DEFAULT_MIN_LENGTHS[self._sensitivity]
        self._confidence_threshold = self.DEFAULT_CONFIDENCE_THRESHOLDS[self._sensitivity]

        # Update debounce
        self._debounce_seconds = float(self.config.get("debounce_seconds", self.DEFAULT_DEBOUNCE_SECONDS))
        self._watcher.debounce_secs = self._debounce_seconds

        # Update cache settings
        self._cache_ttl = float(self.config.get("cache_ttl", self.DEFAULT_CACHE_TTL))
        self._cache_max_size = int(self.config.get("cache_max_size", self.DEFAULT_CACHE_MAX_SIZE))

        # Update engine
        await self._engine.apply_config(self.config)

        logger.info(
            "Runtime config updated: backend=%s model=%s sensitivity=%s strict=%s debounce=%.1fs",
            self.config.get("backend", "auto"),
            self.config.get("model", "qwen3.5:0.8b"),
            self._sensitivity.value,
            self._strict_mode,
            self._debounce_seconds,
        )

    # ─── Text Reception & Debounce ────────────────────────────────────────

    async def _on_text_received(self, text: str) -> None:
        """
        Called by Watcher after debounce. Handles deduplication and enqueuing.

        Flow:
        1. Check cache for existing result
        2. Skip if text too short for sensitivity level
        3. Skip if identical to last processed text
        4. Enqueue with normal priority
        """
        text_hash = self._hash(text)

        # Check cache first
        cached = self._get_from_cache(text_hash)
        if cached:
            logger.debug("Cache hit for text (hash=%s)", text_hash[:8])
            cached.was_cached = True
            self.on_result(cached)
            return

        # Skip too-short segments based on sensitivity
        stripped_len = len(text.strip())
        if stripped_len < self._min_length:
            logger.debug("Skipping short text (len=%d < min=%d)", stripped_len, self._min_length)
            return

        # Skip identical text
        if text_hash == self._last_hash:
            logger.debug("Skipping duplicate text (hash match)")
            return

        # Enqueue text
        try:
            item = QueueItem(text=text, priority=Priority.NORMAL, hash_value=text_hash)
            self._queue.put_nowait(item)
            logger.debug("Text enqueued (len=%d, queue_size=%d)", len(text), self._queue.qsize())
        except asyncio.QueueFull:
            self._overflow_count += 1
            logger.warning(
                "Queue full — dropping text (overflow_count=%d)",
                self._overflow_count,
            )

    async def _on_text_received_with_debounce(self, text: str, priority: Priority = Priority.NORMAL) -> None:
        """
        Internal method for debounced text reception.

        Cancels previous debounce task and starts a new one.
        This prevents rapid-fire processing during burst typing.
        """
        # Cancel existing debounce task
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        # Store pending text
        self._pending_text = text
        self._pending_priority = priority

        # Start new debounce task
        self._debounce_task = asyncio.create_task(self._debounce_handler())

    async def _debounce_handler(self) -> None:
        """
        Wait for debounce interval, then process pending text.
        If cancelled before timeout, the text is discarded.
        """
        try:
            await asyncio.sleep(self._debounce_seconds)
            if self._pending_text:
                await self._on_text_received(self._pending_text)
                self._pending_text = None
        except asyncio.CancelledError:
            logger.debug("Debounce cancelled (new text received)")
        except Exception as e:
            logger.exception("Debounce handler error: %s", e)

    # ─── Queue Management ─────────────────────────────────────────────────

    async def _process_worker(self) -> None:
        """
        Background coroutine that processes queued text segments.

        Lifecycle:
        - Runs continuously while controller is active
        - Processes items from queue
        - Handles errors gracefully
        - Emits results to UI callback

        Error Handling:
        - Catches and logs all exceptions
        - Continues processing after errors
        - Properly marks tasks as done
        """
        logger.info("Worker started")
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                self._processing = True

                start_time = time.monotonic()
                result = await self._process_text(item.text, item.hash_value)
                result.processing_time_ms = (time.monotonic() - start_time) * 1000

                # Emit to UI
                self.on_result(result)

            except asyncio.TimeoutError:
                # No items in queue, continue waiting
                continue
            except asyncio.CancelledError:
                logger.info("Worker cancelled")
                break
            except Exception as e:
                logger.exception("Worker error: %s", e)
            finally:
                self._processing = False
                try:
                    self._queue.task_done()
                except ValueError:
                    pass

        logger.info("Worker stopped")

    async def enqueue_text(self, text: str, priority: Priority = Priority.NORMAL) -> bool:
        """
        Public method to enqueue text for processing.

        Returns True if successfully enqueued, False if queue is full.
        """
        if not self._running:
            logger.warning("Cannot enqueue text: controller not running")
            return False

        text_hash = self._hash(text)
        item = QueueItem(text=text, priority=priority, hash_value=text_hash)

        try:
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            self._overflow_count += 1
            return False

    def get_queue_status(self) -> dict[str, Any]:
        """Return current queue status for monitoring."""
        return {
            "size": self._queue.qsize(),
            "max_size": self._queue_maxsize,
            "overflow_count": self._overflow_count,
            "is_processing": self._processing,
            "is_running": self._running,
        }

    # ─── Core Processing Pipeline ─────────────────────────────────────────

    async def _process_text(self, text: str, text_hash: str) -> PipelineResult:
        """
        Process a single text segment through the full pipeline.

        Pipeline:
        1. Parse Fountain syntax
        2. Apply strict mode filtering
        3. Run heuristics (action lines)
        4. Build context-aware prompt
        5. Call engine for correction
        6. Process and combine results
        7. Generate diff HTML
        8. Cache result

        Returns:
            PipelineResult with final suggestion and metadata
        """
        self._last_hash = text_hash

        # Step 1: Parse Fountain element type
        parsed = self._parser.classify_raw_extract(text)
        logger.debug(
            "Parsed: type=%s should_check=%s reason=%s",
            parsed.element.value,
            parsed.should_check,
            parsed.reason,
        )

        # Step 2: Apply strict mode filtering
        if self._strict_mode and not self._should_check_strict(parsed):
            return self._create_skip_result(text, parsed, "Strict mode — skipped")

        # Step 3: Check if text should be processed
        if not parsed.should_check or not parsed.text:
            return self._create_skip_result(text, parsed, "Not eligible for checking")

        # Step 4: Apply heuristics for action lines
        text_to_check = parsed.text
        heuristic_confidence = "LOW"

        if parsed.element == FountainElement.ACTION:
            text_to_check, heuristic_confidence = enforce_present_tense(text_to_check)
            logger.debug("Heuristics applied: confidence=%s", heuristic_confidence)

        # Step 5: Build context-aware prompt
        prompt_text = self._build_prompt(parsed.element, text_to_check)

        # Step 6: Call engine with timeout
        correction = await self._call_engine_with_timeout(prompt_text)

        # Step 7: Process results
        final_suggestion, has_final_suggestion, confidence = self._process_correction_results(
            original=parsed.text,
            text_to_check=text_to_check,
            correction=correction,
            heuristic_confidence=heuristic_confidence,
        )

        # Step 8: Generate diff HTML
        diff_html = ""
        if has_final_suggestion and final_suggestion:
            diff_html = generate_diff_html(parsed.text, final_suggestion)

        # Step 9: Create result
        result = PipelineResult(
            text=text,
            parsed=parsed,
            correction=correction,
            final_suggestion=final_suggestion,
            has_final_suggestion=has_final_suggestion,
            confidence=confidence,
            diff_html=diff_html,
        )

        # Step 10: Cache result
        self._add_to_cache(text_hash, result)

        return result

    async def _call_engine_with_timeout(self, text: str) -> Optional[CorrectionResult]:
        """
        Call engine with configurable timeout.

        Returns CorrectionResult or None on timeout/error.
        """
        try:
            return await asyncio.wait_for(
                self._engine.correct(text),
                timeout=self._inference_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Engine inference timed out after %.1fs", self._inference_timeout)
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=self._engine.backend,
                latency_ms=self._inference_timeout * 1000,
                error="Inference timeout",
            )
        except Exception as e:
            logger.exception("Engine call failed: %s", e)
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=self._engine.backend,
                latency_ms=0,
                error=str(e),
            )

    def _process_correction_results(
        self,
        original: str,
        text_to_check: str,
        correction: Optional[CorrectionResult],
        heuristic_confidence: str,
    ) -> tuple[Optional[str], bool, str]:
        """
        Combine heuristics and LLM results into final suggestion.

        Logic:
        - If LLM suggests correction, use it
        - If heuristics made changes but LLM didn't, use heuristic result
        - Calculate confidence based on changes
        - Apply confidence threshold filtering

        Returns:
            (final_suggestion, has_suggestion, confidence)
        """
        final_suggestion: Optional[str] = None
        has_final_suggestion = False
        confidence = heuristic_confidence

        if correction and correction.error:
            logger.warning("Engine error: %s", correction.error)

        if correction and correction.has_correction and correction.correction:
            # LLM provided a correction
            final_suggestion = correction.correction
            has_final_suggestion = True

            # Calculate LLM confidence
            llm_confidence = calculate_confidence(original, final_suggestion)

            # Use higher confidence between heuristic and LLM
            confidence = self._higher_confidence(heuristic_confidence, llm_confidence)

            logger.info(
                "LLM correction (%.0fms): %r → %r",
                correction.latency_ms,
                original[:60],
                final_suggestion,
            )

        elif text_to_check != original:
            # Heuristics made changes but LLM didn't suggest more
            final_suggestion = text_to_check
            has_final_suggestion = True
            confidence = heuristic_confidence

            logger.info(
                "Heuristic correction: %r → %r",
                original[:60],
                final_suggestion,
            )

        # Apply confidence threshold filtering
        if has_final_suggestion and final_suggestion:
            if not self._meets_confidence_threshold(confidence):
                logger.debug(
                    "Suggestion filtered by confidence threshold: %s < %.2f",
                    confidence,
                    self._confidence_threshold,
                )
                # Keep suggestion but mark as low confidence
                confidence = "LOW"

        return final_suggestion, has_final_suggestion, confidence

    def _should_check_strict(self, parsed: ParsedBlock) -> bool:
        """
        Determine if block should be checked in strict mode.

        Strict mode checks:
        - Dialogue (always)
        - Action lines (always)
        - Parentheticals (sometimes)

        Non-strict mode only checks dialogue.
        """
        if not self._strict_mode:
            return parsed.element in (FountainElement.DIALOGUE,)

        return parsed.element in (
            FountainElement.ACTION,
            FountainElement.DIALOGUE,
            FountainElement.PARENTHETICAL,
        )

    def _meets_confidence_threshold(self, confidence: str) -> bool:
        """Check if confidence level meets current sensitivity threshold."""
        confidence_values = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.8}
        return confidence_values.get(confidence, 0.0) >= self._confidence_threshold

    @staticmethod
    def _higher_confidence(conf1: str, conf2: str) -> str:
        """Return the higher of two confidence levels."""
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        return conf1 if order.get(conf1, 0) >= order.get(conf2, 0) else conf2

    # ─── Prompt Building ──────────────────────────────────────────────────

    def _build_prompt(self, element: FountainElement, text: str) -> str:
        """
        Build context-appropriate prompt for the engine.

        Different element types get different instructions:
        - Dialogue: Standard grammar correction
        - Action: Lenient about fragments, preserve style
        - Other: Pass through unchanged
        """
        if element == FountainElement.DIALOGUE:
            return text
        elif element == FountainElement.ACTION:
            return (
                f"[ACTION LINE — stylistic fragments are intentional]\n{text}"
            )
        elif element == FountainElement.PARENTHETICAL:
            return f"[PARENTHETICAL — minimal correction only]\n{text}"
        return text

    # ─── Cache Management ─────────────────────────────────────────────────

    def _get_from_cache(self, text_hash: str) -> Optional[PipelineResult]:
        """
        Retrieve result from cache if available and not expired.

        Implements LRU eviction when cache is full.
        """
        if text_hash not in self._result_cache:
            return None

        entry = self._result_cache[text_hash]
        if entry.is_expired:
            # Remove expired entry
            del self._result_cache[text_hash]
            logger.debug("Cache entry expired (hash=%s)", text_hash[:8])
            return None

        # Move to end (most recently used)
        self._result_cache.move_to_end(text_hash)
        return entry.result

    def _add_to_cache(self, text_hash: str, result: PipelineResult) -> None:
        """
        Add result to cache with TTL.

        Evicts oldest entries if cache is full.
        """
        # Evict expired entries first
        self._evict_expired()

        # Evict oldest if at capacity
        if len(self._result_cache) >= self._cache_max_size:
            self._result_cache.popitem(last=False)
            logger.debug("Cache evicted oldest entry (size=%d)", len(self._result_cache))

        self._result_cache[text_hash] = CacheEntry(
            result=result,
            created_at=time.monotonic(),
            ttl_seconds=self._cache_ttl,
        )

    def _evict_expired(self) -> None:
        """Remove all expired entries from cache."""
        expired_keys = [
            key for key, entry in self._result_cache.items() if entry.is_expired
        ]
        for key in expired_keys:
            del self._result_cache[key]

        if expired_keys:
            logger.debug("Evicted %d expired cache entries", len(expired_keys))

    def clear_cache(self) -> None:
        """Clear all cached results."""
        self._result_cache.clear()
        logger.info("Cache cleared")

    def get_cache_status(self) -> dict[str, Any]:
        """Return current cache status for monitoring."""
        self._evict_expired()
        return {
            "size": len(self._result_cache),
            "max_size": self._cache_max_size,
            "ttl_seconds": self._cache_ttl,
        }

    # ─── Result Helpers ───────────────────────────────────────────────────

    def _create_skip_result(
        self, text: str, parsed: ParsedBlock, reason: str
    ) -> PipelineResult:
        """Create a result indicating text was skipped."""
        return PipelineResult(
            text=text,
            parsed=parsed,
            correction=None,
            final_suggestion=None,
            has_final_suggestion=False,
            confidence="LOW",
            diff_html="",
            error=reason,
        )

    # ─── Context Management ───────────────────────────────────────────────

    def notify_window_changed(self) -> None:
        """
        Call when the active window/document changes.

        Resets parser context and cache to prevent
        carrying over state between documents.
        """
        self._parser.reset_context()
        self._last_hash = ""
        self.clear_cache()
        logger.debug("Parser context reset (window change)")

    # ─── Utility Methods ──────────────────────────────────────────────────

    @staticmethod
    def _hash(text: str) -> str:
        """Generate SHA-256 hash of text for deduplication."""
        return hashlib.sha256(text.encode()).hexdigest()

    # ─── Properties ───────────────────────────────────────────────────────

    @property
    def is_processing(self) -> bool:
        """Whether the controller is currently processing text."""
        return self._processing

    @property
    def is_running(self) -> bool:
        """Whether the controller is running."""
        return self._running

    @property
    def engine(self) -> GramEngine:
        """Access to the underlying grammar engine."""
        return self._engine

    @property
    def sensitivity(self) -> SensitivityLevel:
        """Current sensitivity level."""
        return self._sensitivity

    @property
    def strict_mode(self) -> bool:
        """Whether strict mode is enabled."""
        return self._strict_mode

    @property
    def debounce_seconds(self) -> float:
        """Current debounce interval in seconds."""
        return self._debounce_seconds
