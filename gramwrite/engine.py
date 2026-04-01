"""
engine.py — GramWrite Grammar Backend Engine

Provides a clean abstraction layer over multiple local grammar backends:
- Ollama (local LLM server)
- LM Studio (local LLM server)
- Harper (Node.js-based grammar checker)
- Apple Foundation Models (macOS native)

Architecture:
- GrammarBackend: Abstract base class defining the backend interface
- Concrete backends inherit from GrammarBackend
- GramEngine: Orchestrates backend selection, detection, and correction
- Factory pattern for backend instantiation
- All backends return standardized CorrectionResult

Performance targets:
- Inference < 100ms (Harper/Foundation Models)
- Connection pooling for HTTP backends
- Proper timeout management
- Cached backend detection results
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import aiohttp

from .foundation_models import (
    FOUNDATION_BACKEND_KEY,
    FoundationModelsBridge,
)
from .harper import (
    HARPER_BACKEND_KEY,
    HARPER_MODEL_ID,
    HarperBridge,
)

logger = logging.getLogger(__name__)

# Default base URLs for HTTP backends
OLLAMA_BASE = "http://localhost:11434"
LMSTUDIO_BASE = "http://localhost:1234"

# System prompt for LLM-based backends
SYSTEM_PROMPT_DEFAULT = (
    "You are a Hollywood script doctor.\n"
    "Identify the language of the source text.\n"
    "Correct grammar and spelling only in the SAME language.\n"
    "Do NOT translate.\n"
    "Do NOT rewrite stylistic fragments.\n"
    "Do NOT modify ALL CAPS character names or sluglines.\n"
    "Preserve pacing and rhythm of screenplay writing.\n"
    "Keep corrections minimal.\n"
    "If the text has no errors, respond with exactly: NO_CORRECTION\n"
    "If there is an error, respond with ONLY the corrected sentence. "
    "Do not explain. Do not add commentary."
)


class Backend(Enum):
    """Supported grammar backend identifiers."""
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    FOUNDATION_MODELS = FOUNDATION_BACKEND_KEY
    HARPER = HARPER_BACKEND_KEY
    NONE = "none"


@dataclass
class CorrectionResult:
    """
    Standardized result from any grammar backend.

    Attributes:
        original: The original input text
        correction: The corrected text, or None if no correction needed
        has_correction: Whether a correction is available
        backend: Which backend produced this result
        latency_ms: Time taken for the correction in milliseconds
        error: Error message if the backend failed, None otherwise
    """
    original: str
    correction: Optional[str]
    has_correction: bool
    backend: Backend
    latency_ms: float
    error: Optional[str] = None


@dataclass
class BackendStatus:
    """
    Status information for a grammar backend.

    Attributes:
        available: Whether the backend is ready to use
        reason: Human-readable explanation if not available
        model: Current model identifier (if applicable)
        models: List of available models (if applicable)
    """
    available: bool
    reason: Optional[str] = None
    model: Optional[str] = None
    models: list[str] = field(default_factory=list)


class GrammarBackend(ABC):
    """
    Abstract base class for all grammar backends.

    All concrete backends must implement:
    - correct(): Perform grammar correction
    - is_available(): Check if backend is ready
    - get_status(): Get detailed status information
    - list_models(): List available models (if applicable)

    Backends should be async-safe and handle their own connection management.
    """

    @abstractmethod
    async def correct(self, text: str, **kwargs: Any) -> str:
        """
        Correct grammar in the given text.

        Args:
            text: The text to correct
            **kwargs: Backend-specific options (e.g., system_prompt for LLMs)

        Returns:
            Corrected text, or "NO_CORRECTION" if no changes needed

        Raises:
            RuntimeError: If the backend is not available or fails
        """
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check if this backend is available and ready to use.

        Returns:
            True if the backend can process corrections
        """
        ...

    @abstractmethod
    async def get_status(self) -> BackendStatus:
        """
        Get detailed status information for this backend.

        Returns:
            BackendStatus with availability and model information
        """
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """
        List available models for this backend.

        Returns:
            List of model identifiers, or empty list if not applicable
        """
        ...

    @property
    @abstractmethod
    def backend_type(self) -> Backend:
        """Return the Backend enum value for this backend."""
        ...


class OllamaBackend(GrammarBackend):
    """
    Ollama backend for local LLM-based grammar correction.

    Connects to a local Ollama server via HTTP API.
    Supports connection pooling, configurable timeouts, and model selection.
    """

    def __init__(
        self,
        base_url: str = OLLAMA_BASE,
        model: str = "qwen3.5:0.8b",
        timeout_total: float = 15.0,
        timeout_connect: float = 3.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_total = timeout_total
        self._timeout_connect = timeout_connect
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self._cached_available: Optional[bool] = None
        self._cached_at = 0.0

    @property
    def backend_type(self) -> Backend:
        return Backend.OLLAMA

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self._timeout_total,
                connect=self._timeout_connect,
            )
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
        return self._session

    async def close(self):
        """Close the HTTP session and release resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def is_available(self) -> bool:
        """Check if Ollama server is running and responding."""
        now = time.monotonic()
        if self._cached_available is not None and now - self._cached_at < 5:
            return self._cached_available

        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/api/tags") as resp:
                available = resp.status == 200
                self._cached_available = available
                self._cached_at = now
                return available
        except Exception:
            self._cached_available = False
            self._cached_at = now
            return False

    async def get_status(self) -> BackendStatus:
        """Get Ollama backend status including available models."""
        if not await self.is_available():
            return BackendStatus(
                available=False,
                reason="Ollama server is not responding",
                model=self._model,
            )

        models = await self.list_models()
        return BackendStatus(
            available=True,
            model=self._model,
            models=models,
        )

    async def list_models(self) -> list[str]:
        """List models available in the Ollama server."""
        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    async def correct(self, text: str, **kwargs: Any) -> str:
        """
        Send text to Ollama for grammar correction.

        Args:
            text: The text to correct
            **kwargs: Optional system_prompt override

        Returns:
            Corrected text or "NO_CORRECTION"
        """
        session = await self._get_session()
        system_prompt = kwargs.get("system_prompt", SYSTEM_PROMPT_DEFAULT)

        payload = {
            "model": self._model,
            "prompt": text,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "num_predict": 256,
            },
        }

        async with session.post(
            f"{self._base_url}/api/generate", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("response", "").strip()


class LMStudioBackend(GrammarBackend):
    """
    LM Studio backend for local LLM-based grammar correction.

    Connects to a local LM Studio server via OpenAI-compatible API.
    Supports connection pooling, configurable timeouts, and model selection.
    """

    def __init__(
        self,
        base_url: str = LMSTUDIO_BASE,
        model: str = "qwen3.5:0.8b",
        timeout_total: float = 15.0,
        timeout_connect: float = 3.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_total = timeout_total
        self._timeout_connect = timeout_connect
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self._cached_available: Optional[bool] = None
        self._cached_at = 0.0

    @property
    def backend_type(self) -> Backend:
        return Backend.LMSTUDIO

    @property
    def model(self) -> str:
        return self._model

    @model.setter
    def model(self, value: str):
        self._model = value

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(
                total=self._timeout_total,
                connect=self._timeout_connect,
            )
            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            )
        return self._session

    async def close(self):
        """Close the HTTP session and release resources."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def is_available(self) -> bool:
        """Check if LM Studio server is running and responding."""
        now = time.monotonic()
        if self._cached_available is not None and now - self._cached_at < 5:
            return self._cached_available

        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/v1/models") as resp:
                available = resp.status == 200
                self._cached_available = available
                self._cached_at = now
                return available
        except Exception:
            self._cached_available = False
            self._cached_at = now
            return False

    async def get_status(self) -> BackendStatus:
        """Get LM Studio backend status including available models."""
        if not await self.is_available():
            return BackendStatus(
                available=False,
                reason="LM Studio server is not responding",
                model=self._model,
            )

        models = await self.list_models()
        return BackendStatus(
            available=True,
            model=self._model,
            models=models,
        )

    async def list_models(self) -> list[str]:
        """List models available in the LM Studio server."""
        try:
            session = await self._get_session()
            async with session.get(f"{self._base_url}/v1/models") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["id"] for m in data.get("data", [])]
        except Exception:
            pass
        return []

    async def correct(self, text: str, **kwargs: Any) -> str:
        """
        Send text to LM Studio for grammar correction.

        Args:
            text: The text to correct
            **kwargs: Optional system_prompt override

        Returns:
            Corrected text or "NO_CORRECTION"
        """
        session = await self._get_session()
        system_prompt = kwargs.get("system_prompt", SYSTEM_PROMPT_DEFAULT)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
            "stream": False,
        }

        async with session.post(
            f"{self._base_url}/v1/chat/completions", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()


class HarperBackend(GrammarBackend):
    """
    Harper backend for fast, rule-based grammar checking.

    Uses a Node.js bridge to harper.js for local grammar correction.
    Typically faster than LLM-based backends (<50ms target).
    """

    def __init__(self, bridge: Optional[HarperBridge] = None):
        self._bridge = bridge or HarperBridge()

    @property
    def backend_type(self) -> Backend:
        return Backend.HARPER

    async def is_available(self) -> bool:
        """Check if Harper Node helper is available."""
        status = await self._bridge.status()
        return status.usable

    async def get_status(self) -> BackendStatus:
        """Get Harper backend status."""
        status = await self._bridge.status()
        return BackendStatus(
            available=status.usable,
            reason=status.reason,
            model=HARPER_MODEL_ID,
            models=[HARPER_MODEL_ID] if status.usable else [],
        )

    async def list_models(self) -> list[str]:
        """List available Harper models (always returns the single Harper model)."""
        return await self._bridge.list_models()

    async def correct(self, text: str, **kwargs: Any) -> str:
        """
        Send text to Harper for grammar correction.

        Args:
            text: The text to correct
            **kwargs: Ignored (Harper doesn't use system prompts)

        Returns:
            Corrected text or "NO_CORRECTION"
        """
        # Strip any metadata prefix that may have been added
        clean_text = text
        if text.startswith("[ACTION LINE"):
            _, _, clean_text = text.partition("\n")

        return await self._bridge.correct(clean_text)


class FoundationModelsBackend(GrammarBackend):
    """
    Apple Foundation Models backend for macOS native grammar correction.

    Uses a Swift helper binary to access Apple's on-device language model.
    Provides native performance on macOS 15.1+.
    """

    def __init__(self, bridge: Optional[FoundationModelsBridge] = None):
        self._bridge = bridge or FoundationModelsBridge()

    @property
    def backend_type(self) -> Backend:
        return Backend.FOUNDATION_MODELS

    async def is_available(self) -> bool:
        """Check if Apple Foundation Models are available."""
        status = await self._bridge.status()
        return status.usable

    async def get_status(self) -> BackendStatus:
        """Get Foundation Models backend status."""
        status = await self._bridge.status()
        from .foundation_models import FOUNDATION_MODEL_ID
        return BackendStatus(
            available=status.usable,
            reason=status.reason,
            model=FOUNDATION_MODEL_ID,
            models=[FOUNDATION_MODEL_ID] if status.usable else [],
        )

    async def list_models(self) -> list[str]:
        """List available Foundation Models (always returns the single model)."""
        return await self._bridge.list_models()

    async def correct(self, text: str, **kwargs: Any) -> str:
        """
        Send text to Apple Foundation Models for grammar correction.

        Args:
            text: The text to correct
            **kwargs: Optional system_prompt (passed as instructions)

        Returns:
            Corrected text or "NO_CORRECTION"
        """
        instructions = kwargs.get("system_prompt", SYSTEM_PROMPT_DEFAULT)
        return await self._bridge.correct(text, instructions)


class BackendFactory:
    """
    Factory for creating grammar backend instances.

    Creates backends based on configuration and availability.
    Caches created instances for reuse.
    """

    def __init__(self, config: dict):
        self._config = config
        self._backends: dict[Backend, GrammarBackend] = {}
        self._foundation_bridge: Optional[FoundationModelsBridge] = None
        self._harper_bridge: Optional[HarperBridge] = None

    def get_backend(self, backend_type: Backend) -> GrammarBackend:
        """
        Get or create a backend instance.

        Args:
            backend_type: The type of backend to create

        Returns:
            GrammarBackend instance

        Raises:
            ValueError: If backend type is not supported
        """
        if backend_type in self._backends:
            return self._backends[backend_type]

        backend = self._create_backend(backend_type)
        self._backends[backend_type] = backend
        return backend

    def _create_backend(self, backend_type: Backend) -> GrammarBackend:
        """Create a new backend instance based on type."""
        model = self._config.get("model", "qwen3.5:0.8b")

        if backend_type == Backend.OLLAMA:
            return OllamaBackend(model=model)
        elif backend_type == Backend.LMSTUDIO:
            return LMStudioBackend(model=model)
        elif backend_type == Backend.HARPER:
            if self._harper_bridge is None:
                self._harper_bridge = HarperBridge()
            return HarperBackend(bridge=self._harper_bridge)
        elif backend_type == Backend.FOUNDATION_MODELS:
            if self._foundation_bridge is None:
                self._foundation_bridge = FoundationModelsBridge()
            return FoundationModelsBackend(bridge=self._foundation_bridge)
        else:
            raise ValueError(f"Unknown backend type: {backend_type}")

    async def close_all(self):
        """Close all backend resources."""
        for backend in self._backends.values():
            if isinstance(backend, (OllamaBackend, LMStudioBackend)):
                await backend.close()
        self._backends.clear()


class GramEngine:
    """
    Central grammar engine that manages backend selection and correction.

    Responsibilities:
    - Auto-detect available backends
    - Route correction requests to the active backend
    - Provide standardized CorrectionResult from all backends
    - Manage backend lifecycle and configuration

    Usage:
        engine = GramEngine(config)
        await engine.detect_backend()
        result = await engine.correct("Some text with errors")
    """

    # Preferred backend order for auto-detection
    DETECTION_ORDER = [
        Backend.HARPER,
        Backend.FOUNDATION_MODELS,
        Backend.OLLAMA,
        Backend.LMSTUDIO,
    ]

    def __init__(self, config: dict):
        self._config = config
        self._factory = BackendFactory(config)
        self._active_backend: Optional[GrammarBackend] = None
        self._backend_type: Backend = Backend.NONE
        self._system_prompt: str = config.get("system_prompt", SYSTEM_PROMPT_DEFAULT)
        self._lock = asyncio.Lock()
        self._detection_cache: Optional[Backend] = None
        self._detection_cached_at = 0.0

    @property
    def backend(self) -> Backend:
        """Return the currently active backend type."""
        return self._backend_type

    @property
    def system_prompt(self) -> str:
        """Return the current system prompt."""
        return self._system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str):
        self._system_prompt = value

    async def apply_config(self, config: dict):
        """
        Apply new configuration and reset backend detection.

        Args:
            config: New configuration dictionary
        """
        async with self._lock:
            self._config = config
            self._system_prompt = config.get("system_prompt", SYSTEM_PROMPT_DEFAULT)
            self._active_backend = None
            self._backend_type = Backend.NONE
            self._detection_cache = None

    async def detect_backend(self, force_refresh: bool = False) -> Backend:
        """
        Auto-detect and select the best available backend.

        Detection order:
        1. User-configured backend (if specified and available)
        2. Auto-detect in preference order (Harper > Foundation > Ollama > LM Studio)

        Args:
            force_refresh: Force re-detection even if cached

        Returns:
            The detected Backend enum value
        """
        # Return cached result if available
        now = time.monotonic()
        if (
            not force_refresh
            and self._detection_cache is not None
            and now - self._detection_cached_at < 10
            and self._detection_cache != Backend.NONE
        ):
            self._backend_type = self._detection_cache
            return self._backend_type

        preferred = self._config.get("backend", "auto")

        # Try user-configured backend first
        if preferred != "auto":
            backend_type = self._resolve_backend_enum(preferred)
            if backend_type and backend_type != Backend.NONE:
                backend = self._factory.get_backend(backend_type)
                if await backend.is_available():
                    self._active_backend = backend
                    self._backend_type = backend_type
                    self._detection_cache = backend_type
                    self._detection_cached_at = now
                    logger.info("Backend: %s (configured)", backend_type.value)
                    return self._backend_type
                else:
                    logger.warning(
                        "Configured backend %s is not available", backend_type.value
                    )

        # Auto-detect in preference order
        for backend_type in self.DETECTION_ORDER:
            try:
                backend = self._factory.get_backend(backend_type)
                if await backend.is_available():
                    self._active_backend = backend
                    self._backend_type = backend_type
                    self._detection_cache = backend_type
                    self._detection_cached_at = now
                    logger.info("Backend: %s (auto-detected)", backend_type.value)
                    return self._backend_type
            except Exception as exc:
                logger.debug("Backend %s detection failed: %s", backend_type.value, exc)

        # No backend available
        self._backend_type = Backend.NONE
        self._detection_cache = Backend.NONE
        self._detection_cached_at = now
        logger.warning("No grammar backend available")
        return Backend.NONE

    def _resolve_backend_enum(self, name: str) -> Optional[Backend]:
        """Resolve a backend name string to a Backend enum."""
        mapping = {
            "ollama": Backend.OLLAMA,
            "lmstudio": Backend.LMSTUDIO,
            "lm_studio": Backend.LMSTUDIO,
            FOUNDATION_BACKEND_KEY: Backend.FOUNDATION_MODELS,
            "foundation_models": Backend.FOUNDATION_MODELS,
            "apple": Backend.FOUNDATION_MODELS,
            HARPER_BACKEND_KEY: Backend.HARPER,
            "harper": Backend.HARPER,
        }
        return mapping.get(name.lower())

    async def correct(self, text: str) -> CorrectionResult:
        """
        Correct grammar in the given text using the active backend.

        If no backend is active, attempts auto-detection first.

        Args:
            text: The text to correct

        Returns:
            CorrectionResult with correction details
        """
        async with self._lock:
            if self._backend_type == Backend.NONE:
                await self.detect_backend()

        if self._backend_type == Backend.NONE or self._active_backend is None:
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=Backend.NONE,
                latency_ms=0,
                error="No local grammar backend available",
            )

        t0 = time.monotonic()
        try:
            raw = await self._active_backend.correct(
                text, system_prompt=self._system_prompt
            )
            latency_ms = (time.monotonic() - t0) * 1000
            correction = self._parse_response(raw, text)

            return CorrectionResult(
                original=text,
                correction=correction,
                has_correction=correction is not None,
                backend=self._backend_type,
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error("LLM inference timed out after %.0fms", latency_ms)
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=self._backend_type,
                latency_ms=latency_ms,
                error="Inference timeout",
            )
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.exception("Engine error: %s", exc)
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=self._backend_type,
                latency_ms=latency_ms,
                error=str(exc),
            )

    def _parse_response(self, raw: str, original: str) -> Optional[str]:
        """
        Parse backend response and determine if correction is needed.

        Returns None if:
        - Response is "NO_CORRECTION"
        - Response matches original text
        - Response is too short or empty

        Args:
            raw: Raw response from backend
            original: Original input text

        Returns:
            Corrected text or None
        """
        cleaned = raw.strip()

        # Explicit no-correction signal
        if cleaned.upper() == "NO_CORRECTION":
            return None

        # Model returned same text
        if cleaned.lower() == original.lower():
            return None

        # Too short to be a real correction
        if len(cleaned) < 3:
            return None

        # Model returned nothing useful
        if not cleaned:
            return None

        return cleaned

    async def get_backend_status(self) -> dict[Backend, BackendStatus]:
        """
        Get status for all supported backends.

        Returns:
            Dictionary mapping Backend enum to BackendStatus
        """
        statuses = {}
        for backend_type in [
            Backend.OLLAMA,
            Backend.LMSTUDIO,
            Backend.HARPER,
            Backend.FOUNDATION_MODELS,
        ]:
            try:
                backend = self._factory.get_backend(backend_type)
                statuses[backend_type] = await backend.get_status()
            except Exception as exc:
                statuses[backend_type] = BackendStatus(
                    available=False,
                    reason=str(exc),
                )
        return statuses

    async def list_models(self, backend_type: Optional[Backend] = None) -> list[str]:
        """
        List available models for a backend.

        Args:
            backend_type: Specific backend to query, or None for active backend

        Returns:
            List of model identifiers
        """
        if backend_type is None:
            backend_type = self._backend_type

        if backend_type == Backend.NONE:
            return []

        try:
            backend = self._factory.get_backend(backend_type)
            return await backend.list_models()
        except Exception:
            return []

    async def close(self):
        """Release all backend resources."""
        await self._factory.close_all()
