"""
test_engine.py — Comprehensive GramEngine Tests

Covers:
- Backend detection (Ollama, LM Studio, Harper, Foundation Models)
- Ollama connection (mocked)
- LM Studio connection (mocked)
- Harper integration (mocked)
- Foundation Models (mocked)
- Correction results
- Error handling
- Timeout handling
- Latency measurement
- Config application
- Model listing
- Response parsing
- Backend factory
- GrammarBackend abstract interface
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import aiohttp
import pytest
from aioresponses import aioresponses

from gramwrite.engine import (
    Backend,
    CorrectionResult,
    GramEngine,
    OLLAMA_BASE,
    LMSTUDIO_BASE,
    SYSTEM_PROMPT_DEFAULT,
    BackendStatus,
    GrammarBackend,
    OllamaBackend,
    LMStudioBackend,
    HarperBackend,
    FoundationModelsBackend,
    BackendFactory,
)
from gramwrite.foundation_models import FoundationModelsStatus
from gramwrite.harper import HarperStatus


# ─── Engine Initialization Tests ─────────────────────────────────────────────


class TestEngineInit:
    def test_default_config(self):
        engine = GramEngine({})
        assert engine._backend_type == Backend.NONE
        assert engine._system_prompt == SYSTEM_PROMPT_DEFAULT

    def test_custom_config(self):
        engine = GramEngine({
            "backend": "ollama",
            "model": "custom-model",
            "system_prompt": "Custom prompt",
        })
        assert engine._system_prompt == "Custom prompt"

    def test_backend_starts_as_none(self):
        engine = GramEngine({"backend": "ollama"})
        assert engine.backend == Backend.NONE

    def test_backend_property(self):
        engine = GramEngine({})
        assert engine.backend == Backend.NONE

    def test_system_prompt_property(self):
        engine = GramEngine({"system_prompt": "Test prompt"})
        assert engine.system_prompt == "Test prompt"

    def test_system_prompt_setter(self):
        engine = GramEngine({})
        engine.system_prompt = "New prompt"
        assert engine.system_prompt == "New prompt"


# ─── Backend Detection Tests ─────────────────────────────────────────────────


class TestBackendDetection:
    @pytest.mark.asyncio
    async def test_detects_ollama_when_configured(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)
            backend = await engine.detect_backend()
            assert backend == Backend.OLLAMA

    @pytest.mark.asyncio
    async def test_detects_lmstudio_when_configured(self):
        engine = GramEngine({"backend": "lmstudio", "model": "test"})
        with aioresponses() as m:
            m.get(f"{LMSTUDIO_BASE}/v1/models", payload={"data": []}, status=200)
            backend = await engine.detect_backend()
            assert backend == Backend.LMSTUDIO

    @pytest.mark.asyncio
    async def test_ollama_not_detected(self):
        engine = GramEngine({"backend": "ollama", "model": "test"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", exception=aiohttp.ClientError())
            backend = await engine.detect_backend()
            assert backend == Backend.NONE

    @pytest.mark.asyncio
    async def test_auto_detect_falls_back_to_none(self):
        engine = GramEngine({"backend": "auto", "model": "test"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", exception=aiohttp.ClientError())
            m.get(f"{LMSTUDIO_BASE}/v1/models", exception=aiohttp.ClientError())
            backend = await engine.detect_backend()
            assert backend == Backend.NONE

    @pytest.mark.asyncio
    async def test_detects_foundation_models_backend(self):
        engine = GramEngine({
            "backend": "foundation_models",
            "model": "apple.foundation",
            "system_prompt": "Correct grammar only.",
        })

        async def fake_status(force_refresh: bool = False):
            return FoundationModelsStatus(
                supported=True,
                available=True,
                helper_path=Path("/tmp/gramwrite-foundation-models"),
            )

        engine._factory._foundation_bridge = MagicMock()
        engine._factory._foundation_bridge.status = fake_status
        backend = await engine.detect_backend()
        assert backend == Backend.FOUNDATION_MODELS

    @pytest.mark.asyncio
    async def test_foundation_models_unavailable(self):
        engine = GramEngine({
            "backend": "foundation_models",
            "model": "apple.foundation",
        })

        async def fake_status(force_refresh: bool = False):
            return FoundationModelsStatus(
                supported=True,
                available=False,
                reason="Not available",
            )

        engine._factory._foundation_bridge = MagicMock()
        engine._factory._foundation_bridge.status = fake_status
        backend = await engine.detect_backend()
        assert backend == Backend.NONE

    @pytest.mark.asyncio
    async def test_detects_harper_backend(self):
        engine = GramEngine({
            "backend": "harper",
            "model": "harper.english",
            "system_prompt": "Correct grammar only.",
        })

        async def fake_status(force_refresh: bool = False):
            return HarperStatus(
                supported=True,
                available=True,
                helper_path=Path("/tmp/gramwrite-harper.mjs"),
                node_path="/usr/bin/node",
            )

        engine._factory._harper_bridge = MagicMock()
        engine._factory._harper_bridge.status = fake_status
        backend = await engine.detect_backend()
        assert backend == Backend.HARPER

    @pytest.mark.asyncio
    async def test_harper_unavailable(self):
        engine = GramEngine({
            "backend": "harper",
            "model": "harper.english",
        })

        async def fake_status(force_refresh: bool = False):
            return HarperStatus(
                supported=True,
                available=False,
                reason="Node not found",
            )

        engine._factory._harper_bridge = MagicMock()
        engine._factory._harper_bridge.status = fake_status
        backend = await engine.detect_backend()
        assert backend == Backend.NONE

    @pytest.mark.asyncio
    async def test_detection_caching(self):
        """Backend detection should cache results."""
        engine = GramEngine({"backend": "ollama", "model": "test"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)
            backend1 = await engine.detect_backend()
            assert backend1 == Backend.OLLAMA
            backend2 = await engine.detect_backend()
            assert backend2 == Backend.OLLAMA

    @pytest.mark.asyncio
    async def test_force_refresh_detection(self):
        """Force refresh should bypass cache."""
        engine = GramEngine({"backend": "ollama", "model": "test"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)
            backend = await engine.detect_backend(force_refresh=True)
            assert backend == Backend.OLLAMA

    @pytest.mark.asyncio
    async def test_resolve_backend_enum(self):
        engine = GramEngine({})
        assert engine._resolve_backend_enum("ollama") == Backend.OLLAMA
        assert engine._resolve_backend_enum("lmstudio") == Backend.LMSTUDIO
        assert engine._resolve_backend_enum("foundation_models") == Backend.FOUNDATION_MODELS
        assert engine._resolve_backend_enum("harper") == Backend.HARPER
        assert engine._resolve_backend_enum("unknown") is None


# ─── Correction Tests ────────────────────────────────────────────────────────


class TestCorrection:
    @pytest.mark.asyncio
    async def test_successful_correction(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "He walks to the store."},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("He walk to store.")
            assert result.correction == "He walks to the store."
            assert result.has_correction is True
            assert result.backend == Backend.OLLAMA

    @pytest.mark.asyncio
    async def test_no_correction_when_no_error(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "NO_CORRECTION"},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("He walks to the store.")
            assert result.correction is None
            assert result.has_correction is False

    @pytest.mark.asyncio
    async def test_connection_error(self):
        engine = GramEngine({"backend": "ollama", "model": "test"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                exception=aiohttp.ClientConnectionError("Failed to connect"),
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("He walk to store.")
            assert result.correction is None
            assert result.has_correction is False
            assert "Failed to connect" in result.error

    @pytest.mark.asyncio
    async def test_no_backend_available(self):
        engine = GramEngine({"backend": "ollama", "model": "test"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", exception=aiohttp.ClientError())

            result = await engine.correct("Some text.")
            assert result.correction is None
            assert result.has_correction is False
            assert result.backend == Backend.NONE
            assert result.error is not None

    @pytest.mark.asyncio
    async def test_correction_measures_latency(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "Corrected text."},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("Some text.")
            assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_correction_result_has_original(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "Corrected."},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            original = "Original text."
            result = await engine.correct(original)
            assert result.original == original

    @pytest.mark.asyncio
    async def test_foundation_models_correction(self):
        engine = GramEngine({
            "backend": "foundation_models",
            "model": "apple.foundation",
            "system_prompt": "Correct grammar only.",
        })

        async def fake_status(force_refresh: bool = False):
            return FoundationModelsStatus(
                supported=True,
                available=True,
                helper_path=Path("/tmp/gramwrite-foundation-models"),
            )

        async def fake_correct(text: str, instructions: str):
            assert text == "He walk to the store."
            assert "Correct grammar only." in instructions
            return "He walks to the store."

        mock_bridge = MagicMock()
        mock_bridge.status = fake_status
        mock_bridge.correct = fake_correct
        engine._factory._foundation_bridge = mock_bridge
        engine._active_backend = engine._factory.get_backend(Backend.FOUNDATION_MODELS)
        engine._backend_type = Backend.FOUNDATION_MODELS

        result = await engine.correct("He walk to the store.")
        assert result.backend == Backend.FOUNDATION_MODELS
        assert result.has_correction is True
        assert result.correction == "He walks to the store."

    @pytest.mark.asyncio
    async def test_harper_correction(self):
        engine = GramEngine({
            "backend": "harper",
            "model": "harper.english",
            "system_prompt": "Ignored by Harper.",
        })

        async def fake_status(force_refresh: bool = False):
            return HarperStatus(
                supported=True,
                available=True,
                helper_path=Path("/tmp/gramwrite-harper.mjs"),
                node_path="/usr/bin/node",
            )

        async def fake_correct(text: str):
            assert text == "He walk to the store."
            return "He walks to the store."

        mock_bridge = MagicMock()
        mock_bridge.status = fake_status
        mock_bridge.correct = fake_correct
        engine._factory._harper_bridge = mock_bridge
        engine._active_backend = engine._factory.get_backend(Backend.HARPER)
        engine._backend_type = Backend.HARPER

        result = await engine.correct("He walk to the store.")
        assert result.backend == Backend.HARPER
        assert result.has_correction is True
        assert result.correction == "He walks to the store."

    @pytest.mark.asyncio
    async def test_harper_strips_action_prefix(self):
        engine = GramEngine({
            "backend": "harper",
            "model": "harper.english",
            "system_prompt": "Ignored by Harper.",
        })

        async def fake_status(force_refresh: bool = False):
            return HarperStatus(
                supported=True,
                available=True,
                helper_path=Path("/tmp/gramwrite-harper.mjs"),
                node_path="/usr/bin/node",
            )

        async def fake_correct(text: str):
            assert text == "He walk to the store."
            return "He walks to the store."

        mock_bridge = MagicMock()
        mock_bridge.status = fake_status
        mock_bridge.correct = fake_correct
        engine._factory._harper_bridge = mock_bridge
        engine._active_backend = engine._factory.get_backend(Backend.HARPER)
        engine._backend_type = Backend.HARPER

        result = await engine.correct(
            "[ACTION LINE — stylistic fragments are intentional]\nHe walk to the store."
        )
        assert result.backend == Backend.HARPER
        assert result.has_correction is True
        assert result.correction == "He walks to the store."


# ─── Response Parsing Tests ──────────────────────────────────────────────────


class TestResponseParsing:
    @pytest.mark.asyncio
    async def test_parse_no_correction_signal(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "NO_CORRECTION"},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("Good text.")
            assert result.correction is None
            assert result.has_correction is False

    @pytest.mark.asyncio
    async def test_parse_same_text_returned(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "He walks to the store."},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("He walks to the store.")
            assert result.correction is None
            assert result.has_correction is False

    @pytest.mark.asyncio
    async def test_parse_too_short_response(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "OK"},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("Some text.")
            assert result.correction is None

    @pytest.mark.asyncio
    async def test_parse_empty_response(self):
        engine = GramEngine({"backend": "ollama", "model": "qwen2.5:0.5b"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": ""},
                status=200,
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("Some text.")
            assert result.correction is None


# ─── Config Application Tests ────────────────────────────────────────────────


class TestConfigApplication:
    @pytest.mark.asyncio
    async def test_apply_config_updates_system_prompt(self):
        engine = GramEngine({"system_prompt": "Old prompt"})
        await engine.apply_config({"system_prompt": "New prompt"})
        assert engine.system_prompt == "New prompt"

    @pytest.mark.asyncio
    async def test_apply_config_resets_backend(self):
        engine = GramEngine({"backend": "ollama"})
        engine._backend_type = Backend.OLLAMA
        await engine.apply_config({"backend": "foundation_models"})
        assert engine._backend_type == Backend.NONE

    @pytest.mark.asyncio
    async def test_apply_config_clears_detection_cache(self):
        engine = GramEngine({"backend": "ollama"})
        engine._detection_cache = Backend.OLLAMA
        await engine.apply_config({"backend": "harper"})
        assert engine._detection_cache is None


# ─── Model Listing Tests ─────────────────────────────────────────────────────


class TestModelListing:
    @pytest.mark.asyncio
    async def test_list_ollama_models(self):
        engine = GramEngine({"backend": "ollama"})
        with aioresponses() as m:
            m.get(
                f"{OLLAMA_BASE}/api/tags",
                payload={"models": [{"name": "qwen2.5:0.5b"}, {"name": "llama3"}]},
                status=200,
            )
            models = await engine._factory.get_backend(Backend.OLLAMA).list_models()
            assert "qwen2.5:0.5b" in models
            assert "llama3" in models

    @pytest.mark.asyncio
    async def test_list_ollama_models_on_error(self):
        engine = GramEngine({"backend": "ollama"})
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", exception=aiohttp.ClientError())
            models = await engine._factory.get_backend(Backend.OLLAMA).list_models()
            assert models == []

    @pytest.mark.asyncio
    async def test_list_lmstudio_models(self):
        engine = GramEngine({"backend": "lmstudio"})
        with aioresponses() as m:
            m.get(
                f"{LMSTUDIO_BASE}/v1/models",
                payload={"data": [{"id": "model-1"}, {"id": "model-2"}]},
                status=200,
            )
            models = await engine._factory.get_backend(Backend.LMSTUDIO).list_models()
            assert "model-1" in models
            assert "model-2" in models

    @pytest.mark.asyncio
    async def test_list_lmstudio_models_on_error(self):
        engine = GramEngine({"backend": "lmstudio"})
        with aioresponses() as m:
            m.get(f"{LMSTUDIO_BASE}/v1/models", exception=aiohttp.ClientError())
            models = await engine._factory.get_backend(Backend.LMSTUDIO).list_models()
            assert models == []


# ─── OllamaBackend Tests ─────────────────────────────────────────────────────


class TestOllamaBackend:
    @pytest.mark.asyncio
    async def test_backend_type(self):
        backend = OllamaBackend()
        assert backend.backend_type == Backend.OLLAMA

    @pytest.mark.asyncio
    async def test_model_property(self):
        backend = OllamaBackend(model="custom-model")
        assert backend.model == "custom-model"
        backend.model = "new-model"
        assert backend.model == "new-model"

    @pytest.mark.asyncio
    async def test_is_available_success(self):
        backend = OllamaBackend()
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)
            assert await backend.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_failure(self):
        backend = OllamaBackend()
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", exception=aiohttp.ClientError())
            assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_get_status_available(self):
        backend = OllamaBackend(model="test-model")
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)
            status = await backend.get_status()
            assert status.available is True
            assert status.model == "test-model"

    @pytest.mark.asyncio
    async def test_get_status_unavailable(self):
        backend = OllamaBackend()
        with aioresponses() as m:
            m.get(f"{OLLAMA_BASE}/api/tags", exception=aiohttp.ClientError())
            status = await backend.get_status()
            assert status.available is False

    @pytest.mark.asyncio
    async def test_correct_success(self):
        backend = OllamaBackend(model="test-model")
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "Corrected text."},
                status=200,
            )
            result = await backend.correct("Original text.")
            assert result == "Corrected text."

    @pytest.mark.asyncio
    async def test_correct_with_system_prompt(self):
        backend = OllamaBackend(model="test-model")
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                payload={"response": "Corrected."},
                status=200,
            )
            result = await backend.correct("Text.", system_prompt="Custom prompt")
            assert result == "Corrected."

    @pytest.mark.asyncio
    async def test_close(self):
        backend = OllamaBackend()
        await backend.close()


# ─── LMStudioBackend Tests ───────────────────────────────────────────────────


class TestLMStudioBackend:
    @pytest.mark.asyncio
    async def test_backend_type(self):
        backend = LMStudioBackend()
        assert backend.backend_type == Backend.LMSTUDIO

    @pytest.mark.asyncio
    async def test_model_property(self):
        backend = LMStudioBackend(model="custom-model")
        assert backend.model == "custom-model"
        backend.model = "new-model"
        assert backend.model == "new-model"

    @pytest.mark.asyncio
    async def test_is_available_success(self):
        backend = LMStudioBackend()
        with aioresponses() as m:
            m.get(f"{LMSTUDIO_BASE}/v1/models", payload={"data": []}, status=200)
            assert await backend.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_failure(self):
        backend = LMStudioBackend()
        with aioresponses() as m:
            m.get(f"{LMSTUDIO_BASE}/v1/models", exception=aiohttp.ClientError())
            assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_get_status_available(self):
        backend = LMStudioBackend(model="test-model")
        with aioresponses() as m:
            m.get(f"{LMSTUDIO_BASE}/v1/models", payload={"data": []}, status=200)
            status = await backend.get_status()
            assert status.available is True
            assert status.model == "test-model"

    @pytest.mark.asyncio
    async def test_correct_success(self):
        backend = LMStudioBackend(model="test-model")
        with aioresponses() as m:
            m.post(
                f"{LMSTUDIO_BASE}/v1/chat/completions",
                payload={"choices": [{"message": {"content": "Corrected."}}]},
                status=200,
            )
            result = await backend.correct("Original.")
            assert result == "Corrected."


# ─── HarperBackend Tests ─────────────────────────────────────────────────────


class TestHarperBackend:
    @pytest.mark.asyncio
    async def test_backend_type(self):
        backend = HarperBackend()
        assert backend.backend_type == Backend.HARPER

    @pytest.mark.asyncio
    async def test_is_available(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return HarperStatus(supported=True, available=True, helper_path=Path("/tmp/test"), node_path="/usr/bin/node")
        mock_bridge.status = fake_status
        backend = HarperBackend(bridge=mock_bridge)
        assert await backend.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return HarperStatus(supported=True, available=False, reason="No node")
        mock_bridge.status = fake_status
        backend = HarperBackend(bridge=mock_bridge)
        assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_get_status(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return HarperStatus(supported=True, available=True, helper_path=Path("/tmp/test"), node_path="/usr/bin/node")
        mock_bridge.status = fake_status
        backend = HarperBackend(bridge=mock_bridge)
        status = await backend.get_status()
        assert status.available is True
        assert status.model == "harper.english"

    @pytest.mark.asyncio
    async def test_correct(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return HarperStatus(supported=True, available=True, helper_path=Path("/tmp/test"), node_path="/usr/bin/node")
        async def fake_correct(text):
            return "Corrected."
        mock_bridge.status = fake_status
        mock_bridge.correct = fake_correct
        backend = HarperBackend(bridge=mock_bridge)
        result = await backend.correct("Original.")
        assert result == "Corrected."

    @pytest.mark.asyncio
    async def test_correct_strips_action_prefix(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return HarperStatus(supported=True, available=True, helper_path=Path("/tmp/test"), node_path="/usr/bin/node")
        async def fake_correct(text):
            assert text == "He walk."
            return "He walks."
        mock_bridge.status = fake_status
        mock_bridge.correct = fake_correct
        backend = HarperBackend(bridge=mock_bridge)
        result = await backend.correct("[ACTION LINE — test]\nHe walk.")
        assert result == "He walks."


# ─── FoundationModelsBackend Tests ───────────────────────────────────────────


class TestFoundationModelsBackend:
    @pytest.mark.asyncio
    async def test_backend_type(self):
        backend = FoundationModelsBackend()
        assert backend.backend_type == Backend.FOUNDATION_MODELS

    @pytest.mark.asyncio
    async def test_is_available(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return FoundationModelsStatus(supported=True, available=True, helper_path=Path("/tmp/test"))
        mock_bridge.status = fake_status
        backend = FoundationModelsBackend(bridge=mock_bridge)
        assert await backend.is_available() is True

    @pytest.mark.asyncio
    async def test_is_available_false(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return FoundationModelsStatus(supported=True, available=False, reason="Not available")
        mock_bridge.status = fake_status
        backend = FoundationModelsBackend(bridge=mock_bridge)
        assert await backend.is_available() is False

    @pytest.mark.asyncio
    async def test_get_status(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return FoundationModelsStatus(supported=True, available=True, helper_path=Path("/tmp/test"))
        mock_bridge.status = fake_status
        backend = FoundationModelsBackend(bridge=mock_bridge)
        status = await backend.get_status()
        assert status.available is True
        assert status.model == "apple.foundation"

    @pytest.mark.asyncio
    async def test_correct(self):
        mock_bridge = MagicMock()
        async def fake_status(force_refresh=False):
            return FoundationModelsStatus(supported=True, available=True, helper_path=Path("/tmp/test"))
        async def fake_correct(text, instructions):
            return "Corrected."
        mock_bridge.status = fake_status
        mock_bridge.correct = fake_correct
        backend = FoundationModelsBackend(bridge=mock_bridge)
        result = await backend.correct("Original.", system_prompt="Fix grammar")
        assert result == "Corrected."


# ─── BackendFactory Tests ────────────────────────────────────────────────────


class TestBackendFactory:
    def test_create_ollama_backend(self):
        factory = BackendFactory({"model": "test-model"})
        backend = factory.get_backend(Backend.OLLAMA)
        assert isinstance(backend, OllamaBackend)
        assert backend.model == "test-model"

    def test_create_lmstudio_backend(self):
        factory = BackendFactory({"model": "test-model"})
        backend = factory.get_backend(Backend.LMSTUDIO)
        assert isinstance(backend, LMStudioBackend)

    def test_create_harper_backend(self):
        factory = BackendFactory({})
        backend = factory.get_backend(Backend.HARPER)
        assert isinstance(backend, HarperBackend)

    def test_create_foundation_models_backend(self):
        factory = BackendFactory({})
        backend = factory.get_backend(Backend.FOUNDATION_MODELS)
        assert isinstance(backend, FoundationModelsBackend)

    def test_caches_backend_instances(self):
        factory = BackendFactory({})
        backend1 = factory.get_backend(Backend.OLLAMA)
        backend2 = factory.get_backend(Backend.OLLAMA)
        assert backend1 is backend2

    def test_unknown_backend_raises(self):
        factory = BackendFactory({})
        with pytest.raises(ValueError, match="Unknown backend type"):
            factory.get_backend(Backend.NONE)

    @pytest.mark.asyncio
    async def test_close_all(self):
        factory = BackendFactory({})
        factory.get_backend(Backend.OLLAMA)
        await factory.close_all()
        assert len(factory._backends) == 0


# ─── GrammarBackend Abstract Tests ───────────────────────────────────────────


class TestGrammarBackend:
    def test_grammar_backend_is_abstract(self):
        with pytest.raises(TypeError):
            GrammarBackend()

    def test_concrete_backend_implements_all_methods(self):
        """All concrete backends should implement the abstract interface."""
        backends = [
            OllamaBackend(),
            LMStudioBackend(),
            HarperBackend(),
            FoundationModelsBackend(),
        ]
        for backend in backends:
            assert hasattr(backend, "correct")
            assert hasattr(backend, "is_available")
            assert hasattr(backend, "get_status")
            assert hasattr(backend, "list_models")
            assert hasattr(backend, "backend_type")


# ─── CorrectionResult Tests ──────────────────────────────────────────────────


class TestCorrectionResult:
    def test_correction_result_dataclass(self):
        result = CorrectionResult(
            original="test",
            correction="fixed",
            has_correction=True,
            backend=Backend.OLLAMA,
            latency_ms=50.0,
        )
        assert result.original == "test"
        assert result.correction == "fixed"
        assert result.has_correction is True
        assert result.backend == Backend.OLLAMA
        assert result.latency_ms == 50.0

    def test_correction_result_optional_error(self):
        result = CorrectionResult(
            original="test",
            correction=None,
            has_correction=False,
            backend=Backend.NONE,
            latency_ms=0.0,
        )
        assert result.error is None

    def test_correction_result_with_error(self):
        result = CorrectionResult(
            original="test",
            correction=None,
            has_correction=False,
            backend=Backend.OLLAMA,
            latency_ms=10.0,
            error="Connection failed",
        )
        assert result.error == "Connection failed"


# ─── BackendStatus Tests ─────────────────────────────────────────────────────


class TestBackendStatus:
    def test_backend_status_defaults(self):
        status = BackendStatus(available=True)
        assert status.available is True
        assert status.reason is None
        assert status.model is None
        assert status.models == []

    def test_backend_status_with_values(self):
        status = BackendStatus(
            available=False,
            reason="Server not running",
            model="test-model",
            models=["model-1", "model-2"],
        )
        assert status.available is False
        assert status.reason == "Server not running"
        assert status.model == "test-model"
        assert len(status.models) == 2


# ─── Backend Enum Tests ──────────────────────────────────────────────────────


class TestBackendEnum:
    def test_backend_values(self):
        assert Backend.OLLAMA.value == "ollama"
        assert Backend.LMSTUDIO.value == "lmstudio"
        assert Backend.FOUNDATION_MODELS.value == "foundation_models"
        assert Backend.HARPER.value == "harper"
        assert Backend.NONE.value == "none"


# ─── Timeout Tests ───────────────────────────────────────────────────────────


class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_timeout_returns_error_result(self):
        """Test that timeout errors are handled gracefully."""
        engine = GramEngine({"backend": "ollama", "model": "test"})
        with aioresponses() as m:
            m.post(
                f"{OLLAMA_BASE}/api/generate",
                exception=asyncio.TimeoutError("Request timed out"),
            )
            m.get(f"{OLLAMA_BASE}/api/tags", payload={"models": []}, status=200)

            result = await engine.correct("Some text.")
            assert result.correction is None
            assert result.has_correction is False
            assert result.error is not None
            assert result.latency_ms >= 0
