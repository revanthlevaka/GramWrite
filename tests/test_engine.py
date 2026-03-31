import pytest
from aioresponses import aioresponses
from gramwrite.engine import GramEngine, Backend, OLLAMA_BASE

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
