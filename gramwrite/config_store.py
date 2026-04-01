"""
config_store.py — Robust, type-safe configuration management for GramWrite.

Provides:
- Schema validation with type checking and range enforcement
- Atomic writes (write to temp file, then rename)
- File locking for concurrent access safety
- Default value management with platform-specific overrides
- Migration support for config version changes
- Change notifications and hot-reload support
- Clean, async-safe API for all modules

Usage:
    from gramwrite.config_store import ConfigStore

    store = ConfigStore()
    config = store.load()
    store.save(config)
"""

from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums for constrained config values
# ---------------------------------------------------------------------------

class BackendType(str, Enum):
    """Supported grammar correction backends."""
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    HARPER = "harper"
    FOUNDATION_MODELS = "foundation_models"
    NONE = "none"
    AUTO = "auto"  # Legacy alias, maps to auto-detection


class SensitivityLevel(str, Enum):
    """How aggressively to flag potential issues."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ThemeType(str, Enum):
    """UI theme options."""
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

@dataclass
class ConfigField:
    """Metadata for a single configuration field."""
    type: type
    default: Any
    description: str = ""
    required: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    choices: Optional[list[str]] = None
    nested_schema: Optional[dict[str, ConfigField]] = None


CONFIG_SCHEMA: dict[str, ConfigField] = {
    "version": ConfigField(
        type=int,
        default=1,
        description="Configuration schema version for migration support.",
        min_value=1,
    ),
    "backend": ConfigField(
        type=str,
        default=BackendType.AUTO.value,
        description="Grammar backend to use: ollama, lmstudio, harper, foundation_models, none, or auto.",
        choices=[e.value for e in BackendType],
    ),
    "model": ConfigField(
        type=str,
        default="qwen3.5:0.8b",
        description="Model identifier for the selected backend.",
    ),
    "sensitivity": ConfigField(
        type=str,
        default=SensitivityLevel.MEDIUM.value,
        description="How aggressively to flag issues: low, medium, high.",
        choices=[e.value for e in SensitivityLevel],
    ),
    "strict_mode": ConfigField(
        type=bool,
        default=True,
        description="When True, only fix unambiguous grammar mistakes.",
    ),
    "system_prompt": ConfigField(
        type=str,
        default=(
            "You are a Hollywood script doctor.\n"
            "Correct grammar and spelling only.\n"
            "Do NOT rewrite stylistic fragments.\n"
            "Do NOT modify ALL CAPS character names or sluglines.\n"
            "Preserve pacing and rhythm of screenplay writing.\n"
            "If the text has no errors, respond with exactly: NO_CORRECTION\n"
            "If there is an error, respond with ONLY the corrected sentence."
        ),
        description="System prompt sent to LLM backends.",
    ),
    "debounce_ms": ConfigField(
        type=int,
        default=2000,
        description="Milliseconds to wait after last keystroke before checking.",
        min_value=100,
        max_value=10000,
    ),
    "max_cache_size": ConfigField(
        type=int,
        default=500,
        description="Maximum number of entries in the correction cache.",
        min_value=0,
        max_value=10000,
    ),
    "cache_ttl_secs": ConfigField(
        type=int,
        default=3600,
        description="Time-to-live for cached corrections in seconds.",
        min_value=60,
        max_value=86400,
    ),
    "max_context_chars": ConfigField(
        type=int,
        default=300,
        description="Maximum characters of context sent to the backend.",
        min_value=50,
        max_value=2000,
    ),
    "dashboard_port": ConfigField(
        type=int,
        default=7878,
        description="Port for the local web dashboard.",
        min_value=1024,
        max_value=65535,
    ),

    # --- Nested: UI ---
    "ui": ConfigField(
        type=dict,
        default={},
        description="User interface settings.",
        nested_schema={
            "always_on_top": ConfigField(
                type=bool,
                default=True,
                description="Keep the suggestion window above other windows.",
            ),
            "theme": ConfigField(
                type=str,
                default=ThemeType.SYSTEM.value,
                description="UI theme: light, dark, or system.",
                choices=[e.value for e in ThemeType],
            ),
            "position": ConfigField(
                type=dict,
                default={"x": 100, "y": 100},
                description="Window position in screen coordinates.",
                nested_schema={
                    "x": ConfigField(type=int, default=100, description="X coordinate."),
                    "y": ConfigField(type=int, default=100, description="Y coordinate."),
                },
            ),
            "size": ConfigField(
                type=dict,
                default={"width": 400, "height": 200},
                description="Window size in pixels.",
                nested_schema={
                    "width": ConfigField(type=int, default=400, min_value=200, max_value=1920, description="Window width."),
                    "height": ConfigField(type=int, default=200, min_value=100, max_value=1080, description="Window height."),
                },
            ),
        },
    ),

    # --- Nested: Watcher ---
    "watcher": ConfigField(
        type=dict,
        default={},
        description="Text watcher / clipboard monitor settings.",
        nested_schema={
            "poll_interval_ms": ConfigField(
                type=int,
                default=500,
                description="How often to poll for text changes (milliseconds).",
                min_value=100,
                max_value=5000,
            ),
            "max_extract_chars": ConfigField(
                type=int,
                default=1000,
                description="Maximum characters to extract from screen context.",
                min_value=100,
                max_value=5000,
            ),
            "buffer_ttl_secs": ConfigField(
                type=float,
                default=5.0,
                description="How long to keep buffered text before discarding (seconds).",
                min_value=1.0,
                max_value=60.0,
            ),
        },
    ),
}

# Legacy DEFAULT_CONFIG for backward compatibility during transition.
DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "backend": BackendType.AUTO.value,
    "model": "qwen3.5:0.8b",
    "sensitivity": SensitivityLevel.MEDIUM.value,
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
    "debounce_ms": 2000,
    "max_cache_size": 500,
    "cache_ttl_secs": 3600,
    "max_context_chars": 300,
    "dashboard_port": 7878,
    "ui": {
        "always_on_top": True,
        "theme": ThemeType.SYSTEM.value,
        "position": {"x": 100, "y": 100},
        "size": {"width": 400, "height": 200},
    },
    "watcher": {
        "poll_interval_ms": 500,
        "max_extract_chars": 1000,
        "buffer_ttl_secs": 5.0,
    },
}

# Backward-compat alias: legacy code may reference debounce_seconds.
LEGACY_KEY_MAP: dict[str, str] = {
    "debounce_seconds": "debounce_ms",
    "max_context_chars": "max_context_chars",  # unchanged, just listed for migration awareness
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

class ConfigValidationError(ValueError):
    """Raised when configuration validation fails."""
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(
            f"Configuration validation failed ({len(errors)} issue{'s' if len(errors) != 1 else ''}):\n"
            + "\n".join(f"  • {e}" for e in errors)
        )


def _validate_value(
    key: str,
    value: Any,
    schema: ConfigField,
    errors: list[str],
    path_prefix: str = "",
) -> Any:
    """Validate a single value against its schema. Returns the (possibly coerced) value."""
    full_key = f"{path_prefix}{key}" if path_prefix else key

    # --- Type coercion for common cases ---
    if isinstance(value, str) and schema.type in (int, float):
        try:
            value = schema.type(value)
        except (ValueError, TypeError):
            errors.append(f"{full_key}: expected {schema.type.__name__}, got string '{value}'")
            return copy.deepcopy(schema.default)

    if not isinstance(value, schema.type):
        errors.append(f"{full_key}: expected {schema.type.__name__}, got {type(value).__name__}")
        return copy.deepcopy(schema.default)

    # --- Range checks ---
    if schema.min_value is not None and value < schema.min_value:
        errors.append(f"{full_key}: value {value} is below minimum {schema.min_value}")
    if schema.max_value is not None and value > schema.max_value:
        errors.append(f"{full_key}: value {value} exceeds maximum {schema.max_value}")

    # --- Enum / choices check ---
    if schema.choices is not None and value not in schema.choices:
        errors.append(f"{full_key}: '{value}' is not one of {schema.choices}")
        return copy.deepcopy(schema.default)

    # --- Nested schema ---
    if schema.nested_schema is not None and isinstance(value, dict):
        value = _validate_nested(full_key, value, schema.nested_schema, errors)

    return value


def _validate_nested(
    parent_key: str,
    data: dict[str, Any],
    schema: dict[str, ConfigField],
    errors: list[str],
) -> dict[str, Any]:
    """Validate a nested dictionary against a sub-schema, filling in defaults."""
    result: dict[str, Any] = {}
    for field_name, field_schema in schema.items():
        if field_name in data:
            result[field_name] = _validate_value(
                field_name, data[field_name], field_schema, errors,
                path_prefix=f"{parent_key}.",
            )
        else:
            result[field_name] = copy.deepcopy(field_schema.default)
    return result


def _ensure_nested_defaults(
    data: dict[str, Any],
    schema: dict[str, ConfigField],
) -> dict[str, Any]:
    """Fill in nested defaults for dict fields that have nested_schema definitions."""
    result = dict(data)
    for field_name, field_schema in schema.items():
        if field_schema.nested_schema is not None:
            current = result.get(field_name, {})
            if not isinstance(current, dict):
                current = {}
            # Fill in missing nested fields
            for nested_name, nested_schema in field_schema.nested_schema.items():
                if nested_name not in current:
                    current[nested_name] = copy.deepcopy(nested_schema.default)
                # Recurse for deeper nesting
                if nested_schema.nested_schema is not None and isinstance(current.get(nested_name), dict):
                    current[nested_name] = _ensure_nested_defaults(
                        current[nested_name],
                        {nested_name: nested_schema},
                    )
                    # _ensure_nested_defaults returns a dict with the top-level key,
                    # so we need to extract the nested part
                    if nested_name in current[nested_name]:
                        current[nested_name] = current[nested_name][nested_name]
            result[field_name] = current
    return result


def validate_config(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """
    Validate a configuration dictionary against CONFIG_SCHEMA.

    Returns:
        (sanitized_config, errors) — sanitized config has defaults filled in
        for missing fields and invalid values replaced with defaults.
    """
    errors: list[str] = []
    result: dict[str, Any] = {}

    for field_name, field_schema in CONFIG_SCHEMA.items():
        if field_name in config:
            result[field_name] = _validate_value(
                field_name, config[field_name], field_schema, errors,
            )
        else:
            result[field_name] = copy.deepcopy(field_schema.default)

    # Fill in nested defaults for dict fields with nested schemas
    result = _ensure_nested_defaults(result, CONFIG_SCHEMA)

    return result, errors


def auto_fix_config(config: dict[str, Any]) -> dict[str, Any]:
    """
    Attempt to auto-fix common configuration issues before validation.

    Handles:
    - Legacy key migration (debounce_seconds → debounce_ms)
    - Type coercion for stringified numbers
    - Backend alias normalization
    """
    fixed = dict(config)

    # Migrate legacy keys
    for old_key, new_key in LEGACY_KEY_MAP.items():
        if old_key in fixed and new_key not in fixed:
            old_val = fixed.pop(old_key)
            if old_key == "debounce_seconds" and isinstance(old_val, (int, float)):
                fixed[new_key] = int(old_val * 1000)
            else:
                fixed[new_key] = old_val
            logger.info("Auto-migrated config key: %s → %s", old_key, new_key)

    # Normalize backend aliases
    backend = fixed.get("backend", "")
    if isinstance(backend, str):
        backend_lower = backend.lower().strip()
        if backend_lower in ("auto", "automatic"):
            fixed["backend"] = BackendType.AUTO.value
        elif backend_lower in ("ollama",):
            fixed["backend"] = BackendType.OLLAMA.value
        elif backend_lower in ("lmstudio", "lm-studio", "lm_studio"):
            fixed["backend"] = BackendType.LMSTUDIO.value
        elif backend_lower in ("harper",):
            fixed["backend"] = BackendType.HARPER.value
        elif backend_lower in ("foundation_models", "foundation", "apple"):
            fixed["backend"] = BackendType.FOUNDATION_MODELS.value
        elif backend_lower in ("none", "disabled", "off"):
            fixed["backend"] = BackendType.NONE.value

    # Ensure nested dicts exist
    if "ui" not in fixed or not isinstance(fixed.get("ui"), dict):
        fixed["ui"] = {}
    if "watcher" not in fixed or not isinstance(fixed.get("watcher"), dict):
        fixed["watcher"] = {}

    return fixed


# ---------------------------------------------------------------------------
# Migration support
# ---------------------------------------------------------------------------

CURRENT_CONFIG_VERSION = 1


def migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    """
    Migrate a configuration dictionary from an older schema version to the
    current version. Preserves user settings while adding new defaults.

    Supports migrations from version 0 (implicit, no version key) to version 1.
    """
    version = config.get("version", 0)

    if version < 1:
        logger.info("Migrating config from version %d → %d", version, CURRENT_CONFIG_VERSION)
        config = auto_fix_config(config)
        config["version"] = CURRENT_CONFIG_VERSION

    # Future migrations would go here:
    # if version < 2:
    #     config = migrate_v1_to_v2(config)
    #     config["version"] = 2

    return config


# ---------------------------------------------------------------------------
# ConfigStore class
# ---------------------------------------------------------------------------

@dataclass
class ConfigStore:
    """
    Thread-safe, validated configuration store for GramWrite.

    Features:
    - Atomic writes (write to temp file, then os.replace)
    - File locking via fcntl for concurrent access safety
    - Schema validation at load time
    - Default value management
    - Migration support for config version changes
    - Change notifications via callback registration
    - Hot-reload support

    Usage:
        store = ConfigStore()
        config = store.load()
        store.register_callback(lambda c: print("Config changed!"))
        store.save(config)
    """

    _path: Optional[Path] = field(default=None, init=False)
    _config: dict[str, Any] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _callbacks: list[Callable[[dict[str, Any]], None]] = field(default_factory=list, init=False)
    _last_loaded: float = field(default=0.0, init=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def path(self) -> Optional[Path]:
        """Path to the currently loaded config file."""
        return self._path

    @property
    def config(self) -> dict[str, Any]:
        """Return a copy of the current configuration."""
        with self._lock:
            return copy.deepcopy(self._config)

    @property
    def last_loaded(self) -> float:
        """Monotonic timestamp of the last successful load."""
        return self._last_loaded

    def load(self, path: Optional[Path] = None, *, explicit: bool = False) -> dict[str, Any]:
        """
        Load configuration from disk, validate, and migrate if needed.

        Args:
            path: Explicit path to config file. If None, uses resolution logic.
            explicit: If True, use the provided path even if it doesn't exist.

        Returns:
            Validated and migrated configuration dictionary.

        Raises:
            ConfigValidationError: If the config cannot be validated after
                                   auto-fix attempts.
        """
        resolved_path = resolve_config_path(path, explicit=explicit)
        return self.load_from_path(resolved_path)

    def load_from_path(self, path: Path) -> dict[str, Any]:
        """
        Load configuration from a specific path.

        Args:
            path: Absolute path to the config file.

        Returns:
            Validated and migrated configuration dictionary.
        """
        normalized = _normalize_path(path)

        with self._lock:
            raw: dict[str, Any] = {}

            if normalized.exists():
                raw = self._read_with_lock(normalized)
            else:
                logger.info("Config file not found at %s, using defaults", normalized)

            # Merge with defaults
            merged = {**DEFAULT_CONFIG, **raw}

            # Auto-fix common issues
            merged = auto_fix_config(merged)

            # Migrate if needed
            merged = migrate_config(merged)

            # Validate
            validated, errors = validate_config(merged)
            if errors:
                logger.warning("Config validation warnings for %s:\n%s", normalized, "\n".join(errors))

            # Store internally
            self._path = normalized
            self._config = validated
            self._last_loaded = time.monotonic()

            logger.info("Config loaded from %s (version %d)", normalized, validated.get("version", 0))
            return copy.deepcopy(validated)

    def save(self, config: Optional[Mapping[str, Any]] = None, path: Optional[Path] = None) -> Path:
        """
        Save configuration to disk atomically.

        Writes to a temporary file first, then uses os.replace() for atomic
        rename. Uses file locking to prevent concurrent write corruption.

        Args:
            config: Configuration to save. If None, uses the internally
                    stored config from the last load.
            path: Destination path. If None, uses the path from the last load.

        Returns:
            The resolved path where the config was saved.

        Raises:
            ValueError: If no path is available and none was provided.
        """
        target_path = path or self._path
        if target_path is None:
            raise ValueError("No config path available. Call load() first or provide a path.")

        data = config if config is not None else self._config
        normalized = _normalize_path(target_path)

        with self._lock:
            self._atomic_write(normalized, data)
            self._config = dict(data)
            self._path = normalized
            self._notify(data)

        logger.info("Config saved to %s", normalized)
        return normalized

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """
        Update specific configuration keys and persist to disk.

        Args:
            updates: Dictionary of key-value pairs to update.

        Returns:
            The updated configuration dictionary.
        """
        with self._lock:
            current = copy.deepcopy(self._config)
            current.update(updates)

            # Auto-fix and validate
            current = auto_fix_config(current)
            validated, errors = validate_config(current)
            if errors:
                logger.warning("Config update validation warnings:\n%s", "\n".join(errors))

            self._config = validated
            self._notify(validated)

            # Persist if we have a path
            if self._path is not None:
                self._atomic_write(self._path, validated)

            return copy.deepcopy(validated)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level config value, with optional default."""
        with self._lock:
            return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a single config value and persist."""
        self.update({key: value})

    def register_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """
        Register a callback to be called when config changes.

        The callback receives the new configuration dictionary.
        Callbacks are called synchronously within the save/update lock.
        """
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Unregister a previously registered callback."""
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def reload(self) -> dict[str, Any]:
        """
        Reload configuration from disk if the file has been modified.

        Returns:
            The (possibly updated) configuration dictionary.
        """
        if self._path is None or not self._path.exists():
            return self.config

        mtime = os.path.getmtime(self._path)
        if mtime > self._last_loaded:
            logger.info("Config file changed on disk, reloading…")
            return self.load_from_path(self._path)

        return self.config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_with_lock(self, path: Path) -> dict[str, Any]:
        """Read a YAML file with shared file locking."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    data = yaml.safe_load(f) or {}
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            if not isinstance(data, dict):
                logger.warning("Config file %s did not contain a mapping, using defaults", path)
                return {}
            return data
        except Exception as exc:
            logger.error("Failed to read config from %s: %s", path, exc)
            return {}

    def _atomic_write(self, path: Path, data: Mapping[str, Any]) -> None:
        """Write data to path atomically using temp file + rename."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = sanitize_config(data)

        fd, temp_path_str = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=path.suffix,
        )
        temp_path = Path(temp_path_str)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    yaml.dump(
                        payload, f,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            os.replace(temp_path, path)
        except Exception:
            # Clean up temp file on failure
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _notify(self, config: Mapping[str, Any]) -> None:
        """Call all registered callbacks with the new config."""
        snapshot = dict(config)
        for cb in self._callbacks:
            try:
                cb(snapshot)
            except Exception as exc:
                logger.error("Config callback error: %s", exc)


# ---------------------------------------------------------------------------
# Module-level convenience functions (backward compatible)
# ---------------------------------------------------------------------------

# Global singleton for shared access across modules.
_default_store: Optional[ConfigStore] = None


def get_store() -> ConfigStore:
    """Get or create the global ConfigStore singleton."""
    global _default_store
    if _default_store is None:
        _default_store = ConfigStore()
    return _default_store


def reset_store() -> None:
    """Reset the global ConfigStore singleton. Useful for testing."""
    global _default_store
    _default_store = None


def resolve_config_path(requested_path: Path | None = None, *, explicit: bool = False) -> Path:
    """
    Resolve the path to the configuration file.

    Priority:
    1. Explicit path (if explicit=True and path is provided)
    2. Requested path (if it exists)
    3. Project-level config.yaml (next to the package)
    4. User config directory config.yaml

    Args:
        requested_path: Optional path to check.
        explicit: If True, always use requested_path even if it doesn't exist.

    Returns:
        Resolved Path to the configuration file.
    """
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
    """
    Load configuration from a file path (backward-compatible wrapper).

    Merges user config with defaults, auto-fixes legacy keys, migrates
    schema versions, and validates the result.

    Args:
        path: Path to the config file.

    Returns:
        Validated configuration dictionary with a '_config_path' metadata key.
    """
    store = get_store()
    config = store.load_from_path(path)
    config["_config_path"] = str(_normalize_path(path))
    return config


def save_config(config: Mapping[str, Any], path: str | Path) -> Path:
    """
    Save configuration to a file atomically (backward-compatible wrapper).

    Args:
        config: Configuration dictionary to save.
        path: Destination file path.

    Returns:
        The resolved path where the config was saved.
    """
    store = get_store()
    return store.save(config, Path(path))


def sanitize_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """
    Remove internal keys (those starting with '_') from a config dict.

    Args:
        config: Configuration dictionary.

    Returns:
        Cleaned dictionary without internal keys.
    """
    return {key: value for key, value in config.items() if not str(key).startswith("_")}


def user_config_dir() -> Path:
    """
    Return the platform-appropriate user configuration directory.

    Platforms:
    - macOS: ~/Library/Application Support/GramWrite
    - Windows: %APPDATA%/GramWrite or ~/AppData/Roaming/GramWrite
    - Linux: $XDG_CONFIG_HOME/gramwrite or ~/.config/gramwrite

    Returns:
        Path to the user config directory.
    """
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
    """
    Look for a project-level config.yaml next to the package root.

    Returns None when running from a PyInstaller bundle (sys._MEIPASS).

    Returns:
        Path to project config.yaml, or None if not found.
    """
    if hasattr(sys, "_MEIPASS"):
        return None

    package_root = Path(__file__).resolve().parent.parent
    config_path = package_root / "config.yaml"
    if config_path.exists():
        return config_path
    return None


def _normalize_path(path: Path) -> Path:
    """
    Normalize a path: expand user home, resolve to absolute.

    Args:
        path: Input path (may be relative or contain ~).

    Returns:
        Resolved absolute Path.
    """
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (Path.cwd() / expanded).resolve()
