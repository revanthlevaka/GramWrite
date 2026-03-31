"""
watcher.py — Cross-Platform OS-Level Text Watcher
Extracts current text from active screenwriting apps.

macOS  → pyobjc Accessibility API
Windows → uiautomation
Linux  → AT-SPI2 via pyatspi
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from abc import ABC, abstractmethod
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Supported app bundle IDs / process names
SUPPORTED_APPS = {
    "macos": [
        "com.generalcoffee.fadein",         # Fade In (Primary)
        "com.generalkaos.fadein",          # Fade In (Legacy/Alternate)
        "com.screenplay.finaldraft",         # Final Draft
        "com.quoteunquoteapps.highland2",   # Highland 2
        "com.neilsardesai.coppice",          # Fountain editors (misc)
        "net.shinyfrog.bear",                # Bear (Fountain support)
        "md.obsidian",                       # Obsidian (Fountain plugin)
        # Development / testing
        "com.apple.TextEdit",
        "com.sublimetext.4",
        "com.microsoft.VSCode",
    ],
    "windows": [
        "fadein.exe",
        "finaldraft.exe",
        "highland.exe",
        "notepad.exe",          # dev/testing
        "code.exe",
    ],
    "linux": [
        "fadein",
        "fountain",
        "gedit",
        "code",
        "kate",
    ],
}

MAX_EXTRACT_CHARS = 300


class TextExtractor(ABC):
    """Abstract base for platform-specific text extraction."""

    @abstractmethod
    async def get_active_app(self) -> Optional[str]:
        """Return current active app identifier."""
        ...

    @abstractmethod
    async def extract_focused_text(self) -> Optional[str]:
        """Extract ~MAX_EXTRACT_CHARS of text around cursor."""
        ...

    def is_supported_app(self, app_id: Optional[str]) -> bool:
        if not app_id:
            return False
        sys = platform.system().lower()
        key = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(sys, "linux")
        supported = SUPPORTED_APPS.get(key, [])
        app_lower = app_id.lower()
        return any(s.lower() in app_lower or app_lower in s.lower() for s in supported)


# ─── macOS Extractor ─────────────────────────────────────────────────────────


class MacOSExtractor(TextExtractor):
    """
    Uses pyobjc NSAccessibility to read focused element text.
    Requires Accessibility permissions in System Preferences.
    """

    def __init__(self):
        self._ax = None
        self._workspace = None
        self._load_objc()

    def _load_objc(self):
        try:
            import AppKit
            import ApplicationServices

            self._AppKit = AppKit
            self._AS = ApplicationServices
            logger.info("macOS Accessibility API loaded")
        except ImportError:
            logger.warning("pyobjc not available — install with: pip install pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices")

    async def get_active_app(self) -> Optional[str]:
        try:
            app = self._AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            return app.bundleIdentifier()
        except Exception as e:
            logger.debug("get_active_app error: %s", e)
            return None

    async def extract_focused_text(self) -> Optional[str]:
        try:
            # Get focused UI element
            app = self._AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            pid = app.processIdentifier()

            ax_app = self._AS.AXUIElementCreateApplication(pid)

            # Get focused element
            err, focused = self._AS.AXUIElementCopyAttributeValue(
                ax_app, "AXFocusedUIElement", None
            )
            if err != 0 or focused is None:
                return None

            # Try AXSelectedText first (text around cursor)
            err, selected = self._AS.AXUIElementCopyAttributeValue(
                focused, "AXSelectedText", None
            )
            if err == 0 and selected and len(selected.strip()) > 0:
                return selected.strip()[:MAX_EXTRACT_CHARS]

            # Fall back to full value, trim to last N chars
            err, value = self._AS.AXUIElementCopyAttributeValue(
                focused, "AXValue", None
            )
            if err == 0 and value:
                text = str(value)
                # Attempt to get cursor position for smarter extraction
                err2, pos = self._AS.AXUIElementCopyAttributeValue(
                    focused, "AXInsertionPointLineNumber", None
                )
                if err2 == 0 and pos is not None:
                    lines = text.splitlines()
                    line_num = int(pos)
                    start = max(0, line_num - 3)
                    end = min(len(lines), line_num + 1)
                    return "\n".join(lines[start:end])[:MAX_EXTRACT_CHARS]

                return text[-MAX_EXTRACT_CHARS:]

            return None

        except Exception as e:
            logger.debug("extract_focused_text error: %s", e)
            return None


# ─── Windows Extractor ───────────────────────────────────────────────────────


class WindowsExtractor(TextExtractor):
    """
    Uses uiautomation to read focused control text on Windows.
    """

    def __init__(self):
        self._uia = None
        self._load_uia()

    def _load_uia(self):
        try:
            import uiautomation as uia
            self._uia = uia
            logger.info("Windows UIAutomation loaded")
        except ImportError:
            logger.warning("uiautomation not available — install with: pip install uiautomation")

    async def get_active_app(self) -> Optional[str]:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            import psutil
            proc = psutil.Process(pid.value)
            return proc.name()
        except Exception as e:
            logger.debug("get_active_app error: %s", e)
            return None

    async def extract_focused_text(self) -> Optional[str]:
        if not self._uia:
            return None
        try:
            focused = self._uia.GetFocusedControl()
            if focused is None:
                return None

            ctrl_type = focused.ControlTypeName
            if ctrl_type in ("EditControl", "DocumentControl", "TextControl"):
                text = focused.GetValuePattern().Value
                if text:
                    return text[-MAX_EXTRACT_CHARS:]

                # Try text pattern
                try:
                    tp = focused.GetTextPattern()
                    doc_range = tp.DocumentRange
                    return doc_range.GetText(MAX_EXTRACT_CHARS)
                except Exception as e:
                    logger.debug("extract_focused_text text pattern error: %s", e)

            return None
        except Exception as e:
            logger.debug("extract_focused_text error: %s", e)
            return None


# ─── Linux Extractor ─────────────────────────────────────────────────────────


class LinuxExtractor(TextExtractor):
    """
    Uses AT-SPI2 accessibility stack on Linux (GNOME/KDE).
    Falls back to xdotool + xclip clipboard trick if AT-SPI unavailable.
    """

    def __init__(self):
        self._atspi = None
        self._load_atspi()

    def _load_atspi(self):
        try:
            import pyatspi
            self._atspi = pyatspi
            logger.info("AT-SPI2 loaded")
        except ImportError:
            logger.warning("pyatspi not available — install with: pip install pyatspi")

    async def get_active_app(self) -> Optional[str]:
        try:
            import subprocess  # nosec B404
            result = subprocess.run(  # nosec B603 B607
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    async def extract_focused_text(self) -> Optional[str]:
        if self._atspi:
            return await self._extract_via_atspi()
        return await self._extract_via_clipboard()

    async def _extract_via_atspi(self) -> Optional[str]:
        try:
            desktop = self._atspi.Registry.getDesktop(0)
            for app in desktop:
                for window in app:
                    focused = self._atspi.findFocused(window)
                    if focused:
                        text_iface = focused.queryText()
                        if text_iface:
                            length = text_iface.characterCount
                            start = max(0, length - MAX_EXTRACT_CHARS)
                            return text_iface.getText(start, length)
        except Exception as e:
            logger.debug("AT-SPI2 extraction error: %s", e)
        return None

    async def _extract_via_clipboard(self) -> Optional[str]:
        """
        Fallback: simulate Ctrl+C, read clipboard.
        Intrusive — only used if AT-SPI unavailable.
        """
        try:
            import subprocess  # nosec B404
            # Get selection via xclip
            result = subprocess.run(  # nosec B603 B607
                ["xclip", "-o", "-selection", "primary"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[-MAX_EXTRACT_CHARS:]
        except Exception as e:
            logger.debug("clipboard fallback error: %s", e)
        return None


# ─── Null Extractor (fallback) ────────────────────────────────────────────────


class NullExtractor(TextExtractor):
    """Used when platform is unrecognized or deps unavailable."""

    async def get_active_app(self) -> Optional[str]:
        return None

    async def extract_focused_text(self) -> Optional[str]:
        return None


# ─── Watcher ─────────────────────────────────────────────────────────────────


class Watcher:
    """
    Main text watcher. Polls for active app + text changes.
    Calls callback with extracted text after debounce period.

    callback signature: async def on_text(text: str) -> None
    """

    def __init__(self, config: dict, callback: Callable):
        self.config = config
        self.callback = callback
        self.debounce_secs: float = config.get("debounce_seconds", 2.0)
        self._extractor = self._build_extractor()
        self._last_text: str = ""
        self._last_change_time: float = 0.0
        self._pending_task: Optional[asyncio.Task] = None
        self._running = False
        self._fired = False

    def _build_extractor(self) -> TextExtractor:
        sys = platform.system()
        if sys == "Darwin":
            return MacOSExtractor()
        elif sys == "Windows":
            return WindowsExtractor()
        elif sys == "Linux":
            return LinuxExtractor()
        else:
            logger.warning("Unsupported platform: %s", sys)
            return NullExtractor()

    async def run(self):
        """Main polling loop. Runs until stopped."""
        self._running = True
        logger.info("Watcher started (debounce=%.1fs)", self.debounce_secs)

        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.exception("Watcher tick error: %s", e)
            await asyncio.sleep(0.25)  # 250ms polling interval

    async def _tick(self):
        app_id = await self._extractor.get_active_app()

        if not self._extractor.is_supported_app(app_id):
            return

        text = await self._extractor.extract_focused_text()
        if not text or not text.strip():
            return

        text = text.strip()

        if text == self._last_text:
            # Text unchanged — check if debounce window has elapsed
            elapsed = time.monotonic() - self._last_change_time
            if (
                self._last_change_time > 0
                and elapsed >= self.debounce_secs
                and not self._pending_fired
            ):
                self._pending_fired = True
                asyncio.create_task(self.callback(text))
        else:
            # Text changed — reset debounce timer
            self._last_text = text
            self._last_change_time = time.monotonic()
            self._pending_fired = False

    def stop(self):
        self._running = False
        logger.info("Watcher stopped")

    @property
    def _pending_fired(self) -> bool:
        return getattr(self, "_fired", False)

    @_pending_fired.setter
    def _pending_fired(self, value: bool):
        self._fired = value
