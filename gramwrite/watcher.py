"""
watcher.py — Cross-Platform OS-Level Text Watcher
Extracts current text from active screenwriting applications.

macOS  → PyObjC Accessibility API with key fallback
Windows → uiautomation with clipboard fallback
Linux  → AT-SPI2 via pyatspi with xdotool fallback

Architecture:
- Abstract base class for platform watchers
- Platform-specific implementations
- Clean callback interface
- Thread-safe operations
- Proper async support
"""

from __future__ import annotations

import asyncio
import logging
import platform
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from typing import Callable, Optional, List, Tuple

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
POLLING_INTERVAL = 0.25  # 250ms polling interval
BUFFER_TTL = 12.0  # seconds
BUFFER_MAX_CHARS = 800


class TypedTextBuffer:
    """
    Thread-safe rolling buffer of recently typed text for fallback capture.
    
    Features:
    - Thread-safe operations via threading.Lock
    - Proper TTL (time-to-live) handling
    - App change detection and buffer reset
    - Backspace handling
    - Character limit enforcement
    - Snapshot retrieval with validation
    """

    def __init__(self, max_chars: int = BUFFER_MAX_CHARS, ttl_secs: float = BUFFER_TTL):
        """
        Initialize the typed text buffer.
        
        Args:
            max_chars: Maximum number of characters to retain in buffer
            ttl_secs: Time-to-live in seconds before buffer expires
        """
        self._max_chars = max_chars
        self._ttl_secs = ttl_secs
        self._buffer = ""
        self._app_id: Optional[str] = None
        self._updated_at = 0.0
        self._lock = threading.Lock()

    def record_text(self, app_id: str, text: str) -> None:
        """
        Record newly typed text into the buffer.
        
        Args:
            app_id: Application identifier that generated the text
            text: The text content to record
        """
        if not text:
            return
        with self._lock:
            self._reset_if_app_changed(app_id)
            self._buffer = (self._buffer + text)[-self._max_chars:]
            self._updated_at = time.monotonic()

    def record_backspace(self, app_id: str, count: int = 1) -> None:
        """
        Record backspace operations to maintain buffer accuracy.
        
        Args:
            app_id: Application identifier where backspace occurred
            count: Number of characters to remove (default: 1)
        """
        with self._lock:
            self._reset_if_app_changed(app_id)
            if count > 0:
                self._buffer = self._buffer[:-count]
            self._updated_at = time.monotonic()

    def snapshot(self, app_id: Optional[str]) -> Optional[str]:
        """
        Get a snapshot of the current buffer if valid.
        
        Args:
            app_id: Application identifier to validate against
            
        Returns:
            Buffer content if valid, None otherwise
        """
        with self._lock:
            if not app_id or self._app_id != app_id:
                return None
            if self._updated_at <= 0 or (time.monotonic() - self._updated_at) > self._ttl_secs:
                return None
            text = self._buffer.strip()
            if not text:
                return None
            return text[-MAX_EXTRACT_CHARS:]

    def clear(self) -> None:
        """Clear the buffer and reset all state."""
        with self._lock:
            self._buffer = ""
            self._app_id = None
            self._updated_at = 0.0

    def _reset_if_app_changed(self, app_id: str) -> None:
        """
        Reset buffer if the application has changed.
        
        Args:
            app_id: Current application identifier
        """
        if self._app_id != app_id:
            self._app_id = app_id
            self._buffer = ""

    @property
    def is_empty(self) -> bool:
        """Check if the buffer is empty."""
        with self._lock:
            return len(self._buffer) == 0

    @property
    def age(self) -> float:
        """Get the age of the buffer in seconds."""
        with self._lock:
            if self._updated_at <= 0:
                return float('inf')
            return time.monotonic() - self._updated_at


class ClipboardMonitor:
    """
    Cross-platform clipboard monitoring for fallback text extraction.
    
    Monitors clipboard changes and provides recent clipboard content
    as a fallback when primary extraction methods fail.
    """

    def __init__(self, max_chars: int = MAX_EXTRACT_CHARS):
        """
        Initialize clipboard monitor.
        
        Args:
            max_chars: Maximum characters to retain from clipboard
        """
        self._max_chars = max_chars
        self._last_content = ""
        self._updated_at = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start clipboard monitoring in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Clipboard monitor started")

    def stop(self) -> None:
        """Stop clipboard monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Clipboard monitor stopped")

    def get_content(self) -> Optional[str]:
        """
        Get recent clipboard content if available.
        
        Returns:
            Clipboard content if recent, None otherwise
        """
        with self._lock:
            if not self._last_content:
                return None
            if time.monotonic() - self._updated_at > 5.0:  # 5 second TTL
                return None
            return self._last_content[-self._max_chars:]

    def _monitor_loop(self) -> None:
        """Background loop to monitor clipboard changes."""
        while self._running:
            try:
                content = self._read_clipboard()
                if content and content != self._last_content:
                    with self._lock:
                        self._last_content = content[-self._max_chars:]
                        self._updated_at = time.monotonic()
            except Exception as e:
                logger.debug("Clipboard monitor error: %s", e)
            time.sleep(0.5)  # Check every 500ms

    def _read_clipboard(self) -> Optional[str]:
        """Read current clipboard content."""
        try:
            import subprocess
            system = platform.system()
            
            if system == "Darwin":
                result = subprocess.run(
                    ["pbpaste"],
                    capture_output=True, text=True, timeout=2
                )
            elif system == "Windows":
                result = subprocess.run(
                    ["powershell", "-command", "Get-Clipboard"],
                    capture_output=True, text=True, timeout=2
                )
            else:  # Linux
                result = subprocess.run(
                    ["xclip", "-o", "-selection", "clipboard"],
                    capture_output=True, text=True, timeout=2
                )
            
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None


class MacOSKeyFallback:
    """
    Listen for typed characters when Accessibility cannot read the editor value.
    
    Uses Quartz Event Taps to capture keyboard events at the system level.
    Requires Input Monitoring permission in System Preferences.
    """

    _DELETE_KEYCODE = 51
    _RETURN_KEYCODES = {36, 76}

    def __init__(self, app_checker: Callable[[Optional[str]], bool]):
        """
        Initialize macOS key fallback.
        
        Args:
            app_checker: Function to check if app is supported
        """
        self._app_checker = app_checker
        self._buffer = TypedTextBuffer()
        self._tap = None
        self._thread: Optional[threading.Thread] = None
        self._Quartz = None
        self._AppKit = None
        self._load_dependencies()
        self._start()

    def snapshot(self, app_id: Optional[str]) -> Optional[str]:
        """Get snapshot from typed text buffer."""
        return self._buffer.snapshot(app_id)

    def _load_dependencies(self) -> None:
        """Load PyObjC dependencies."""
        try:
            import AppKit
            import Quartz

            self._AppKit = AppKit
            self._Quartz = Quartz
        except ImportError:
            logger.debug("Quartz/AppKit not available for macOS key fallback")

    def _start(self) -> None:
        """Start the event tap in a background thread."""
        if not self._Quartz or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        """Run the CoreFoundation run loop with event tap."""
        mask = self._Quartz.CGEventMaskBit(self._Quartz.kCGEventKeyDown)
        self._tap = self._Quartz.CGEventTapCreate(
            self._Quartz.kCGSessionEventTap,
            self._Quartz.kCGHeadInsertEventTap,
            self._Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._event_callback,
            None,
        )
        if not self._tap:
            logger.warning("Could not start macOS key fallback; Input Monitoring permission may be missing.")
            return

        source = self._Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        run_loop = self._Quartz.CFRunLoopGetCurrent()
        self._Quartz.CFRunLoopAddSource(run_loop, source, self._Quartz.kCFRunLoopCommonModes)
        self._Quartz.CGEventTapEnable(self._tap, True)
        self._Quartz.CFRunLoopRun()

    def _event_callback(self, _proxy, event_type, event, _refcon):
        """Handle incoming keyboard events."""
        if event_type in (
            self._Quartz.kCGEventTapDisabledByTimeout,
            self._Quartz.kCGEventTapDisabledByUserInput,
        ):
            if self._tap is not None:
                self._Quartz.CGEventTapEnable(self._tap, True)
            return event

        if event_type == self._Quartz.kCGEventKeyDown:
            self._handle_key_down(event)

        return event

    def _handle_key_down(self, event) -> None:
        """Process a key down event."""
        app_id = self._frontmost_supported_app_id()
        if app_id is None:
            return

        flags = self._Quartz.CGEventGetFlags(event)
        if flags & (
            self._Quartz.kCGEventFlagMaskCommand
            | self._Quartz.kCGEventFlagMaskControl
        ):
            return

        keycode = int(
            self._Quartz.CGEventGetIntegerValueField(
                event,
                self._Quartz.kCGKeyboardEventKeycode,
            )
        )
        if keycode == self._DELETE_KEYCODE:
            self._buffer.record_backspace(app_id)
            return
        if keycode in self._RETURN_KEYCODES:
            self._buffer.record_text(app_id, "\n")
            return

        try:
            count, text = self._Quartz.CGEventKeyboardGetUnicodeString(event, 8, None, None)
        except Exception:
            return

        if not text:
            return

        text = text[:count]
        if not text or any(ord(char) < 32 and char not in ("\n", "\t") for char in text):
            return

        self._buffer.record_text(app_id, text)

    def _frontmost_supported_app_id(self) -> Optional[str]:
        """Get bundle ID of frontmost supported app."""
        try:
            app = self._AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            app_id = app.bundleIdentifier()
        except Exception:
            return None
        if self._app_checker(app_id):
            return app_id
        return None


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
        """
        Check if the given app ID is a supported screenwriting application.
        
        Args:
            app_id: Application identifier to check
            
        Returns:
            True if app is supported, False otherwise
        """
        if not app_id:
            return False
        sys = platform.system().lower()
        key = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(sys, "linux")
        supported = SUPPORTED_APPS.get(key, [])
        app_lower = app_id.lower()
        return any(s.lower() in app_lower or app_lower in s.lower() for s in supported)

    async def extract_with_fallback(self) -> Optional[str]:
        """
        Attempt text extraction with platform-specific fallbacks.
        
        Returns:
            Extracted text or None if all methods fail
        """
        # Primary extraction method
        text = await self.extract_focused_text()
        if text:
            return text
        
        # Platform-specific fallbacks will be implemented by subclasses
        return None


# ─── macOS Extractor ─────────────────────────────────────────────────────────


class MacOSExtractor(TextExtractor):
    """
    Uses PyObjC NSAccessibility to read focused element text.
    
    Features:
    - PyObjC Accessibility API integration
    - Support for Fade In, Final Draft, Highland 2
    - Bundle ID detection
    - Text extraction from focused element
    - Handle permission prompts gracefully
    - Key fallback for when Accessibility API fails
    
    Requires Accessibility permissions in System Preferences.
    """

    _TEXT_ROLES = {
        "AXDocument",
        "AXStaticText",
        "AXTextArea",
        "AXTextField",
        "AXTextView",
        "AXWebArea",
    }
    _CHILD_ATTRIBUTES = (
        "AXChildren",
        "AXChildrenInNavigationOrder",
        "AXContents",
        "AXSections",
        "AXVisibleChildren",
    )
    _SEARCH_NODE_LIMIT = 200
    _PREFERRED_TEXT_ROLES = {
        "AXDocument",
        "AXTextArea",
        "AXTextField",
        "AXTextView",
        "AXWebArea",
    }

    def __init__(self):
        """Initialize macOS extractor with Accessibility API and fallbacks."""
        self._ax = None
        self._workspace = None
        self._cached_pid: Optional[int] = None
        self._cached_text_element = None
        self._permission_granted: Optional[bool] = None
        self._load_objc()
        self._typed_fallback = MacOSKeyFallback(self.is_supported_app)

    def _load_objc(self) -> None:
        """Load PyObjC frameworks for Accessibility API."""
        try:
            import AppKit
            import ApplicationServices

            self._AppKit = AppKit
            self._AS = ApplicationServices
            logger.info("macOS Accessibility API loaded")
        except ImportError:
            logger.warning("pyobjc not available — install with: pip install pyobjc-framework-Cocoa pyobjc-framework-ApplicationServices")

    def _check_accessibility_permission(self) -> bool:
        """
        Check if Accessibility permission is granted.
        
        Returns:
            True if permission granted, False otherwise
        """
        if self._permission_granted is not None:
            return self._permission_granted
        
        try:
            import ApplicationServices
            self._permission_granted = ApplicationServices.AXIsProcessTrusted()
            return self._permission_granted
        except Exception:
            self._permission_granted = False
            return False

    async def get_active_app(self) -> Optional[str]:
        """
        Get the bundle identifier of the frontmost application.
        
        Returns:
            Bundle ID string or None if unavailable
        """
        try:
            app = self._AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            return app.bundleIdentifier()
        except Exception as e:
            logger.debug("get_active_app error: %s", e)
            return None

    async def extract_focused_text(self) -> Optional[str]:
        """
        Extract text from the currently focused UI element.
        
        Returns:
            Extracted text or None if extraction fails
        """
        if not self._check_accessibility_permission():
            logger.debug("Accessibility permission not granted")
            return self._typed_fallback.snapshot(None)
        
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

            target = self._resolve_text_element(pid, focused)
            if target is None:
                return None

            role = self._read_attribute(target, "AXRole")
            text = self._extract_text_from_element(target)
            if self._looks_like_editor_text(role, text):
                return text

            fallback = self._typed_fallback.snapshot(app.bundleIdentifier())
            if fallback:
                return fallback

            return None

        except Exception as e:
            logger.debug("extract_focused_text error: %s", e)
            return None

    def _resolve_text_element(self, pid: int, focused) -> Optional:
        """
        Resolve the actual text element from a focused UI element.
        
        Args:
            pid: Process ID of the application
            focused: The focused UI element
            
        Returns:
            Text element or None if not found
        """
        if self._cached_pid != pid:
            self._cached_pid = pid
            self._cached_text_element = None

        if self._cached_text_element and self._element_has_text(self._cached_text_element):
            return self._cached_text_element

        target = focused
        if not self._element_has_text(target):
            target = self._find_text_descendant(focused)

        if target is None:
            return None

        self._cached_text_element = target
        return target

    def _extract_text_from_element(self, element) -> Optional[str]:
        """
        Extract text content from a UI element.
        
        Args:
            element: The UI element to extract from
            
        Returns:
            Extracted text or None
        """
        selected = self._read_attribute(element, "AXSelectedText")
        if isinstance(selected, str) and selected.strip():
            return selected.strip()[:MAX_EXTRACT_CHARS]

        selected_range = self._read_range_attribute(element, "AXSelectedTextRange")
        if selected_range is not None:
            snippet = self._read_text_for_range(element, *selected_range)
            if snippet:
                return snippet

        visible_range = self._read_range_attribute(element, "AXVisibleCharacterRange")
        if visible_range is not None:
            snippet = self._read_parameterized_range(
                element,
                "AXStringForRange",
                visible_range[0],
                min(visible_range[1], MAX_EXTRACT_CHARS),
            )
            if snippet:
                return snippet

        value = self._read_attribute(element, "AXValue")
        if value:
            text = str(value)
            if selected_range is not None:
                return self._slice_text_around_range(text, *selected_range)
            if visible_range is not None:
                return self._slice_text_around_range(text, *visible_range)

            # Attempt to get cursor position for smarter extraction
            pos = self._read_attribute(element, "AXInsertionPointLineNumber")
            if pos is not None:
                lines = text.splitlines()
                line_num = int(pos)
                start = max(0, line_num - 3)
                end = min(len(lines), line_num + 1)
                return "\n".join(lines[start:end])[:MAX_EXTRACT_CHARS]

            return text[-MAX_EXTRACT_CHARS:]

        return None

    def _find_text_descendant(self, root) -> Optional:
        """
        Find a text-containing descendant element via BFS.
        
        Args:
            root: Root element to search from
            
        Returns:
            First text element found or None
        """
        queue = list(self._iter_children(root))
        seen = {repr(root)}
        searched = 0

        while queue and searched < self._SEARCH_NODE_LIMIT:
            current = queue.pop(0)
            marker = repr(current)
            if marker in seen:
                continue
            seen.add(marker)
            searched += 1

            if self._element_has_text(current):
                logger.debug("macOS extractor descended to text element after %d nodes", searched)
                return current

            queue.extend(self._iter_children(current))

        return None

    def _iter_children(self, element):
        """Iterate over child elements."""
        for attr in self._CHILD_ATTRIBUTES:
            children = self._read_attribute(element, attr)
            if not children:
                continue
            try:
                for child in list(children):
                    yield child
            except TypeError:
                continue

    def _element_has_text(self, element) -> bool:
        """Check if an element contains text content."""
        role = self._read_attribute(element, "AXRole")
        if isinstance(role, str) and role in self._PREFERRED_TEXT_ROLES:
            return True

        selected = self._read_attribute(element, "AXSelectedText")
        if self._looks_like_editor_text(role, selected):
            return True

        if (
            self._read_range_attribute(element, "AXSelectedTextRange") is not None
            and role in self._PREFERRED_TEXT_ROLES
        ):
            return True

        if (
            self._read_range_attribute(element, "AXVisibleCharacterRange") is not None
            and role in self._PREFERRED_TEXT_ROLES
        ):
            return True

        value = self._read_attribute(element, "AXValue")
        return self._looks_like_editor_text(role, value)

    def _read_attribute(self, element, attr: str):
        """Read an attribute from an AXUIElement."""
        try:
            err, value = self._AS.AXUIElementCopyAttributeValue(element, attr, None)
        except Exception:
            return None
        if err == 0:
            return value
        return None

    def _read_range_attribute(self, element, attr: str) -> Optional[Tuple[int, int]]:
        """Read a range attribute and unpack it."""
        value = self._read_attribute(element, attr)
        if value is None:
            return None
        return self._unpack_range(value)

    def _read_text_for_range(self, element, location: int, length: int) -> Optional[str]:
        """Read text for a specific range."""
        snippet = self._read_parameterized_range(
            element,
            "AXStringForRange",
            max(location - (MAX_EXTRACT_CHARS // 2), 0),
            max(length, 1) + MAX_EXTRACT_CHARS,
        )
        if snippet:
            return snippet

        value = self._read_attribute(element, "AXValue")
        if not value:
            return None
        return self._slice_text_around_range(str(value), location, length)

    def _read_parameterized_range(
        self,
        element,
        attr: str,
        location: int,
        length: int,
    ) -> Optional[str]:
        """Read text using a parameterized attribute."""
        try:
            range_value = self._AS.AXValueCreate(
                self._AS.kAXValueCFRangeType,
                self._AS.CFRange(location, max(length, 1)),
            )
            err, value = self._AS.AXUIElementCopyParameterizedAttributeValue(
                element,
                attr,
                range_value,
                None,
            )
            if err == 0 and value:
                return str(value).strip()[:MAX_EXTRACT_CHARS]
        except Exception:
            return None
        return None

    def _unpack_range(self, value) -> Optional[Tuple[int, int]]:
        """Unpack an AXValue range into location and length."""
        try:
            success, raw_range = self._AS.AXValueGetValue(
                value,
                self._AS.kAXValueCFRangeType,
                None,
            )
            if not success or not isinstance(raw_range, tuple) or len(raw_range) != 2:
                return None
            location, length = raw_range
            return int(location), int(length)
        except Exception:
            return None

    @staticmethod
    def _slice_text_around_range(text: str, location: int, length: int) -> str:
        """
        Extract text around a cursor position with a window.
        
        Args:
            text: Full text content
            location: Cursor position
            length: Selection length
            
        Returns:
            Text snippet around cursor
        """
        if not text:
            return ""

        total = len(text)
        cursor = max(0, min(location, total))
        selection = max(1, length)
        half_window = MAX_EXTRACT_CHARS // 2
        start = max(0, cursor - half_window)
        end = min(total, cursor + selection + half_window)

        if end - start < MAX_EXTRACT_CHARS and total > MAX_EXTRACT_CHARS:
            if start == 0:
                end = min(total, MAX_EXTRACT_CHARS)
            elif end == total:
                start = max(0, total - MAX_EXTRACT_CHARS)

        if end - start > MAX_EXTRACT_CHARS:
            overflow = (end - start) - MAX_EXTRACT_CHARS
            trim_left = overflow // 2
            trim_right = overflow - trim_left
            start += trim_left
            end -= trim_right

        return text[start:end].strip()

    def _looks_like_editor_text(self, role, value) -> bool:
        """
        Determine if a value looks like editor text content.
        
        Args:
            role: AXRole of the element
            value: Text value to check
            
        Returns:
            True if value looks like editor text
        """
        if not isinstance(value, str):
            return False
        text = value.strip()
        if not text:
            return False
        if isinstance(role, str) and role in self._PREFERRED_TEXT_ROLES:
            return True
        if "\n" in text or len(text) >= 60:
            return True
        if role == "AXStaticText":
            return False
        lowered = text.lower()
        if lowered == "fade in":
            return False
        if lowered.startswith("page ") and " of " in lowered:
            return False
        if text.endswith("pt") and any(char.isdigit() for char in text):
            return False
        return False


# ─── Windows Extractor ───────────────────────────────────────────────────────


class WindowsExtractor(TextExtractor):
    """
    Uses uiautomation to read focused control text on Windows.
    
    Features:
    - uiautomation integration
    - Support for Windows screenwriting apps
    - Process name detection
    - Text extraction from active window
    - Handle UAC and permission issues
    - Clipboard fallback when UIA fails
    """

    def __init__(self):
        """Initialize Windows extractor with UI Automation."""
        self._uia = None
        self._clipboard_monitor = ClipboardMonitor()
        self._load_uia()

    def _load_uia(self) -> None:
        """Load uiautomation library."""
        try:
            import uiautomation as uia
            self._uia = uia
            logger.info("Windows UIAutomation loaded")
        except ImportError:
            logger.warning("uiautomation not available — install with: pip install uiautomation")

    async def get_active_app(self) -> Optional[str]:
        """
        Get the process name of the foreground window.
        
        Returns:
            Process name or None if unavailable
        """
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
        """
        Extract text from the focused control using UI Automation.
        
        Returns:
            Extracted text or None if extraction fails
        """
        if not self._uia:
            return await self._extract_via_clipboard()
        
        try:
            focused = self._uia.GetFocusedControl()
            if focused is None:
                return await self._extract_via_clipboard()

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

            return await self._extract_via_clipboard()
        except Exception as e:
            logger.debug("extract_focused_text error: %s", e)
            return await self._extract_via_clipboard()

    async def _extract_via_clipboard(self) -> Optional[str]:
        """
        Fallback: read clipboard content.
        
        Returns:
            Clipboard content or None
        """
        content = self._clipboard_monitor.get_content()
        if content:
            return content
        
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[-MAX_EXTRACT_CHARS:]
        except Exception as e:
            logger.debug("Windows clipboard fallback error: %s", e)
        
        return None


# ─── Linux Extractor ─────────────────────────────────────────────────────────


class LinuxExtractor(TextExtractor):
    """
    Uses AT-SPI2 accessibility stack on Linux (GNOME/KDE).
    
    Features:
    - AT-SPI2 via pyatspi
    - Support for Linux editors
    - Process name detection
    - Text extraction
    - Handle D-Bus connection issues
    - xdotool + xclip clipboard fallback
    """

    def __init__(self):
        """Initialize Linux extractor with AT-SPI2."""
        self._atspi = None
        self._clipboard_monitor = ClipboardMonitor()
        self._load_atspi()

    def _load_atspi(self) -> None:
        """Load pyatspi library."""
        try:
            import pyatspi
            self._atspi = pyatspi
            logger.info("AT-SPI2 loaded")
        except ImportError:
            logger.warning("pyatspi not available — install with: pip install pyatspi")

    async def get_active_app(self) -> Optional[str]:
        """
        Get the name of the active window.
        
        Returns:
            Window name or None if unavailable
        """
        try:
            import subprocess
            result = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True, text=True, timeout=2
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    async def extract_focused_text(self) -> Optional[str]:
        """
        Extract text using AT-SPI2 or fallback methods.
        
        Returns:
            Extracted text or None if all methods fail
        """
        if self._atspi:
            text = await self._extract_via_atspi()
            if text:
                return text
        
        return await self._extract_via_clipboard()

    async def _extract_via_atspi(self) -> Optional[str]:
        """
        Extract text using AT-SPI2 accessibility API.
        
        Returns:
            Extracted text or None
        """
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
        Fallback: read clipboard content via xclip.
        
        Returns:
            Clipboard content or None
        """
        content = self._clipboard_monitor.get_content()
        if content:
            return content
        
        try:
            import subprocess
            # Try primary selection first
            result = subprocess.run(
                ["xclip", "-o", "-selection", "primary"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[-MAX_EXTRACT_CHARS:]
            
            # Try clipboard selection
            result = subprocess.run(
                ["xclip", "-o", "-selection", "clipboard"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[-MAX_EXTRACT_CHARS:]
        except Exception as e:
            logger.debug("Linux clipboard fallback error: %s", e)
        
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
    
    Features:
    - Platform detection and selection logic
    - Debounce handling
    - Error recovery
    - Clean resource cleanup
    - Thread-safe operations
    
    callback signature: async def on_text(text: str) -> None
    """

    def __init__(self, config: dict, callback: Callable):
        """
        Initialize the watcher.
        
        Args:
            config: Configuration dictionary
            callback: Async callback function for text changes
        """
        self.config = config
        self.callback = callback
        self.debounce_secs: float = config.get("debounce_seconds", 2.0)
        self._extractor = self._build_extractor()
        self._last_text: str = ""
        self._last_change_time: float = 0.0
        self._pending_task: Optional[asyncio.Task] = None
        self._running = False
        self._fired = False
        self._error_count = 0
        self._max_consecutive_errors = 10

    def _build_extractor(self) -> TextExtractor:
        """
        Build the appropriate text extractor for the current platform.
        
        Returns:
            Platform-specific TextExtractor instance
        """
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

    async def run(self) -> None:
        """Main polling loop. Runs until stopped."""
        self._running = True
        logger.info("Watcher started (debounce=%.1fs)", self.debounce_secs)

        while self._running:
            try:
                await self._tick()
                self._error_count = 0  # Reset on success
            except Exception as e:
                self._error_count += 1
                logger.exception("Watcher tick error: %s", e)
                
                # Back off on consecutive errors
                if self._error_count >= self._max_consecutive_errors:
                    logger.warning("Too many consecutive errors, backing off")
                    await asyncio.sleep(5.0)
                    self._error_count = 0
                    
            await asyncio.sleep(POLLING_INTERVAL)

    async def _tick(self) -> None:
        """
        Perform a single polling tick.
        
        Checks for active app, extracts text, and handles debounce logic.
        """
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

    def stop(self) -> None:
        """Stop the watcher."""
        self._running = False
        logger.info("Watcher stopped")

    @property
    def _pending_fired(self) -> bool:
        return getattr(self, "_fired", False)

    @_pending_fired.setter
    def _pending_fired(self, value: bool) -> None:
        self._fired = value
