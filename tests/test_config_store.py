from pathlib import Path

import pytest
import yaml

from gramwrite.config_store import resolve_config_path, save_config
from gramwrite.engine import Backend, GramEngine


def test_save_config_filters_internal_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    saved_path = save_config(
        {
            "backend": "foundation_models",
            "model": "apple.foundation",
            "_config_path": "/should/not/be/saved.yaml",
        },
        config_path,
    )

    assert saved_path == config_path.resolve()
    saved_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved_data == {
        "backend": "foundation_models",
        "model": "apple.foundation",
    }


def test_resolve_config_path_uses_user_dir_for_missing_default(monkeypatch, tmp_path):
    monkeypatch.setattr("gramwrite.config_store._project_config_path", lambda: None)
    monkeypatch.setattr("gramwrite.config_store.user_config_dir", lambda: tmp_path / "GramWrite")
    monkeypatch.chdir(tmp_path)

    resolved = resolve_config_path(Path("config.yaml"), explicit=False)

    assert resolved == (tmp_path / "GramWrite" / "config.yaml").resolve()


@pytest.mark.asyncio
async def test_engine_apply_config_updates_runtime_settings():
    engine = GramEngine(
        {
            "backend": "ollama",
            "model": "qwen3.5:0.8b",
            "system_prompt": "Old prompt",
        }
    )
    engine.backend = Backend.OLLAMA

    updated = {
        "backend": "foundation_models",
        "model": "apple.foundation",
        "system_prompt": "New prompt",
    }

    await engine.apply_config(updated)

    assert engine.config is updated
    assert engine.model == "apple.foundation"
    assert engine.system_prompt == "New prompt"
    assert engine.backend == Backend.NONE
    await engine.close()
