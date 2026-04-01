"""
config_store.py — shared config loading and saving helpers
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Any

import yaml


DEFAULT_CONFIG = {
    "backend": "auto",
    "model": "qwen3.5:0.8b",
    "sensitivity": "medium",
    "strict_mode": True,
    "system_prompt": (
        "You are a Hollywood script doctor.\n"
        "Correct grammar and spelling only.\n"
        "Do NOT rewrite stylistic fragments.\n"
        "Do NOT modify ALL CAPS character names or sluglines.\n"
        "Preserve pacing and rhythm of screenplay writing.\n"
        "If the text has no errors, respond with exactly: NO_CORRECTION\n"
        "If there is an error, respond with ONLY the corrected sentence."
    ),
    "debounce_seconds": 2.0,
    "max_context_chars": 300,
    "dashboard_port": 7878,
}


def resolve_config_path(requested_path: Path | None = None, *, explicit: bool = False) -> Path:
    if explicit and requested_path is not None:
        return _normalize_path(requested_path)

    if requested_path is not None:
        candidate = _normalize_path(requested_path)
        if candidate.exists():
            return candidate

    project_config = _project_config_path()
    if project_config is not None and project_config.exists():
        return project_config

    return user_config_dir() / "config.yaml"


def load_config(path: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    normalized_path = _normalize_path(path)

    if normalized_path.exists():
        with normalized_path.open(encoding="utf-8") as handle:
            user_config = yaml.safe_load(handle) or {}
        config.update(user_config)

    config["_config_path"] = str(normalized_path)
    return config


def save_config(config: Mapping[str, Any], path: str | Path) -> Path:
    normalized_path = _normalize_path(Path(path))
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_config(config)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=normalized_path.parent,
        prefix=f".{normalized_path.stem}-",
        suffix=normalized_path.suffix,
        delete=False,
    ) as handle:
        yaml.dump(payload, handle, default_flow_style=False, allow_unicode=True, sort_keys=False)
        temp_path = Path(handle.name)

    os.replace(temp_path, normalized_path)
    return normalized_path


def sanitize_config(config: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if not str(key).startswith("_")}


def user_config_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "GramWrite"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "GramWrite"
        return home / "AppData" / "Roaming" / "GramWrite"

    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "gramwrite"
    return home / ".config" / "gramwrite"


def _project_config_path() -> Path | None:
    if hasattr(sys, "_MEIPASS"):
        return None

    package_root = Path(__file__).resolve().parent.parent
    config_path = package_root / "config.yaml"
    if config_path.exists():
        return config_path
    return None


def _normalize_path(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (Path.cwd() / expanded).resolve()
