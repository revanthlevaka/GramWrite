"""
app.py — GramWrite Floating UI
Minimal, always-on-top draggable icon with suggestion bubble.
Built with PyQt6.

Provides:
- FloatingDot: Small, unobtrusive status indicator (bottom-right corner)
- SuggestionBubble: Correction popup with accept/reject/copy actions
- SignalBridge: Thread-safe communication between async controller and Qt
- AsyncWorkerThread: Background event loop for grammar pipeline
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from PyQt6.QtCore import (
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    QEasingCurve,
    QObject,
)
from PyQt6.QtGui import (
    QAction,
    QClipboard,
    QColor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
    QKeySequence,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

# ─── Colour palette ──────────────────────────────────────────────────────────
C_IDLE = QColor(80, 80, 90, 200)
C_PROCESSING = QColor(60, 100, 160, 220)
C_ALERT = QColor(50, 180, 120, 240)
C_ERROR = QColor(180, 70, 60, 220)

C_BG_BUBBLE = QColor(18, 18, 22, 230)
C_BORDER = QColor(60, 60, 70)
C_TEXT_PRIMARY = QColor(230, 230, 235)
C_TEXT_DIM = QColor(120, 120, 130)
C_COPY_BTN = QColor(50, 180, 120)
C_ACCEPT_BTN = QColor(50, 180, 120)
C_REJECT_BTN = QColor(180, 70, 60)


# ─── Signals bridge (Controller → Qt main thread) ────────────────────────────


class SignalBridge(QObject):
    """
    Thread-safe signal bridge between the async grammar pipeline and Qt main thread.

    Signals:
        correction_ready: Emitted when a grammar suggestion is available.
            Args: original, correction, confidence, diff_html, element_type
        state_changed: Emitted when the app state changes.
            Args: state string (idle | processing | alert | error)
        backend_status: Emitted with backend status messages.
            Args: status message string
    """

    correction_ready = pyqtSignal(str, str, str, str, str)   # original, correction, confidence, diff_html, element_type
    state_changed = pyqtSignal(str)           # idle | processing | alert | error
    backend_status = pyqtSignal(str)          # status message


# ─── Floating dot icon ────────────────────────────────────────────────────────


class FloatingDot(QWidget):
    """
    The primary GramWrite icon — a small coloured dot in the screen corner.

    Features:
    - Draggable via mouse
    - Left-click toggles suggestion bubble
    - Right-click opens context menu (Settings, Always on Top, Quit)
    - Animated pulse during processing/alert states
    - Always-on-top by default, toggleable
    """

    open_settings = pyqtSignal()  # emitted when user picks «Settings» from menu
    always_on_top_toggled = pyqtSignal(bool)  # emitted when always-on-top state changes

    def __init__(self, bridge: SignalBridge, size: int = 28):
        super().__init__(None)
        self._bridge = bridge
        self._dot_size = size
        self._color = QColor(C_IDLE)
        self._drag_pos: Optional[QPoint] = None
        self._pulse_alpha = 200
        self._pulse_direction = 1
        self._bubble: Optional[SuggestionBubble] = None
        self._current_suggestion: Optional[str] = None
        self._current_original: Optional[str] = None
        self._current_confidence: str = "LOW"
        self._current_diff_html: str = ""
        self._current_element_type: str = "dialogue"
        self._always_on_top = True
        self._state = "idle"

        self._init_window()
        self._init_pulse_timer()
        self._connect_signals()
        self._init_context_menu()
        self._init_keyboard_shortcuts()

    def _init_window(self):
        """Configure window flags, position, and visual effects."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setFixedSize(self._dot_size + 8, self._dot_size + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Position bottom-right of primary screen
        screen = QGuiApplication.primaryScreen().availableGeometry()
        target_x = screen.x() + screen.width() - 80
        target_y = screen.y() + screen.height() - 120
        self.move(target_x, target_y)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

    def _init_pulse_timer(self):
        """Start the 20fps pulse animation timer."""
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(50)  # 20fps pulse

    def _connect_signals(self):
        """Connect bridge signals to local handlers."""
        self._bridge.correction_ready.connect(self._on_correction_ready)
        self._bridge.state_changed.connect(self._on_state_changed)

    def _init_context_menu(self):
        """Build the right-click context menu with Settings, Always on Top, and Quit."""
        self._ctx_menu = QMenu()
        self._ctx_menu.setStyleSheet("""
            QMenu {
                background: #1a1a24;
                color: #c8c4bc;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                padding: 4px 0;
                font-family: 'Courier Prime', monospace;
                font-size: 11px;
            }
            QMenu::item {
                padding: 6px 24px 6px 16px;
            }
            QMenu::item:selected {
                background: rgba(58,176,120,0.20);
                color: #e8e4da;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255,255,255,0.07);
                margin: 4px 8px;
            }
        """)

        settings_action = QAction("⚙  Settings", self)
        settings_action.triggered.connect(self.open_settings.emit)
        self._ctx_menu.addAction(settings_action)

        self._ctx_menu.addSeparator()

        self._always_on_top_action = QAction("📌  Always on Top", self)
        self._always_on_top_action.setCheckable(True)
        self._always_on_top_action.setChecked(self._always_on_top)
        self._always_on_top_action.triggered.connect(self._toggle_always_on_top)
        self._ctx_menu.addAction(self._always_on_top_action)

        self._ctx_menu.addSeparator()

        quit_action = QAction("✕  Quit GramWrite", self)
        quit_action.triggered.connect(QApplication.quit)
        self._ctx_menu.addAction(quit_action)

    def _init_keyboard_shortcuts(self):
        """Register keyboard shortcuts for quick actions."""
        # Ctrl+Shift+G: Toggle suggestion bubble
        self._toggle_shortcut = QShortcut(QKeySequence("Ctrl+Shift+G"), self)
        self._toggle_shortcut.activated.connect(self._toggle_bubble)

        # Ctrl+Shift+S: Open settings
        self._settings_shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        self._settings_shortcut.activated.connect(self.open_settings.emit)

    def _toggle_always_on_top(self, checked: bool):
        """Toggle the always-on-top window flag."""
        self._always_on_top = checked
        self.always_on_top_toggled.emit(checked)
        # Re-apply window flags
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        if checked:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.show()

    def contextMenuEvent(self, event):
        """Show context menu on right-click."""
        self._ctx_menu.exec(event.globalPos())

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        """Render the dot with glow and pulse effects."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        r = self._dot_size / 2

        # Glow effect
        glow = QRadialGradient(cx, cy, r * 1.8)
        glow_color = QColor(self._color)
        glow_color.setAlpha(40)
        glow.setColorAt(0, glow_color)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(
            int(cx - r * 1.8), int(cy - r * 1.8),
            int(r * 3.6), int(r * 3.6)
        )

        # Main dot
        dot_color = QColor(self._color)
        dot_color.setAlpha(self._pulse_alpha)
        painter.setBrush(dot_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        painter.end()

    def _tick_pulse(self):
        """Update pulse animation based on current state."""
        state = getattr(self, "_state", "idle")
        if state == "processing":
            self._pulse_alpha += self._pulse_direction * 8
            if self._pulse_alpha >= 240 or self._pulse_alpha <= 100:
                self._pulse_direction *= -1
        elif state == "alert":
            self._pulse_alpha += self._pulse_direction * 4
            if self._pulse_alpha >= 255 or self._pulse_alpha <= 160:
                self._pulse_direction *= -1
        else:
            self._pulse_alpha = 200
        self.update()

    # ── State ─────────────────────────────────────────────────────────────────

    def _on_state_changed(self, state: str):
        """Handle state transitions with colour updates."""
        self._state = state
        if state == "idle":
            self._color = QColor(C_IDLE)
        elif state == "processing":
            self._color = QColor(C_PROCESSING)
        elif state == "alert":
            self._color = QColor(C_ALERT)
        elif state == "error":
            self._color = QColor(C_ERROR)
        self.update()

    def _on_correction_ready(self, original: str, correction: str, confidence: str, diff_html: str, element_type: str):
        """Store new suggestion and transition to alert state."""
        self._current_original = original
        self._current_suggestion = correction
        self._current_confidence = confidence
        self._current_diff_html = diff_html
        self._current_element_type = element_type
        self._on_state_changed("alert")

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        """Begin drag on left-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        """End drag or register click if no movement."""
        if event.button() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            if self._drag_pos and (delta - self._drag_pos).manhattanLength() < 5:
                # It was a click, not a drag
                self._toggle_bubble()
            self._drag_pos = None

    def mouseMoveEvent(self, event: QMouseEvent):
        """Move window during drag."""
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def _toggle_bubble(self):
        """Show or hide the suggestion bubble."""
        if self._bubble and self._bubble.isVisible():
            self._bubble.hide()
            return

        if self._current_suggestion:
            if not self._bubble:
                self._bubble = SuggestionBubble(self._bridge)
                # Connect accept/reject signals
                self._bubble.suggestion_accepted.connect(self._on_suggestion_accepted)
                self._bubble.suggestion_rejected.connect(self._on_suggestion_rejected)
            self._bubble.set_content(
                self._current_original or "",
                self._current_suggestion,
                self._current_confidence,
                self._current_diff_html,
                self._current_element_type,
            )
            # Position bubble above dot
            dot_pos = self.mapToGlobal(QPoint(0, 0))
            bubble_x = dot_pos.x() - 280 + self._dot_size
            bubble_y = dot_pos.y() - 140
            screen = QGuiApplication.primaryScreen().geometry()
            bubble_x = max(8, min(bubble_x, screen.width() - 310))
            bubble_y = max(8, bubble_y)
            self._bubble.move(bubble_x, bubble_y)
            self._bubble.show()
        else:
            # No suggestion — show status dot with no-error pulse
            self._on_state_changed("idle")

    def _on_suggestion_accepted(self, correction: str):
        """Handle accepted suggestion — dismiss bubble and return to idle."""
        self._on_state_changed("idle")

    def _on_suggestion_rejected(self):
        """Handle rejected suggestion — dismiss bubble and return to idle."""
        self._on_state_changed("idle")


# ─── Suggestion Bubble ────────────────────────────────────────────────────────


class SuggestionBubble(QWidget):
    """
    Brand-aligned correction popup with accept/reject/copy actions.

    Displays:
    - Original text (red, italic)
    - Corrected text (green)
    - Confidence badge and element type badge
    - Accept (applies correction), Reject (dismisses), Copy buttons

    Keyboard shortcuts:
    - Enter: Accept suggestion
    - Escape: Reject/dismiss
    - Ctrl+C: Copy corrected text
    """

    suggestion_accepted = pyqtSignal(str)   # emitted with corrected text
    suggestion_rejected = pyqtSignal()      # emitted when user dismisses

    def __init__(self, bridge: SignalBridge):
        super().__init__(None)
        self._bridge = bridge
        self._correction: str = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setFixedWidth(320)

        self._build_ui()
        self._apply_shadow()
        self._init_keyboard_shortcuts()

    def _init_keyboard_shortcuts(self):
        """Register keyboard shortcuts for accept/reject/copy actions."""
        # Enter: Accept suggestion
        self._accept_shortcut = QShortcut(QKeySequence("Return"), self)
        self._accept_shortcut.activated.connect(self._on_accept)

        # Escape: Reject/dismiss
        self._reject_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._reject_shortcut.activated.connect(self._on_reject)

        # Ctrl+C: Copy corrected text
        self._copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self)
        self._copy_shortcut.activated.connect(self._copy_to_clipboard)

    def _build_ui(self):
        """Construct the bubble layout with all UI elements."""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._container = QWidget(self)
        self._container.setObjectName("bubble")
        self._container.setStyleSheet("""
            QWidget#bubble {
                background: rgba(18, 18, 22, 230);
                border: 1px solid rgba(60, 60, 70, 200);
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header with confidence and type
        header_layout = QHBoxLayout()
        header = QLabel("✦ GramWrite")
        header.setFont(QFont("Courier New", 9))
        header.setStyleSheet("color: rgba(120,120,130,200); letter-spacing: 2px;")

        self._type_badge = QLabel("DIALOGUE")
        self._type_badge.setFont(QFont("Courier New", 8))
        self._type_badge.setStyleSheet("""
            background: rgba(58, 176, 120, 0.12);
            color: rgba(58, 176, 120, 255);
            padding: 2px 6px;
            border-radius: 2px;
            letter-spacing: 1px;
        """)

        self._conf_dot = QLabel("●")
        self._conf_dot.setFont(QFont("Courier New", 10))

        self._conf_label = QLabel("LOW")
        self._conf_label.setFont(QFont("Courier New", 9))
        self._conf_label.setStyleSheet("color: rgba(120,120,130,200);")

        header_layout.addWidget(header)
        header_layout.addStretch()
        header_layout.addWidget(self._type_badge)
        header_layout.addWidget(self._conf_dot)
        header_layout.addWidget(self._conf_label)

        layout.addLayout(header_layout)

        self._original_label = QLabel("")
        self._original_label.setFont(QFont("Georgia", 11))
        self._original_label.setStyleSheet("color: rgba(224, 85, 85, 255); font-style: italic; line-height: 1.5;")
        self._original_label.setWordWrap(True)
        self._original_label.setMaximumWidth(288)
        layout.addWidget(self._original_label)

        arrow = QLabel("↓")
        arrow.setFont(QFont("Courier New", 10))
        arrow.setStyleSheet("color: rgba(120,120,130,180);")
        layout.addWidget(arrow)

        self._correction_label = QLabel("")
        self._correction_label.setTextFormat(Qt.TextFormat.RichText)
        self._correction_label.setFont(QFont("Georgia", 11))
        self._correction_label.setStyleSheet("color: rgba(58, 176, 120, 255); line-height: 1.5;")
        self._correction_label.setWordWrap(True)
        self._correction_label.setMaximumWidth(288)
        layout.addWidget(self._correction_label)

        self._reason_label = QLabel("")
        self._reason_label.setFont(QFont("Courier New", 9))
        self._reason_label.setStyleSheet("color: rgba(120,120,130,200); line-height: 1.5;")
        self._reason_label.setWordWrap(True)
        self._reason_label.setMaximumWidth(288)
        layout.addWidget(self._reason_label)

        # Divider
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(60,60,70,180);")
        layout.addWidget(divider)

        # Bottom bar with Reject, Accept, Copy
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._reject_btn = QPushButton("Reject")
        self._reject_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reject_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(180, 70, 60, 200);
                border: 1px solid rgba(180, 70, 60, 120);
                border-radius: 6px;
                font-family: 'Courier New';
                font-size: 10px;
                padding: 5px 12px;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background: rgba(180, 70, 60, 40);
                color: rgba(220, 90, 80, 255);
            }
        """)
        self._reject_btn.clicked.connect(self._on_reject)

        self._accept_btn = QPushButton("Accept")
        self._accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accept_btn.setStyleSheet("""
            QPushButton {
                background: rgba(50, 180, 120, 220);
                color: white;
                border: none;
                border-radius: 6px;
                font-family: 'Courier New';
                font-size: 10px;
                font-weight: bold;
                padding: 5px 12px;
                letter-spacing: 1px;
            }
            QPushButton:hover { background: rgba(60, 200, 135, 255); }
            QPushButton:pressed { background: rgba(40, 160, 100, 255); }
        """)
        self._accept_btn.clicked.connect(self._on_accept)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(120,120,130,200);
                border: 1px solid rgba(120,120,130,100);
                border-radius: 6px;
                font-family: 'Courier New';
                font-size: 10px;
                padding: 5px 12px;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background: rgba(120,120,130,40);
                color: rgba(200,200,210,255);
            }
        """)
        self._copy_btn.clicked.connect(self._copy_to_clipboard)

        bottom.addWidget(self._reject_btn)
        bottom.addStretch()
        bottom.addWidget(self._accept_btn)
        bottom.addWidget(self._copy_btn)
        layout.addLayout(bottom)

        root.addWidget(self._container)

    def _apply_shadow(self):
        """Apply drop shadow effect to the bubble container."""
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self._container.setGraphicsEffect(shadow)

    def set_content(self, original: str, correction: str, confidence: str, diff_html: str, element_type: str):
        """
        Populate the bubble with suggestion data.

        Args:
            original: The original text with potential errors.
            correction: The corrected text suggestion.
            confidence: Confidence level (HIGH, MEDIUM, LOW).
            diff_html: HTML diff representation (reserved for future use).
            element_type: Screenplay element type (dialogue, action, etc.).
        """
        self._correction = correction

        original_display = original
        correction_display = correction
        if len(original_display) > 140:
            original_display = original_display[:137] + "..."
        if len(correction_display) > 140:
            correction_display = correction_display[:137] + "..."

        self._original_label.setText(f"\"{original_display}\"")
        self._correction_label.setText(f"\"{correction_display}\"")
        readable_type = (element_type or "dialogue").strip().lower()
        self._type_badge.setText(readable_type.upper())
        if readable_type == "action":
            self._type_badge.setStyleSheet("""
                background: rgba(201, 168, 76, 0.12);
                color: rgba(201, 168, 76, 255);
                padding: 2px 6px;
                border-radius: 2px;
                letter-spacing: 1px;
            """)
        else:
            self._type_badge.setStyleSheet("""
                background: rgba(58, 176, 120, 0.12);
                color: rgba(58, 176, 120, 255);
                padding: 2px 6px;
                border-radius: 2px;
                letter-spacing: 1px;
            """)

        self._reason_label.setText(
            f"{confidence.title()} confidence suggestion for the current {readable_type} line."
        )

        self._conf_label.setText(confidence)
        if confidence == "HIGH":
            self._conf_dot.setStyleSheet("color: #4CAF50;")
        elif confidence == "MEDIUM":
            self._conf_dot.setStyleSheet("color: #FFC107;")
        else:
            self._conf_dot.setStyleSheet("color: #787882;")

        self.adjustSize()

    def _on_accept(self):
        """Handle accept action — emit signal and dismiss."""
        self.suggestion_accepted.emit(self._correction)
        self.hide()

    def _on_reject(self):
        """Handle reject action — emit signal and dismiss."""
        self.suggestion_rejected.emit()
        self.hide()

    def _copy_to_clipboard(self):
        """Copy corrected text to system clipboard."""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self._correction)
        self._copy_btn.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self._copy_btn.setText("Copy"))


# ─── Async bridge thread ─────────────────────────────────────────────────────


class AsyncWorkerThread(QThread):
    """
    Runs the asyncio event loop (Controller + Watcher) in a background thread.
    Communicates results back via Qt signals on SignalBridge.
    """

    def __init__(self, config: dict, bridge: SignalBridge):
        super().__init__()
        self._config = config
        self._bridge = bridge
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._controller = None

    def run(self):
        """Start the async event loop with controller and web dashboard."""
        from .controller import Controller, PipelineResult
        from .web_dashboard import WebDashboard

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        def on_result(result: PipelineResult):
            # Push to web dashboard for live polling
            if hasattr(self, "_web"):
                self._web.push_suggestion({
                    "has_suggestion": result.has_suggestion,
                    "original": result.parsed.text,
                    "correction": result.suggestion,
                    "confidence": result.confidence,
                    "diff_html": result.diff_html,
                    "parsed": result.parsed.to_dict(),
                })

            if result.has_suggestion:
                self._bridge.correction_ready.emit(
                    result.parsed.text,
                    result.suggestion,
                    result.confidence,
                    result.diff_html,
                    result.parsed.element.value,
                )
                self._bridge.state_changed.emit("alert")
            elif result.parsed.should_check:
                # Was checked, no errors found
                self._bridge.state_changed.emit("idle")
            else:
                self._bridge.state_changed.emit("idle")

        self._controller = Controller(self._config, on_result)

        # Start Web Dashboard
        port = self._config.get("dashboard_port", 7878)
        self._web = WebDashboard(
            self._config,
            self._controller.engine,
            on_update=lambda updated: asyncio.create_task(self._controller.apply_config(updated)),
        )

        async def main_loop():
            # Start web server as a concurrent task
            web_task = asyncio.create_task(self._web.start(port))
            # Start the main controller (blocks until stopped)
            await self._controller.start()
            # If controller stops, cancel web server
            web_task.cancel()
            await self._web.stop()

        try:
            self._loop.run_until_complete(main_loop())
        except Exception as e:
            logger.exception("AsyncWorkerThread error: %s", e)
            self._bridge.state_changed.emit("error")

    def stop(self):
        """Gracefully stop the controller and web dashboard."""
        if self._controller and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._controller.stop(), self._loop
            )
        if hasattr(self, "_web") and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._web.stop(), self._loop
            )

    def apply_config(self, config: dict):
        """Apply updated configuration to the running controller."""
        updated_config = dict(config)
        self._config.clear()
        self._config.update(updated_config)
        if self._controller and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._controller.apply_config(self._config), self._loop
            )


# ─── Main entry point ────────────────────────────────────────────────────────


def run_app(config: dict, show_dashboard: bool = False):
    """
    Launch the GramWrite floating UI application.

    Args:
        config: Application configuration dictionary.
        show_dashboard: If True, open the settings dashboard on startup.
    """
    from .engine import GramEngine
    from .dashboard import DashboardWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("GramWrite")
    app.setApplicationDisplayName("GramWrite")

    # Set application icon
    try:
        from pathlib import Path
        from PyQt6.QtGui import QIcon

        # Try to find the icon file
        icon_paths = [
            Path(__file__).parent / "static" / "icon.png",  # Package static
            Path.cwd() / "gramwrite" / "static" / "icon.png",  # CWD relative
            Path.cwd() / "assets" / "icon" / "icon.png",  # Assets folder
        ]

        for icon_path in icon_paths:
            if icon_path.exists():
                app.setWindowIcon(QIcon(str(icon_path)))
                break
    except (ImportError, OSError) as exc:
        logger.debug("Skipping optional app icon setup: %s", exc)

    bridge = SignalBridge()
    engine = GramEngine(config)

    dot = FloatingDot(bridge)
    dot.show()

    # Dashboard (created once, shown on demand)
    dashboard = DashboardWindow(config, engine)

    def _center_window(window: QWidget):
        """Center a window on the primary screen."""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        available = screen.availableGeometry()
        frame = window.frameGeometry()
        frame.moveCenter(available.center())
        window.move(frame.topLeft())

    def _show_dashboard():
        """Show and activate the settings dashboard."""
        _center_window(dashboard)
        dashboard.showNormal()
        dashboard.show()
        dashboard.raise_()
        dashboard.activateWindow()
        app.setActiveWindow(dashboard)

    dot.open_settings.connect(_show_dashboard)

    if show_dashboard:
        QTimer.singleShot(0, _show_dashboard)

    # Start async controller in background thread
    worker = AsyncWorkerThread(config, bridge)
    dashboard.config_updated.connect(worker.apply_config)
    worker.start()

    bridge.state_changed.emit("idle")

    def on_quit():
        """Clean up worker thread on application quit."""
        worker.stop()
        worker.wait(3000)

    app.aboutToQuit.connect(on_quit)

    sys.exit(app.exec())
