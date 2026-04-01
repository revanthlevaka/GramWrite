"""
conftest.py — Shared pytest fixtures for GramWrite test suite.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from gramwrite.config_store import DEFAULT_CONFIG, save_config
from gramwrite.engine import Backend, GramEngine
from gramwrite.fountain_parser import FountainParser, ParsedBlock, FountainElement
from gramwrite.controller import Controller, PipelineResult
from gramwrite.watcher import TypedTextBuffer, Watcher


# ─── Fountain Parser Fixtures ────────────────────────────────────────────────


@pytest.fixture
def parser():
    """Fresh FountainParser instance."""
    return FountainParser()


@pytest.fixture
def sample_slugline():
    return "INT. COFFEE SHOP - DAY"


@pytest.fixture
def sample_character():
    return "JOHN"


@pytest.fixture
def sample_dialogue():
    return "I can't believe you did that."


@pytest.fixture
def sample_action():
    return "He walks across the room and opens the door."


@pytest.fixture
def sample_transition():
    return "CUT TO:"


@pytest.fixture
def sample_parenthetical():
    return "(sighs)"


# ─── Engine Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def engine_config():
    """Standard engine config for testing."""
    return {
        "backend": "ollama",
        "model": "qwen2.5:0.5b",
        "system_prompt": "You are a script doctor. Reply NO_CORRECTION if good.",
        "max_context_chars": 300,
    }


@pytest.fixture
def engine(engine_config):
    """GramEngine instance with test config."""
    return GramEngine(engine_config)


@pytest.fixture
def foundation_models_engine():
    """Engine configured for Apple Foundation Models."""
    return GramEngine({
        "backend": "foundation_models",
        "model": "apple.foundation",
        "system_prompt": "Correct grammar only.",
    })


@pytest.fixture
def harper_engine():
    """Engine configured for Harper backend."""
    return GramEngine({
        "backend": "harper",
        "model": "harper.english",
        "system_prompt": "Ignored by Harper.",
    })


# ─── Controller Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_on_result():
    """Mock callback for controller results."""
    return MagicMock()


@pytest.fixture
def controller_config():
    """Standard controller config."""
    return {
        "backend": "ollama",
        "model": "qwen2.5:0.5b",
        "sensitivity": "medium",
        "strict_mode": True,
        "debounce_seconds": 0.1,  # Fast for tests
        "system_prompt": "Correct grammar only.",
    }


@pytest.fixture
def controller(controller_config, mock_on_result):
    """Controller instance with mocked callback."""
    return Controller(controller_config, mock_on_result)


# ─── Watcher Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def typed_buffer():
    """TypedTextBuffer with small limits for testing."""
    return TypedTextBuffer(max_chars=100, ttl_secs=60.0)


@pytest.fixture
def watcher_config():
    """Watcher config."""
    return {
        "debounce_seconds": 0.1,
    }


@pytest.fixture
def mock_callback():
    """Async mock callback for watcher."""
    return AsyncMock()


# ─── Config Store Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def temp_config_path(tmp_path):
    """Temporary config file path."""
    return tmp_path / "config.yaml"


@pytest.fixture
def saved_config(temp_config_path):
    """Save a standard config and return the path."""
    config = {
        "backend": "ollama",
        "model": "qwen2.5:0.5b",
        "sensitivity": "high",
    }
    save_config(config, temp_config_path)
    return temp_config_path


# ─── Integration Test Helpers ────────────────────────────────────────────────


@pytest.fixture
def screenplay_excerpt():
    """Real-world screenplay excerpt for integration tests."""
    return """INT. COFFEE SHOP - DAY

John sits at a corner table, staring at his laptop.

JOHN
i dont know what your talking about.

MARY
You know exactly what I mean.

John looks away. The rain pours outside.

CUT TO:

EXT. HIGHWAY - NIGHT

A car speeds down the empty road.
"""


@pytest.fixture
def dialogue_only_excerpt():
    """Dialogue-only excerpt for grammar testing."""
    return """JOHN
i dont know what your talking about.

MARY
he was their yesterday, but he didnt call me.
"""


@pytest.fixture
def action_only_excerpt():
    """Action-only excerpt for tense testing."""
    return """He walked into the room and looked around.
The door slam open. She ran to the window.
"""
