"""
engine.py — GramWrite LLM Backend Connector
Supports Ollama and LM Studio. Auto-detects active backend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

OLLAMA_BASE = "http://localhost:11434"
LMSTUDIO_BASE = "http://localhost:1234"

SYSTEM_PROMPT_DEFAULT = (
    "You are a Hollywood script doctor.\n"
    "Correct grammar and spelling only.\n"
    "Do NOT rewrite stylistic fragments.\n"
    "Do NOT modify ALL CAPS character names or sluglines.\n"
    "Preserve pacing and rhythm of screenplay writing.\n"
    "If the text has no errors, respond with exactly: NO_CORRECTION\n"
    "If there is an error, respond with ONLY the corrected sentence. "
    "Do not explain. Do not add commentary."
)


class Backend(Enum):
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    NONE = "none"


@dataclass
class CorrectionResult:
    original: str
    correction: Optional[str]
    has_correction: bool
    backend: Backend
    latency_ms: float
    error: Optional[str] = None


class GramEngine:
    """
    Manages connection to local LLM backend.
    Auto-detects Ollama or LM Studio on startup.
    Thread-safe via asyncio.
    """

    def __init__(self, config: dict):
        self.config = config
        self.backend: Backend = Backend.NONE
        self.model: str = config.get("model", "qwen3.5:0.8b")
        self.system_prompt: str = config.get("system_prompt", SYSTEM_PROMPT_DEFAULT)
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=3)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def detect_backend(self) -> Backend:
        """
        Auto-detect which backend is running.
        Prefers user-configured backend, falls back to auto-detect.
        """
        preferred = self.config.get("backend", "auto")
        session = await self._get_session()

        if preferred == "ollama":
            if await self._ping_ollama(session):
                self.backend = Backend.OLLAMA
                logger.info("Backend: Ollama (configured)")
                return self.backend

        if preferred == "lmstudio":
            if await self._ping_lmstudio(session):
                self.backend = Backend.LMSTUDIO
                logger.info("Backend: LM Studio (configured)")
                return self.backend

        # Auto-detect: try both
        if await self._ping_ollama(session):
            self.backend = Backend.OLLAMA
            logger.info("Backend: Ollama (auto-detected)")
        elif await self._ping_lmstudio(session):
            self.backend = Backend.LMSTUDIO
            logger.info("Backend: LM Studio (auto-detected)")
        else:
            self.backend = Backend.NONE
            logger.warning("No backend detected. Ensure Ollama or LM Studio is running.")

        return self.backend

    async def _ping_ollama(self, session: aiohttp.ClientSession) -> bool:
        try:
            async with session.get(f"{OLLAMA_BASE}/api/tags") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def _ping_lmstudio(self, session: aiohttp.ClientSession) -> bool:
        try:
            async with session.get(f"{LMSTUDIO_BASE}/v1/models") as resp:
                return resp.status == 200
        except Exception:
            return False

    async def correct(self, text: str) -> CorrectionResult:
        """
        Send text to active backend for grammar correction.
        Returns structured CorrectionResult.
        """
        async with self._lock:
            if self.backend == Backend.NONE:
                await self.detect_backend()

        if self.backend == Backend.NONE:
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=Backend.NONE,
                latency_ms=0,
                error="No LLM backend available",
            )

        t0 = time.monotonic()
        try:
            if self.backend == Backend.OLLAMA:
                raw = await self._call_ollama(text)
            else:
                raw = await self._call_lmstudio(text)

            latency_ms = (time.monotonic() - t0) * 1000
            correction = self._parse_response(raw, text)

            return CorrectionResult(
                original=text,
                correction=correction,
                has_correction=correction is not None,
                backend=self.backend,
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error("LLM inference timed out after %.0fms", latency_ms)
            return CorrectionResult(
                original=text,
                correction=None,
                has_correction=False,
                backend=self.backend,
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
                backend=self.backend,
                latency_ms=latency_ms,
                error=str(exc),
            )

    async def _call_ollama(self, text: str) -> str:
        session = await self._get_session()
        payload = {
            "model": self.model,
            "prompt": text,
            "system": self.system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "top_p": 0.9,
                "num_predict": 256,
            },
        }
        async with session.post(
            f"{OLLAMA_BASE}/api/generate", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("response", "").strip()

    async def _call_lmstudio(self, text: str) -> str:
        session = await self._get_session()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
            "stream": False,
        }
        async with session.post(
            f"{LMSTUDIO_BASE}/v1/chat/completions", json=payload
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()

    def _parse_response(self, raw: str, original: str) -> Optional[str]:
        """
        Parse LLM response. Returns None if no correction needed.
        Validates that model actually changed something meaningful.
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

    async def list_ollama_models(self) -> list[str]:
        """Return available Ollama model names."""
        try:
            session = await self._get_session()
            async with session.get(f"{OLLAMA_BASE}/api/tags") as resp:
                data = await resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def list_lmstudio_models(self) -> list[str]:
        """Return available LM Studio model names."""
        try:
            session = await self._get_session()
            async with session.get(f"{LMSTUDIO_BASE}/v1/models") as resp:
                data = await resp.json()
                return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
