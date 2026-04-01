"""
foundation_models.py — Apple Foundation Models bridge
Uses a tiny Swift helper to access Apple's on-device language model on macOS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess  # nosec B404 - required for fixed local helper build/sign commands on macOS
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FOUNDATION_BACKEND_KEY = "foundation_models"
FOUNDATION_MODEL_ID = "apple.foundation"
FOUNDATION_MODEL_LABEL = "Apple Foundation Models"
HELPER_BINARY_NAME = "gramwrite-foundation-models"
HELPER_SOURCE_NAME = "GramWriteFoundationModels.swift"
HELPER_APP_NAME = "GramWriteFoundationModelsHelper.app"
HELPER_BUNDLE_ID = "com.revanthlevaka.gramwrite.foundationmodels"


@dataclass
class FoundationModelsStatus:
    supported: bool
    available: bool
    reason: Optional[str] = None
    helper_path: Optional[Path] = None

    @property
    def usable(self) -> bool:
        return self.supported and self.available and self.helper_path is not None


class FoundationModelsBridge:
    """
    Bridge between Python and the Foundation Models Swift helper.
    """

    def __init__(self):
        self._cached_status: Optional[FoundationModelsStatus] = None
        self._cached_at = 0.0

    async def status(self, force_refresh: bool = False) -> FoundationModelsStatus:
        if (
            not force_refresh
            and self._cached_status is not None
            and time.monotonic() - self._cached_at < 5
        ):
            return self._cached_status

        if sys.platform != "darwin":
            status = FoundationModelsStatus(
                supported=False,
                available=False,
                reason="Apple Foundation Models are available on macOS only.",
            )
            self._remember(status)
            return status

        helper_path, build_error = self._ensure_helper()
        if helper_path is None:
            status = FoundationModelsStatus(
                supported=True,
                available=False,
                reason=build_error or "Foundation Models helper is not available in this build.",
            )
            self._remember(status)
            return status

        payload, stderr, returncode = await self._run_helper(
            helper_path,
            "status",
            timeout=10,
        )
        if returncode != 0:
            status = FoundationModelsStatus(
                supported=True,
                available=False,
                reason=stderr or "Foundation Models helper failed to report availability.",
                helper_path=helper_path,
            )
            self._remember(status)
            return status

        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            status = FoundationModelsStatus(
                supported=True,
                available=False,
                reason="Foundation Models helper returned invalid JSON.",
                helper_path=helper_path,
            )
            self._remember(status)
            return status

        status = FoundationModelsStatus(
            supported=bool(data.get("supported", True)),
            available=bool(data.get("available", False)),
            reason=data.get("reason"),
            helper_path=helper_path,
        )
        self._remember(status)
        return status

    async def correct(self, text: str, instructions: str) -> str:
        status = await self.status()
        if not status.usable:
            raise RuntimeError(status.reason or "Apple Foundation Models are unavailable.")

        request = {
            "text": text,
            "instructions": instructions,
        }
        stdout, stderr, returncode = await self._run_helper(
            status.helper_path,
            "correct",
            stdin_text=json.dumps(request),
            timeout=30,
        )

        if returncode != 0:
            raise RuntimeError(stderr or "Foundation Models helper failed during correction.")

        try:
            data = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("Foundation Models helper returned invalid JSON.") from exc

        if not data.get("ok", False):
            raise RuntimeError(data.get("error") or "Foundation Models helper reported an unknown error.")

        if not data.get("hasCorrection", False):
            return "NO_CORRECTION"

        return str(data.get("correction", "")).strip()

    async def list_models(self) -> list[str]:
        status = await self.status()
        return [FOUNDATION_MODEL_ID] if status.available else []

    def _remember(self, status: FoundationModelsStatus):
        self._cached_status = status
        self._cached_at = time.monotonic()

    async def _run_helper(
        self,
        helper_path: Path,
        command: str,
        stdin_text: Optional[str] = None,
        timeout: int = 20,
    ) -> tuple[str, str, int]:
        process = await asyncio.create_subprocess_exec(
            str(helper_path),
            command,
            stdin=asyncio.subprocess.PIPE if stdin_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(stdin_text.encode("utf-8") if stdin_text is not None else None),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError("Apple Foundation Models timed out.")

        return stdout.decode("utf-8").strip(), stderr.decode("utf-8").strip(), process.returncode

    def _ensure_helper(self) -> tuple[Optional[Path], Optional[str]]:
        helper_path = self._find_helper_binary()
        if helper_path is not None:
            return helper_path, None

        source_path = self._find_helper_source()
        if source_path is None:
            return None, "Foundation Models helper source is missing."

        if shutil.which("xcrun") is None:
            return None, "xcrun is not installed, so the Foundation Models helper cannot be built locally."

        bundle_path = self._local_build_bundle()
        executable_path = bundle_path / "Contents" / "MacOS" / HELPER_BINARY_NAME
        executable_path.parent.mkdir(parents=True, exist_ok=True)
        (bundle_path / "Contents").mkdir(parents=True, exist_ok=True)
        self._write_info_plist(bundle_path)

        cache_root = Path(tempfile.mkdtemp(prefix="gramwrite-swift-cache-"))
        env = os.environ.copy()
        env["SWIFT_MODULECACHE_PATH"] = str(cache_root / "swift")
        env["CLANG_MODULE_CACHE_PATH"] = str(cache_root / "clang")

        command = [
            "xcrun",
            "swiftc",
            "-parse-as-library",
            str(source_path),
            "-o",
            str(executable_path),
        ]
        try:
            completed = subprocess.run(  # nosec B603 - fixed command list, no shell, local bundled helper source
                command,
                capture_output=True,
                text=True,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            logger.warning("Could not build Foundation Models helper: %s", detail)
            return None, detail

        if completed.stderr.strip():
            logger.info("Foundation Models helper build output: %s", completed.stderr.strip())

        executable_path.chmod(0o755)

        sign_command = [
            "/usr/bin/codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            str(bundle_path),
        ]
        try:
            subprocess.run(  # nosec B603 - fixed codesign invocation for the local helper bundle, no shell
                sign_command,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or exc.stdout.strip() or str(exc)
            logger.warning("Could not sign Foundation Models helper app bundle: %s", detail)
            return None, detail

        return executable_path, None

    def _find_helper_binary(self) -> Optional[Path]:
        for candidate in self._helper_binary_candidates():
            if candidate.exists() and os.access(candidate, os.X_OK):
                return candidate
        return None

    def _find_helper_source(self) -> Optional[Path]:
        for candidate in self._helper_source_candidates():
            if candidate.exists():
                return candidate
        return None

    def _helper_binary_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        package_dir = Path(__file__).resolve().parent

        for root in self._frozen_roots():
            candidates.extend(
                [
                    root / "gramwrite" / "native" / HELPER_APP_NAME / "Contents" / "MacOS" / HELPER_BINARY_NAME,
                    root / "native" / HELPER_APP_NAME / "Contents" / "MacOS" / HELPER_BINARY_NAME,
                ]
            )

        candidates.extend(
            [
                package_dir / "native" / HELPER_APP_NAME / "Contents" / "MacOS" / HELPER_BINARY_NAME,
                self._local_build_bundle() / "Contents" / "MacOS" / HELPER_BINARY_NAME,
            ]
        )
        return candidates

    def _helper_source_candidates(self) -> list[Path]:
        package_dir = Path(__file__).resolve().parent
        project_root = package_dir.parent
        candidates: list[Path] = []
        for root in self._frozen_roots():
            candidates.extend(
                [
                    root / "gramwrite" / "native" / HELPER_SOURCE_NAME,
                    root / "native" / HELPER_SOURCE_NAME,
                ]
            )
        candidates.extend(
            [
                package_dir / "native" / HELPER_SOURCE_NAME,
                project_root / "gramwrite" / "native" / HELPER_SOURCE_NAME,
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

    @staticmethod
    def _local_build_bundle() -> Path:
        return Path(tempfile.gettempdir()) / "gramwrite-foundation-models" / HELPER_APP_NAME

    @staticmethod
    def _write_info_plist(bundle_path: Path):
        plist_path = bundle_path / "Contents" / "Info.plist"
        plist_path.write_text(
            (
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
                "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
                "<plist version=\"1.0\">\n"
                "<dict>\n"
                f"  <key>CFBundleExecutable</key><string>{HELPER_BINARY_NAME}</string>\n"
                f"  <key>CFBundleIdentifier</key><string>{HELPER_BUNDLE_ID}</string>\n"
                "  <key>CFBundleName</key><string>GramWrite Foundation Models Helper</string>\n"
                "  <key>CFBundlePackageType</key><string>APPL</string>\n"
                "  <key>LSMinimumSystemVersion</key><string>15.1</string>\n"
                "</dict>\n"
                "</plist>\n"
            ),
            encoding="utf-8",
        )
