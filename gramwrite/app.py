"""
app.py — GramWrite Floating UI
Minimal, always-on-top draggable icon with suggestion bubble.
Built with PyQt6.
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
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
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


# ─── Signals bridge (Controller → Qt main thread) ────────────────────────────


class SignalBridge(QObject):
    correction_ready = pyqtSignal(str, str)   # original, correction
    state_changed = pyqtSignal(str)           # idle | processing | alert | error
    backend_status = pyqtSignal(str)          # status message


# ─── Floating dot icon ────────────────────────────────────────────────────────


class FloatingDot(QWidget):
    """
    The primary GramWrite icon.
    A small coloured dot that lives in the corner.
    Draggable. Click to show/hide suggestion bubble.
    Right-click for Settings / Quit context menu.
    """

    open_settings = pyqtSignal()  # emitted when user picks «Settings» from menu

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

        self._init_window()
        self._init_pulse_timer()
        self._connect_signals()
        self._init_context_menu()

    def _init_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self._dot_size + 8, self._dot_size + 8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Position bottom-right of primary screen
        screen = QGuiApplication.primaryScreen().geometry()
        self.move(screen.width() - 80, screen.height() - 120)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)

    def _init_pulse_timer(self):
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_timer.start(50)  # 20fps pulse

    def _connect_signals(self):
        self._bridge.correction_ready.connect(self._on_correction_ready)
        self._bridge.state_changed.connect(self._on_state_changed)

    def _init_context_menu(self):
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

        quit_action = QAction("✕  Quit GramWrite", self)
        quit_action.triggered.connect(QApplication.quit)
        self._ctx_menu.addAction(quit_action)

    def contextMenuEvent(self, event):
        self._ctx_menu.exec(event.globalPos())

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, _):
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

    def _on_correction_ready(self, original: str, correction: str):
        self._current_original = original
        self._current_suggestion = correction
        self._on_state_changed("alert")

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            if self._drag_pos and (delta - self._drag_pos).manhattanLength() < 5:
                # It was a click, not a drag
                self._toggle_bubble()
            self._drag_pos = None

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def _toggle_bubble(self):
        if self._bubble and self._bubble.isVisible():
            self._bubble.hide()
            return

        if self._current_suggestion:
            if not self._bubble:
                self._bubble = SuggestionBubble(self._bridge)
            self._bubble.set_content(
                self._current_original or "",
                self._current_suggestion
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


# ─── Suggestion Bubble ────────────────────────────────────────────────────────


class SuggestionBubble(QWidget):
    """
    Minimal correction popup.
    Shows original vs correction, with copy button.
    """

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
        self.setFixedWidth(300)

        self._build_ui()
        self._apply_shadow()

    def _build_ui(self):
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

        # Header
        header = QLabel("✦ GramWrite")
        header.setFont(QFont("Courier New", 9))
        header.setStyleSheet("color: rgba(120,120,130,200); letter-spacing: 2px;")
        layout.addWidget(header)

        # Correction text
        self._correction_label = QLabel("")
        self._correction_label.setFont(QFont("Georgia", 11))
        self._correction_label.setStyleSheet("color: rgba(230, 230, 235, 255); line-height: 1.5;")
        self._correction_label.setWordWrap(True)
        self._correction_label.setMaximumWidth(268)
        layout.addWidget(self._correction_label)

        # Divider
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(60,60,70,180);")
        layout.addWidget(divider)

        # Bottom bar
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._dismiss_btn = QPushButton("Dismiss")
        self._dismiss_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._dismiss_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: rgba(120,120,130,200);
                border: none;
                font-family: 'Courier New';
                font-size: 10px;
                padding: 4px 8px;
            }
            QPushButton:hover { color: rgba(200,200,210,255); }
        """)
        self._dismiss_btn.clicked.connect(self.hide)

        self._copy_btn = QPushButton("Copy correction")
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet("""
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
        self._copy_btn.clicked.connect(self._copy_to_clipboard)

        bottom.addWidget(self._dismiss_btn)
        bottom.addStretch()
        bottom.addWidget(self._copy_btn)
        layout.addLayout(bottom)

        root.addWidget(self._container)

    def _apply_shadow(self):
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self._container.setGraphicsEffect(shadow)

    def set_content(self, original: str, correction: str):
        self._correction = correction
        display = correction
        if len(display) > 160:
            display = display[:157] + "…"
        self._correction_label.setText(display)
        self.adjustSize()

    def _copy_to_clipboard(self):
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self._correction)
        self._copy_btn.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self._copy_btn.setText("Copy correction"))


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
        from .controller import Controller, PipelineResult

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        def on_result(result: PipelineResult):
            if result.has_suggestion:
                self._bridge.correction_ready.emit(
                    result.parsed.text,
                    result.suggestion,
                )
                self._bridge.state_changed.emit("alert")
            elif result.parsed.should_check:
                # Was checked, no errors found
                self._bridge.state_changed.emit("idle")
            else:
                self._bridge.state_changed.emit("idle")

        self._controller = Controller(self._config, on_result)

        try:
            self._loop.run_until_complete(self._controller.start())
        except Exception as e:
            logger.exception("AsyncWorkerThread error: %s", e)
            self._bridge.state_changed.emit("error")

    def stop(self):
        if self._controller and self._loop:
            asyncio.run_coroutine_threadsafe(
                self._controller.stop(), self._loop
            )


# ─── Main entry point ────────────────────────────────────────────────────────


def run_app(config: dict, show_dashboard: bool = False):
    """Launch the GramWrite floating UI."""
    from .engine import GramEngine
    from .dashboard import DashboardWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("GramWrite")

    bridge = SignalBridge()
    engine = GramEngine(config)

    dot = FloatingDot(bridge)
    dot.show()

    # Dashboard (created once, shown on demand)
    dashboard = DashboardWindow(config, engine)

    def _show_dashboard():
        dashboard.show()
        dashboard.raise_()
        dashboard.activateWindow()

    dot.open_settings.connect(_show_dashboard)

    if show_dashboard:
        _show_dashboard()

    # Start async controller in background thread
    worker = AsyncWorkerThread(config, bridge)
    worker.start()

    bridge.state_changed.emit("idle")

    def on_quit():
        worker.stop()
        worker.wait(3000)

    app.aboutToQuit.connect(on_quit)

    sys.exit(app.exec())
