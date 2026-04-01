"""
harper.py — Harper grammar checker bridge
Uses a tiny Node helper around harper.js so GramWrite can run Harper locally.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HARPER_BACKEND_KEY = "harper"
HARPER_MODEL_ID = "harper.english"
HARPER_MODEL_LABEL = "Harper (English)"
HELPER_DIR_NAME = "harper"
HELPER_SCRIPT_NAME = "gramwrite-harper.mjs"


@dataclass
class HarperStatus:
    supported: bool
    available: bool
    reason: Optional[str] = None
    helper_path: Optional[Path] = None
    node_path: Optional[str] = None

    @property
    def usable(self) -> bool:
        return (
            self.supported
            and self.available
            and self.helper_path is not None
            and self.node_path is not None
        )


class HarperBridge:
    """
    Bridge between Python and the Harper Node helper.
    """

    def __init__(self):
        self._cached_status: Optional[HarperStatus] = None
        self._cached_at = 0.0

    async def status(self, force_refresh: bool = False) -> HarperStatus:
        if (
            not force_refresh
            and self._cached_status is not None
            and time.monotonic() - self._cached_at < 5
        ):
            return self._cached_status

        helper_path = self._find_helper_script()
        if helper_path is None:
            status = HarperStatus(
                supported=True,
                available=False,
                reason="Harper helper files are missing from this build.",
            )
            self._remember(status)
            return status

        node_path = self._find_node()
        if node_path is None:
            status = HarperStatus(
                supported=True,
                available=False,
                reason="Node.js is required for the Harper backend.",
                helper_path=helper_path,
            )
            self._remember(status)
            return status

        stdout, stderr, returncode = await self._run_helper(
            node_path,
            helper_path,
            "status",
            timeout=20,
        )
        if returncode != 0:
            status = HarperStatus(
                supported=True,
                available=False,
                reason=stderr or "Harper helper failed to report availability.",
                helper_path=helper_path,
                node_path=node_path,
            )
            self._remember(status)
            return status

        try:
            data = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            status = HarperStatus(
                supported=True,
                available=False,
                reason="Harper helper returned invalid JSON.",
                helper_path=helper_path,
                node_path=node_path,
            )
            self._remember(status)
            return status

        status = HarperStatus(
            supported=bool(data.get("supported", True)),
            available=bool(data.get("available", False)),
            reason=data.get("reason"),
            helper_path=helper_path,
            node_path=node_path,
        )
        self._remember(status)
        return status

    async def correct(self, text: str) -> str:
        status = await self.status()
        if not status.usable:
            raise RuntimeError(status.reason or "Harper is unavailable.")

        request = {
            "text": text,
        }
        stdout, stderr, returncode = await self._run_helper(
            status.node_path,
            status.helper_path,
            "correct",
            stdin_text=json.dumps(request),
            timeout=30,
        )
        if returncode != 0:
            raise RuntimeError(stderr or "Harper helper failed during correction.")

        try:
            data = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Harper helper returned invalid JSON.") from exc

        if not data.get("ok", False):
            raise RuntimeError(data.get("error") or "Harper helper reported an unknown error.")

        if not data.get("hasCorrection", False):
            return "NO_CORRECTION"

        return str(data.get("correction", "")).strip()

    async def list_models(self) -> list[str]:
        status = await self.status()
        return [HARPER_MODEL_ID] if status.available else []

    def _remember(self, status: HarperStatus):
        self._cached_status = status
        self._cached_at = time.monotonic()

    async def _run_helper(
        self,
        node_path: str,
        helper_path: Path,
        command: str,
        stdin_text: Optional[str] = None,
        timeout: int = 20,
    ) -> tuple[str, str, int]:
        process = await asyncio.create_subprocess_exec(
            node_path,
            str(helper_path),
            command,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(
                    stdin_text.encode("utf-8") if stdin_text is not None else None
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Harper timed out.")

        return stdout.decode("utf-8").strip(), stderr.decode("utf-8").strip(), process.returncode

    def _find_node(self) -> Optional[str]:
        env_override = os.environ.get("GRAMWRITE_HARPER_NODE")
        if env_override:
            return env_override

        return shutil.which("node") or shutil.which("nodejs")

    def _find_helper_script(self) -> Optional[Path]:
        env_override = os.environ.get("GRAMWRITE_HARPER_HELPER")
        if env_override:
            candidate = Path(env_override)
            if candidate.exists():
                return candidate

        for candidate in self._helper_script_candidates():
            if candidate.exists():
                return candidate
        return None

    def _helper_script_candidates(self) -> list[Path]:
        package_dir = Path(__file__).resolve().parent
        candidates: list[Path] = []

        for root in self._frozen_roots():
            candidates.extend(
                [
                    root / "gramwrite" / "native" / HELPER_DIR_NAME / HELPER_SCRIPT_NAME,
                    root / "native" / HELPER_DIR_NAME / HELPER_SCRIPT_NAME,
                ]
            )

        candidates.extend(
            [
                package_dir / "native" / HELPER_DIR_NAME / HELPER_SCRIPT_NAME,
                package_dir.parent / "gramwrite" / "native" / HELPER_DIR_NAME / HELPER_SCRIPT_NAME,
            ]
        )
        return candidates

    @staticmethod
    def _frozen_roots() -> list[Path]:
        if not hasattr(sys, "_MEIPASS"):
            return []

        meipass = Path(sys._MEIPASS)
        candidates = [
            meipass,
            meipass.parent / "Resources",
            meipass.parent / "Frameworks",
        ]
        unique_roots: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            unique_roots.append(candidate)
        return unique_roots
