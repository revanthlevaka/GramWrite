import os
import tempfile
import yaml
from pathlib import Path
from gramwrite.__main__ import load_config

def test_load_config_defaults():
    # If file doesn't exist, it should return defaults
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        config = load_config(config_path)
        assert config["backend"] == "auto"
        assert config["model"] == "qwen3.5:0.8b"

def test_load_config_custom():
    # If file exists, it should merge with defaults
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "config.yaml"
        custom_config = {"backend": "openai", "model": "gpt-4"}
        with open(config_path, "w") as f:
            yaml.dump(custom_config, f)
            
        config = load_config(config_path)
        assert config["backend"] == "openai"
        assert config["model"] == "gpt-4"
        assert config["sensitivity"] == "medium" # predefined default
