"""
test_watcher.py — Comprehensive Watcher Tests

Covers:
- TypedTextBuffer operations
- Thread safety
- TTL handling
- App change detection
- Backspace handling
- Platform detection (mocked)
- Error handling
- Watcher class behavior
- Extractor abstraction
"""

import asyncio
import platform
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gramwrite.watcher import (
    MAX_EXTRACT_CHARS,
    SUPPORTED_APPS,
    MacOSExtractor,
    MacOSKeyFallback,
    NullExtractor,
    TextExtractor,
    TypedTextBuffer,
    Watcher,
)


# ─── TypedTextBuffer Tests ───────────────────────────────────────────────────


class TestTypedTextBuffer:
    def test_record_text(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hello")
        assert typed_buffer.snapshot("com.test.app") == "Hello"

    def test_record_multiple_texts(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "He")
        typed_buffer.record_text("com.test.app", "llo")
        assert typed_buffer.snapshot("com.test.app") == "Hello"

    def test_record_backspace(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hello")
        typed_buffer.record_backspace("com.test.app")
        assert typed_buffer.snapshot("com.test.app") == "Hell"

    def test_record_backspace_multiple(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hello")
        typed_buffer.record_backspace("com.test.app", count=2)
        assert typed_buffer.snapshot("com.test.app") == "Hel"

    def test_record_backspace_more_than_length(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hi")
        typed_buffer.record_backspace("com.test.app", count=10)
        # Buffer is empty after stripping, snapshot returns None
        assert typed_buffer.snapshot("com.test.app") is None

    def test_app_change_resets_buffer(self, typed_buffer):
        typed_buffer.record_text("com.app.one", "Text from app one")
        typed_buffer.record_text("com.app.two", "Text from app two")
        # App one's buffer should be gone
        assert typed_buffer.snapshot("com.app.one") is None
        # App two should have its text
        assert typed_buffer.snapshot("com.app.two") == "Text from app two"

    def test_snapshot_wrong_app_returns_none(self, typed_buffer):
        typed_buffer.record_text("com.app.one", "Text")
        assert typed_buffer.snapshot("com.app.two") is None

    def test_snapshot_no_app_id_returns_none(self, typed_buffer):
        typed_buffer.record_text("com.app.one", "Text")
        assert typed_buffer.snapshot(None) is None

    def test_clear_buffer(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hello")
        typed_buffer.clear()
        assert typed_buffer.snapshot("com.test.app") is None

    def test_record_empty_text_ignored(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "")
        assert typed_buffer.snapshot("com.test.app") is None

    def test_max_chars_truncation(self):
        buffer = TypedTextBuffer(max_chars=10, ttl_secs=60.0)
        buffer.record_text("com.test.app", "A" * 20)
        snapshot = buffer.snapshot("com.test.app")
        assert len(snapshot) <= 10
        assert snapshot == "A" * 10

    def test_ttl_expiration(self):
        buffer = TypedTextBuffer(max_chars=100, ttl_secs=0.01)  # 10ms TTL
        buffer.record_text("com.test.app", "Hello")
        time.sleep(0.02)  # Wait for TTL to expire
        assert buffer.snapshot("com.test.app") is None

    def test_ttl_not_expired_yet(self):
        buffer = TypedTextBuffer(max_chars=100, ttl_secs=60.0)
        buffer.record_text("com.test.app", "Hello")
        assert buffer.snapshot("com.test.app") == "Hello"

    def test_snapshot_strips_whitespace(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "  Hello  ")
        assert typed_buffer.snapshot("com.test.app") == "Hello"

    def test_snapshot_returns_none_for_empty_buffer(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "   ")
        assert typed_buffer.snapshot("com.test.app") is None

    def test_max_extract_chars_limit(self, typed_buffer):
        """Snapshot should respect MAX_EXTRACT_CHARS limit."""
        long_text = "A" * 500
        typed_buffer.record_text("com.test.app", long_text)
        snapshot = typed_buffer.snapshot("com.test.app")
        assert len(snapshot) <= MAX_EXTRACT_CHARS

    def test_thread_safety(self, typed_buffer):
        """Buffer should be thread-safe with lock."""
        import threading

        errors = []

        def record_many():
            try:
                for i in range(100):
                    typed_buffer.record_text("com.test.app", f"char{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=record_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_backspace_on_empty_buffer(self, typed_buffer):
        typed_buffer.record_backspace("com.test.app")
        assert typed_buffer.snapshot("com.test.app") is None

    def test_record_text_updates_timestamp(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hello")
        assert typed_buffer._updated_at > 0

    def test_record_backspace_updates_timestamp(self, typed_buffer):
        typed_buffer.record_text("com.test.app", "Hello")
        old_time = typed_buffer._updated_at
        time.sleep(0.001)
        typed_buffer.record_backspace("com.test.app")
        assert typed_buffer._updated_at > old_time


# ─── TextExtractor Abstract Tests ────────────────────────────────────────────


class TestTextExtractor:
    def test_text_extractor_is_abstract(self):
        with pytest.raises(TypeError):
            TextExtractor()

    def test_is_supported_app_macos(self):
        extractor = NullExtractor()
        with patch.object(platform, "system", return_value="Darwin"):
            assert extractor.is_supported_app("com.generalcoffee.fadein") is True

    def test_is_supported_app_windows(self):
        extractor = NullExtractor()
        with patch.object(platform, "system", return_value="Windows"):
            assert extractor.is_supported_app("fadein.exe") is True

    def test_is_supported_app_linux(self):
        extractor = NullExtractor()
        with patch.object(platform, "system", return_value="Linux"):
            assert extractor.is_supported_app("fadein") is True

    def test_is_supported_app_none(self):
        extractor = NullExtractor()
        assert extractor.is_supported_app(None) is False

    def test_is_supported_app_empty(self):
        extractor = NullExtractor()
        assert extractor.is_supported_app("") is False

    def test_is_supported_app_unknown(self):
        extractor = NullExtractor()
        with patch.object(platform, "system", return_value="Darwin"):
            assert extractor.is_supported_app("com.unknown.app") is False

    def test_is_supported_app_partial_match(self):
        """Should match if supported app is a substring."""
        extractor = NullExtractor()
        with patch.object(platform, "system", return_value="Darwin"):
            # VSCode should match com.microsoft.VSCode
            assert extractor.is_supported_app("com.microsoft.VSCode") is True


# ─── NullExtractor Tests ─────────────────────────────────────────────────────


class TestNullExtractor:
    @pytest.mark.asyncio
    async def test_get_active_app_returns_none(self):
        extractor = NullExtractor()
        assert await extractor.get_active_app() is None

    @pytest.mark.asyncio
    async def test_extract_focused_text_returns_none(self):
        extractor = NullExtractor()
        assert await extractor.extract_focused_text() is None


# ─── Watcher Tests ───────────────────────────────────────────────────────────


class TestWatcher:
    def test_watcher_initialization(self, watcher_config, mock_callback):
        watcher = Watcher(watcher_config, mock_callback)
        assert watcher.config == watcher_config
        assert watcher.callback == mock_callback
        assert watcher.debounce_secs == 0.1
        assert watcher._running is False

    def test_watcher_default_debounce(self, mock_callback):
        watcher = Watcher({}, mock_callback)
        assert watcher.debounce_secs == 2.0

    def test_watcher_build_extractor_macos(self, mock_callback):
        with patch.object(platform, "system", return_value="Darwin"):
            watcher = Watcher({}, mock_callback)
            assert isinstance(watcher._extractor, MacOSExtractor)

    def test_watcher_build_extractor_windows(self, mock_callback):
        with patch.object(platform, "system", return_value="Windows"):
            watcher = Watcher({}, mock_callback)
            from gramwrite.watcher import WindowsExtractor
            assert isinstance(watcher._extractor, WindowsExtractor)

    def test_watcher_build_extractor_linux(self, mock_callback):
        with patch.object(platform, "system", return_value="Linux"):
            watcher = Watcher({}, mock_callback)
            from gramwrite.watcher import LinuxExtractor
            assert isinstance(watcher._extractor, LinuxExtractor)

    def test_watcher_build_extractor_unknown(self, mock_callback):
        with patch.object(platform, "system", return_value="Unknown"):
            watcher = Watcher({}, mock_callback)
            assert isinstance(watcher._extractor, NullExtractor)

    @pytest.mark.asyncio
    async def test_watcher_stop(self, watcher_config, mock_callback):
        watcher = Watcher(watcher_config, mock_callback)
        watcher._running = True
        watcher.stop()
        assert watcher._running is False

    @pytest.mark.asyncio
    async def test_watcher_stop_idempotent(self, watcher_config, mock_callback):
        watcher = Watcher(watcher_config, mock_callback)
        watcher.stop()
        watcher.stop()  # Should not raise


# ─── MacOSKeyFallback Tests ─────────────────────────────────────────────────


class TestMacOSKeyFallback:
    def test_keyfallback_initialization(self):
        """KeyFallback should initialize without errors even without Quartz."""
        checker = MagicMock(return_value=False)
        fallback = MacOSKeyFallback(checker)
        # Should not raise even if Quartz is not available
        assert fallback._buffer is not None

    def test_keyfallback_snapshot_delegates_to_buffer(self):
        checker = MagicMock(return_value=False)
        fallback = MacOSKeyFallback(checker)
        fallback._buffer.record_text("com.test.app", "Hello")
        assert fallback.snapshot("com.test.app") == "Hello"

    def test_keyfallback_snapshot_none_when_no_buffer(self):
        checker = MagicMock(return_value=False)
        fallback = MacOSKeyFallback(checker)
        assert fallback.snapshot("com.test.app") is None


# ─── SUPPORTED_APPS Tests ───────────────────────────────────────────────────


class TestSupportedApps:
    def test_supported_apps_has_macos(self):
        assert "macos" in SUPPORTED_APPS
        assert len(SUPPORTED_APPS["macos"]) > 0

    def test_supported_apps_has_windows(self):
        assert "windows" in SUPPORTED_APPS
        assert len(SUPPORTED_APPS["windows"]) > 0

    def test_supported_apps_has_linux(self):
        assert "linux" in SUPPORTED_APPS
        assert len(SUPPORTED_APPS["linux"]) > 0

    def test_fadein_in_supported_apps(self):
        assert "com.generalcoffee.fadein" in SUPPORTED_APPS["macos"]

    def test_max_extract_chars_constant(self):
        assert MAX_EXTRACT_CHARS == 300


# ─── Integration: TypedTextBuffer Workflow Tests ─────────────────────────────


class TestTypedTextBufferWorkflow:
    def test_typing_workflow(self, typed_buffer):
        """Simulate a typing workflow with text and backspaces."""
        typed_buffer.record_text("com.test.app", "He")
        typed_buffer.record_text("com.test.app", "llo")
        typed_buffer.record_backspace("com.test.app")
        typed_buffer.record_text("com.test.app", "o world")
        assert typed_buffer.snapshot("com.test.app") == "Hello world"

    def test_multi_app_workflow(self, typed_buffer):
        """Test switching between apps resets buffer."""
        typed_buffer.record_text("com.app.one", "Text one")
        typed_buffer.record_text("com.app.two", "Text two")
        typed_buffer.record_text("com.app.one", " more")

        # App one should have "more" (buffer reset on app switch, then " more" recorded)
        # snapshot strips whitespace
        assert typed_buffer.snapshot("com.app.one") == "more"
        # App two's text was overwritten when we switched back to app one
        # The buffer only tracks one app at a time
        assert typed_buffer.snapshot("com.app.two") is None

    def test_backspace_workflow(self, typed_buffer):
        """Test backspace behavior in a realistic workflow."""
        typed_buffer.record_text("com.test.app", "Hello World")
        typed_buffer.record_backspace("com.test.app", count=6)
        assert typed_buffer.snapshot("com.test.app") == "Hello"

    def test_empty_snapshot_after_ttl(self):
        """Test that TTL expiration clears the buffer."""
        buffer = TypedTextBuffer(max_chars=100, ttl_secs=0.001)
        buffer.record_text("com.test.app", "Hello")
        time.sleep(0.005)
        assert buffer.snapshot("com.test.app") is None
