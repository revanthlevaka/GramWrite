import pytest
from aioresponses import aioresponses
from gramwrite.engine import GramEngine, Backend, OLLAMA_BASE
from gramwrite.foundation_models import FoundationModelsStatus
from gramwrite.harper import HarperStatus
from pathlib import Path

@pytest.fixture
def engine():
    # Setup standard config
    config = {
        "backend": "ollama", # Force ollama for tests
        "model": "qwen2.5:0.5b",
        "system_prompt": "You are a script doctor. Reply NO_CORRECTION if good.",
        "max_context_chars": 300,
    }
    return GramEngine(config)

@pytest.mark.asyncio
async def test_engine_successful_correction(engine):
    with aioresponses() as m:
        # Mock the Ollama API response
        m.post(
            f"{OLLAMA_BASE}/api/generate",
            payload={"response": "He walks to the store."},
            status=200
        )

        # Test detection mock
        m.get(
            f"{OLLAMA_BASE}/api/tags",
            payload={"models": []},
            status=200
        )

        result = await engine.correct("He walk to store.")
        assert result.correction == "He walks to the store."
        assert result.has_correction is True
        assert result.backend == Backend.OLLAMA
        await engine.close()

@pytest.mark.asyncio
async def test_engine_no_correction(engine):
    with aioresponses() as m:
        # Mock the Ollama API returning NO_CORRECTION
        m.post(
            f"{OLLAMA_BASE}/api/generate",
            payload={"response": "NO_CORRECTION"},
            status=200
        )

        m.get(
            f"{OLLAMA_BASE}/api/tags",
            payload={"models": []},
            status=200
        )

        result = await engine.correct("He walks to the store.")
        assert result.correction is None # Engine returns None when NO_CORRECTION is received
        assert result.has_correction is False
        await engine.close()

@pytest.mark.asyncio
async def test_engine_connection_error(engine):
    with aioresponses() as m:
        # Mock a connection error by mocking the URL to exception
        import aiohttp
        m.post(
            f"{OLLAMA_BASE}/api/generate",
            exception=aiohttp.ClientConnectionError("Failed to connect")
        )
        m.get(
            f"{OLLAMA_BASE}/api/tags",
            payload={"models": []},
            status=200
        )

        result = await engine.correct("He walk to store.")
        assert result.correction is None
        assert result.has_correction is False
        assert "Failed to connect" in result.error
        await engine.close()


@pytest.mark.asyncio
async def test_engine_detects_foundation_models_backend():
    engine = GramEngine(
        {
            "backend": "foundation_models",
            "model": "apple.foundation",
            "system_prompt": "Correct grammar only.",
        }
    )

    async def fake_status(force_refresh: bool = False):
        return FoundationModelsStatus(
            supported=True,
            available=True,
            helper_path=Path("/tmp/gramwrite-foundation-models"),
        )

    engine._foundation.status = fake_status
    backend = await engine.detect_backend()
    assert backend == Backend.FOUNDATION_MODELS
    await engine.close()


@pytest.mark.asyncio
async def test_engine_foundation_models_correction():
    engine = GramEngine(
        {
            "backend": "foundation_models",
            "model": "apple.foundation",
            "system_prompt": "Correct grammar only.",
        }
    )

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

    engine._foundation.status = fake_status
    engine._foundation.correct = fake_correct

    result = await engine.correct("He walk to the store.")
    assert result.backend == Backend.FOUNDATION_MODELS
    assert result.has_correction is True
    assert result.correction == "He walks to the store."
    await engine.close()


@pytest.mark.asyncio
async def test_engine_detects_harper_backend():
    engine = GramEngine(
        {
            "backend": "harper",
            "model": "harper.english",
            "system_prompt": "Correct grammar only.",
        }
    )

    async def fake_status(force_refresh: bool = False):
        return HarperStatus(
            supported=True,
            available=True,
            helper_path=Path("/tmp/gramwrite-harper.mjs"),
            node_path="/usr/bin/node",
        )

    engine._harper.status = fake_status
    backend = await engine.detect_backend()
    assert backend == Backend.HARPER
    await engine.close()


@pytest.mark.asyncio
async def test_engine_harper_correction():
    engine = GramEngine(
        {
            "backend": "harper",
            "model": "harper.english",
            "system_prompt": "Ignored by Harper.",
        }
    )

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

    engine._harper.status = fake_status
    engine._harper.correct = fake_correct

    result = await engine.correct("He walk to the store.")
    assert result.backend == Backend.HARPER
    assert result.has_correction is True
    assert result.correction == "He walks to the store."
    await engine.close()


@pytest.mark.asyncio
async def test_engine_harper_strips_action_prefix():
    engine = GramEngine(
        {
            "backend": "harper",
            "model": "harper.english",
            "system_prompt": "Ignored by Harper.",
        }
    )

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

    engine._harper.status = fake_status
    engine._harper.correct = fake_correct

    result = await engine.correct("[ACTION LINE — stylistic fragments are intentional]\nHe walk to the store.")
    assert result.backend == Backend.HARPER
    assert result.has_correction is True
    assert result.correction == "He walks to the store."
    await engine.close()
