"""
__main__.py — GramWrite entry point
Run with: python -m gramwrite
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from . import __version__


def load_config(path: Path) -> dict:
    """Load config.yaml, fall back to defaults if missing."""
    defaults = {
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

    if path.exists():
        try:
            with open(path) as f:
                user_config = yaml.safe_load(f) or {}
            defaults.update(user_config)
        except Exception as e:
            print(f"Warning: Could not read {path}: {e}", file=sys.stderr)

    defaults["_config_path"] = str(path)
    return defaults


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy third-party loggers
    for noisy in ("aiohttp", "asyncio", "PyQt6"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def main():
    parser = argparse.ArgumentParser(
        prog="gramwrite",
        description="GramWrite — Invisible Editor for Screenwriters",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config.yaml (default: ./config.yaml)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Open settings dashboard on startup",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"GramWrite {__version__}",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Dashboard port (default: 7878, set in config.yaml)",
    )
    parser.add_argument(
        "--self-test-text",
        default=None,
        help="Run one correction request with the configured backend and print JSON, then exit.",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)
    config = load_config(args.config)

    if args.port is not None:
        config["dashboard_port"] = args.port

    if args.self_test_text:
        from .engine import GramEngine

        async def run_self_test() -> int:
            engine = GramEngine(config)
            try:
                result = await engine.correct(args.self_test_text)
            finally:
                await engine.close()

            print(
                json.dumps(
                    {
                        "backend": result.backend.value,
                        "has_correction": result.has_correction,
                        "correction": result.correction,
                        "error": result.error,
                        "latency_ms": round(result.latency_ms, 2),
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if result.error is None else 1

        return asyncio.run(run_self_test())

    from .app import run_app
    run_app(config, show_dashboard=args.dashboard)


if __name__ == "__main__":
    main()
