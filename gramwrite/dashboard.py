"""
dashboard.py — GramWrite Settings Panel
Branded secondary UI for configuration.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .engine import GramEngine
from .foundation_models import FOUNDATION_BACKEND_KEY, FOUNDATION_MODEL_ID
from .harper import HARPER_BACKEND_KEY, HARPER_MODEL_ID

logger = logging.getLogger(__name__)

VERSION = __version__
SENSITIVITY_LABELS = ["Low", "Medium", "High"]
SENSITIVITY_MAP = {"Low": "low", "Medium": "medium", "High": "high"}
SENSITIVITY_REVERSE = {v: i for i, (k, v) in enumerate(SENSITIVITY_MAP.items())}


class DashboardWindow(QWidget):
    """
    Settings panel. Opens on demand from the floating dot.
    Brings the shipped dashboard closer to the brand manual layout.
    """

    config_updated = pyqtSignal(dict)

    def __init__(self, config: dict, engine: GramEngine):
        super().__init__(None)
        self._config = dict(config)
        self._engine = engine
        self._is_macos = sys.platform == "darwin"
        self._last_local_model = self._config.get("model", "qwen3.5:0.8b")
        if self._last_local_model == FOUNDATION_MODEL_ID:
            self._last_local_model = "qwen3.5:0.8b"
        self._nav_buttons: dict[str, QPushButton] = {}
        self._page_indexes: dict[str, int] = {}

        self.setWindowTitle("GramWrite — Settings")
        self.resize(980, 680)
        self.setMinimumSize(920, 620)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self._apply_theme()
        self._build_ui()
        self._switch_page("general")

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QWidget {
                background-color: #13131a;
                color: #c8c4bc;
                font-family: 'Courier Prime', 'Courier New', monospace;
                font-size: 11px;
            }
            QWidget#shell {
                background: #13131a;
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: 12px;
            }
            QWidget#chrome {
                background: #0d0d10;
                border-bottom: 1px solid rgba(255,255,255,0.08);
                border-top-left-radius: 12px;
                border-top-right-radius: 12px;
            }
            QLabel#chrome-title {
                color: #8c8993;
                font-size: 10px;
                letter-spacing: 2px;
                text-transform: uppercase;
            }
            QWidget#logo-lockup {
                background: transparent;
            }
            QFrame#logo-mark {
                background: #3ab078;
                border-radius: 14px;
            }
            QFrame#logo-mark-inner {
                background: rgba(0,0,0,0.38);
                border-radius: 4px;
            }
            QLabel#logo-word {
                color: #e8e4da;
                font-size: 14px;
                letter-spacing: 2px;
            }
            QLabel#logo-tagline {
                color: #5a5860;
                font-size: 10px;
                letter-spacing: 1px;
            }
            QFrame#sidebar {
                background: #0d0d10;
                border-right: 1px solid rgba(255,255,255,0.08);
            }
            QLabel#nav-group {
                color: rgba(200,196,188,0.42);
                font-size: 9px;
                letter-spacing: 3px;
                text-transform: uppercase;
            }
            QPushButton#nav-item {
                background: transparent;
                border: none;
                border-left: 2px solid transparent;
                color: #7a767f;
                padding: 10px 16px;
                text-align: left;
                font-size: 12px;
            }
            QPushButton#nav-item:hover {
                background: #1a1a24;
                color: #c8c4bc;
            }
            QPushButton#nav-item[active="true"] {
                background: rgba(58,176,120,0.12);
                border-left-color: #3ab078;
                color: #3ab078;
            }
            QFrame#status-card {
                background: #1a1a24;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 6px;
            }
            QLabel#status-title {
                color: #e8e4da;
                font-size: 10px;
                letter-spacing: 1px;
                text-transform: uppercase;
            }
            QLabel#status-detail {
                color: #7a767f;
                font-size: 10px;
            }
            QLabel#status-dot {
                color: #3ab078;
                font-size: 14px;
            }
            QWidget#tabs {
                border-bottom: 1px solid rgba(255,255,255,0.08);
            }
            QPushButton#tab-item {
                background: transparent;
                color: #7a767f;
                border: 1px solid transparent;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 8px 16px;
                text-transform: uppercase;
                letter-spacing: 1px;
                font-size: 11px;
            }
            QPushButton#tab-item:hover {
                background: #1a1a24;
                color: #c8c4bc;
            }
            QPushButton#tab-item[active="true"] {
                background: #13131a;
                color: #3ab078;
                border-color: rgba(255,255,255,0.08);
            }
            QWidget#page {
                background: #13131a;
            }
            QLabel#page-title {
                color: #e8e4da;
                font-size: 13px;
                letter-spacing: 2px;
                text-transform: uppercase;
            }
            QLabel#page-copy {
                color: #7a767f;
                font-size: 11px;
                line-height: 1.6;
            }
            QLabel#form-label {
                color: #7a767f;
                font-size: 10px;
                letter-spacing: 2px;
                text-transform: uppercase;
            }
            QLabel#form-hint {
                color: rgba(200,196,188,0.36);
                font-size: 10px;
                line-height: 1.5;
            }
            QFrame#group-card {
                background: #1a1a24;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 8px;
            }
            QComboBox, QLineEdit, QPlainTextEdit {
                background: #0d0d10;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 5px;
                color: #c8c4bc;
                padding: 9px 12px;
                font-size: 12px;
            }
            QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus {
                border-color: rgba(58,176,120,0.45);
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QComboBox QAbstractItemView {
                background: #1a1a24;
                border: 1px solid rgba(255,255,255,0.12);
                selection-background-color: rgba(58,176,120,0.15);
            }
            QPushButton#refresh-btn {
                background: transparent;
                color: #7a767f;
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 5px;
                padding: 8px 12px;
                font-size: 10px;
            }
            QPushButton#refresh-btn:hover {
                background: #1a1a24;
                color: #c8c4bc;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #22222e;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #3ab078;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #3ab078;
                width: 16px;
                height: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QLabel#slider-value {
                color: #3ab078;
                font-size: 11px;
            }
            QCheckBox {
                color: #c8c4bc;
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid rgba(255,255,255,0.14);
                background: #0d0d10;
            }
            QCheckBox::indicator:checked {
                background: #3ab078;
                border-color: #3ab078;
            }
            QPushButton#save-btn {
                background: #3ab078;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 10px 22px;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 2px;
                text-transform: uppercase;
            }
            QPushButton#save-btn:hover {
                background: #48c88a;
            }
            QLabel#about-copy {
                color: #7a767f;
                font-size: 11px;
                line-height: 1.8;
            }
            QLabel#about-strong {
                color: #e8e4da;
            }
            """
        )

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        shell = QFrame()
        shell.setObjectName("shell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        shell_layout.addWidget(self._build_chrome())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_main(), 1)
        shell_layout.addLayout(body)

        root.addWidget(shell)

    def _build_chrome(self) -> QWidget:
        chrome = QFrame()
        chrome.setObjectName("chrome")
        chrome_layout = QHBoxLayout(chrome)
        chrome_layout.setContentsMargins(18, 12, 18, 12)

        title = QLabel("GramWrite — Settings")
        title.setObjectName("chrome-title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        chrome_layout.addWidget(title)
        return chrome

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 20, 0, 16)
        layout.setSpacing(0)

        logo_lockup = QWidget()
        logo_lockup.setObjectName("logo-lockup")
        logo_layout = QHBoxLayout(logo_lockup)
        logo_layout.setContentsMargins(20, 0, 20, 20)
        logo_layout.setSpacing(12)

        logo_mark = QFrame()
        logo_mark.setObjectName("logo-mark")
        logo_mark.setFixedSize(28, 28)
        logo_mark_layout = QVBoxLayout(logo_mark)
        logo_mark_layout.setContentsMargins(0, 0, 0, 0)
        logo_mark_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        logo_mark_inner = QFrame()
        logo_mark_inner.setObjectName("logo-mark-inner")
        logo_mark_inner.setFixedSize(8, 8)
        logo_mark_layout.addWidget(logo_mark_inner)

        logo_wrap = QVBoxLayout()
        logo_wrap.setContentsMargins(0, 0, 0, 0)
        logo_wrap.setSpacing(4)

        logo = QLabel("GRAMWRITE")
        logo.setObjectName("logo-word")
        tagline = QLabel("The Invisible Editor")
        tagline.setObjectName("logo-tagline")
        logo_wrap.addWidget(logo)
        logo_wrap.addWidget(tagline)
        logo_copy = QWidget()
        logo_copy.setLayout(logo_wrap)

        logo_layout.addWidget(logo_mark, 0, Qt.AlignmentFlag.AlignTop)
        logo_layout.addWidget(logo_copy)
        logo_layout.addStretch()
        layout.addWidget(logo_lockup)

        layout.addWidget(self._divider())
        layout.addSpacing(12)

        layout.addWidget(self._nav_label("Settings"))
        layout.addWidget(self._nav_button("general", "General"))
        layout.addWidget(self._nav_button("model", "Model"))
        layout.addWidget(self._nav_button("appearance", "Appearance"))
        layout.addWidget(self._nav_button("advanced", "Advanced"))
        layout.addSpacing(10)
        layout.addWidget(self._nav_label("System"))
        layout.addWidget(self._nav_button("about", "About"))
        layout.addStretch()
        layout.addWidget(self._build_status_card())

        return sidebar

    def _build_main(self) -> QWidget:
        wrap = QWidget()
        main_layout = QVBoxLayout(wrap)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        tabs = QWidget()
        tabs.setObjectName("tabs")
        tabs_layout = QHBoxLayout(tabs)
        tabs_layout.setContentsMargins(24, 16, 24, 0)
        tabs_layout.setSpacing(2)
        for key, label in (
            ("general", "General"),
            ("model", "Model"),
            ("appearance", "Appearance"),
            ("advanced", "Advanced"),
            ("about", "About"),
        ):
            tabs_layout.addWidget(self._tab_button(key, label))
        tabs_layout.addStretch()
        main_layout.addWidget(tabs)

        self._stack = QStackedWidget()
        self._stack.setContentsMargins(0, 0, 0, 0)
        for key, builder in (
            ("general", self._build_general_page),
            ("model", self._build_model_page),
            ("appearance", self._build_appearance_page),
            ("advanced", self._build_advanced_page),
            ("about", self._build_about_page),
        ):
            widget = builder()
            self._page_indexes[key] = self._stack.addWidget(widget)
        main_layout.addWidget(self._stack, 1)
        return wrap

    def _build_general_page(self) -> QWidget:
        page, layout = self._page_shell(
            "General",
            "The everyday controls for how GramWrite watches, waits, and intervenes while you write.",
        )

        grid = self._settings_grid()
        self._backend_combo = QComboBox()
        backend_options = ["auto", "ollama", "lmstudio", HARPER_BACKEND_KEY]
        if self._is_macos:
            backend_options.append(FOUNDATION_BACKEND_KEY)
        self._backend_combo.addItems(backend_options)
        self._backend_combo.setCurrentText(self._config.get("backend", "auto"))
        self._bind_status_updates()
        backend_hint = "Auto-detects Ollama or LM Studio when possible. Harper is available as a fast local English grammar checker."
        if self._is_macos:
            backend_hint += " Apple Foundation Models is available on Apple Intelligence-enabled Macs when selected explicitly."
        grid.addWidget(self._field("Grammar Backend", self._backend_combo, backend_hint), 0, 0)

        self._debounce_input = QLineEdit(str(self._config.get("debounce_seconds", 2.0)))
        grid.addWidget(self._field("Debounce (seconds)", self._debounce_input, "Wait time after typing stops before analysis."), 0, 1)

        sens_wrap = QWidget()
        sens_layout = QHBoxLayout(sens_wrap)
        sens_layout.setContentsMargins(0, 0, 0, 0)
        sens_layout.setSpacing(16)
        self._sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self._sensitivity_slider.setRange(0, 2)
        self._sensitivity_slider.setValue(SENSITIVITY_REVERSE.get(self._config.get("sensitivity", "medium"), 1))
        self._sensitivity_value = QLabel(SENSITIVITY_LABELS[self._sensitivity_slider.value()])
        self._sensitivity_value.setObjectName("slider-value")
        self._sensitivity_slider.valueChanged.connect(
            lambda value: self._sensitivity_value.setText(SENSITIVITY_LABELS[value])
        )
        sens_layout.addWidget(self._sensitivity_slider, 1)
        sens_layout.addWidget(self._sensitivity_value)
        grid.addWidget(
            self._field(
                "Correction Sensitivity",
                sens_wrap,
                "Low = major errors only. Medium = standard. High = catch everything.",
            ),
            1,
            0,
            1,
            2,
        )

        behavior_card = self._group_card()
        behavior_layout = QVBoxLayout(behavior_card)
        behavior_layout.setContentsMargins(16, 16, 16, 16)
        behavior_layout.setSpacing(12)
        self._strict_mode_checkbox = QCheckBox("Strict Screenplay Mode")
        self._strict_mode_checkbox.setChecked(bool(self._config.get("strict_mode", True)))
        strict_hint = self._hint_label("Checks Action and Dialogue lines only. Sluglines and transitions are ignored.")
        behavior_layout.addWidget(self._strict_mode_checkbox)
        behavior_layout.addWidget(strict_hint)
        grid.addWidget(self._field("Behaviour", behavior_card, ""), 2, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()
        layout.addLayout(self._save_row())
        return page

    def _build_model_page(self) -> QWidget:
        page, layout = self._page_shell(
            "Model",
            "Backend selection, active model choice, and the exact system instructions sent with every correction.",
        )

        grid = self._settings_grid()

        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(8)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItem(self._config.get("model", "qwen3.5:0.8b"))
        self._model_combo.setCurrentText(self._config.get("model", "qwen3.5:0.8b"))
        model_layout.addWidget(self._model_combo, 1)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("refresh-btn")
        self._refresh_btn.clicked.connect(self._load_models)
        model_layout.addWidget(self._refresh_btn)
        model_hint = "Load discovered models from Ollama and LM Studio. Harper uses a fixed local English model."
        if self._is_macos:
            model_hint += " Apple Foundation Models uses Apple's on-device model instead of a user-selected Ollama checkpoint."
        grid.addWidget(self._field("Active Model", model_row, model_hint), 0, 0, 1, 2)

        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlainText(self._config.get("system_prompt", ""))
        self._prompt_edit.setFixedHeight(180)
        grid.addWidget(
            self._field(
                "System Prompt",
                self._prompt_edit,
                "Keeps corrections grammar-only and screenplay-aware. Edit carefully.",
            ),
            1,
            0,
            1,
            2,
        )

        layout.addLayout(grid)
        layout.addStretch()
        layout.addLayout(self._save_row())
        self._handle_backend_changed(self._backend_combo.currentText())
        return page

    def _build_appearance_page(self) -> QWidget:
        page, layout = self._page_shell(
            "Appearance",
            "A live summary of the shipping visual system so the dashboard mirrors the brand language already in the app.",
        )

        grid = self._settings_grid()
        palette_card = self._group_card()
        palette_layout = QVBoxLayout(palette_card)
        palette_layout.setContentsMargins(16, 16, 16, 16)
        palette_layout.setSpacing(10)
        for label, value in (
            ("Ink", "#0d0d10"),
            ("Surface", "#1a1a24"),
            ("Signal Green", "#3ab078"),
            ("Aged Paper", "#e8e4da"),
        ):
            row = QLabel(f"{label:<13} {value}")
            row.setStyleSheet("color: #c8c4bc; font-size: 11px;")
            palette_layout.addWidget(row)
        grid.addWidget(self._field("Palette", palette_card, "The dashboard and correction UI now follow the same brand palette."), 0, 0)

        motion_card = self._group_card()
        motion_layout = QVBoxLayout(motion_card)
        motion_layout.setContentsMargins(16, 16, 16, 16)
        motion_layout.setSpacing(10)
        motion_layout.addWidget(QLabel("Idle       Dark grey static dot"))
        motion_layout.addWidget(QLabel("Processing Blue pulse"))
        motion_layout.addWidget(QLabel("Alert      Signal green"))
        motion_layout.addWidget(QLabel("Error      Red state"))
        grid.addWidget(self._field("Dot States", motion_card, "The floating dot remains the primary always-on surface."), 0, 1)

        type_card = self._group_card()
        type_layout = QVBoxLayout(type_card)
        type_layout.setContentsMargins(16, 16, 16, 16)
        type_layout.setSpacing(8)
        type_layout.addWidget(QLabel("Brand moments: uppercase display styling"))
        type_layout.addWidget(QLabel("UI controls: Courier Prime / monospace"))
        type_layout.addWidget(QLabel("Editorial copy: serif contrast where helpful"))
        grid.addWidget(self._field("Typography", type_card, "A reference page only. These notes are not editable product settings."), 1, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()
        layout.addLayout(self._save_row())
        return page

    def _build_advanced_page(self) -> QWidget:
        page, layout = self._page_shell(
            "Advanced",
            "Low-level performance and dashboard controls for local development and debugging.",
        )

        grid = self._settings_grid()
        self._max_context_input = QLineEdit(str(self._config.get("max_context_chars", 300)))
        grid.addWidget(self._field("Max Context Chars", self._max_context_input, "How much nearby text GramWrite inspects around the cursor."), 0, 0)

        self._dashboard_port_input = QLineEdit(str(self._config.get("dashboard_port", 7878)))
        grid.addWidget(self._field("Dashboard Port", self._dashboard_port_input, "Used by the localhost dashboard server."), 0, 1)

        note_card = self._group_card()
        note_layout = QVBoxLayout(note_card)
        note_layout.setContentsMargins(16, 16, 16, 16)
        note_layout.setSpacing(8)
        note_layout.addWidget(QLabel("No accounts. No telemetry. No cloud."))
        note_layout.addWidget(QLabel("All inference stays on local hardware."))
        note_layout.addWidget(QLabel("Use conservative values unless you are debugging."))
        grid.addWidget(self._field("Privacy Pledge", note_card, ""), 1, 0, 1, 2)

        layout.addLayout(grid)
        layout.addStretch()
        layout.addLayout(self._save_row())
        return page

    def _build_about_page(self) -> QWidget:
        page, layout = self._page_shell(
            "About",
            "Version, authorship, and the product philosophy behind the floating-dot experience.",
        )

        card = self._group_card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)

        for line in (
            f"Version {VERSION} · MIT License",
            "Built by Revanth Levaka",
            "A local-first grammar sidecar for screenwriters.",
            "Optional English grammar backend powered by Harper from Automattic.",
        ):
            label = QLabel(line)
            label.setObjectName("about-copy")
            card_layout.addWidget(label)

        privacy = QLabel(
            "GramWrite makes zero external network calls.\n"
            "Your text is never logged, stored, or transmitted.\n"
            "Every correction runs locally on your machine."
        )
        privacy.setObjectName("about-copy")
        card_layout.addWidget(privacy)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _page_shell(self, title_text: str, copy_text: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        title = QLabel(title_text)
        title.setObjectName("page-title")
        copy = QLabel(copy_text)
        copy.setObjectName("page-copy")
        copy.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(copy)
        return page, layout

    def _settings_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(20)
        return grid

    def _field(self, label_text: str, widget: QWidget, hint_text: str) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        label = QLabel(label_text)
        label.setObjectName("form-label")
        layout.addWidget(label)
        layout.addWidget(widget)
        if hint_text:
            hint = self._hint_label(hint_text)
            layout.addWidget(hint)
        return wrap

    def _hint_label(self, text: str) -> QLabel:
        hint = QLabel(text)
        hint.setObjectName("form-hint")
        hint.setWordWrap(True)
        return hint

    def _group_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("group-card")
        return card

    def _divider(self) -> QFrame:
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(255,255,255,0.08); border: none;")
        return divider

    def _nav_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("nav-group")
        label.setContentsMargins(20, 8, 20, 4)
        return label

    def _nav_button(self, key: str, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("nav-item")
        button.clicked.connect(lambda: self._switch_page(key))
        self._nav_buttons[f"nav:{key}"] = button
        return button

    def _tab_button(self, key: str, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("tab-item")
        button.clicked.connect(lambda: self._switch_page(key))
        self._nav_buttons[f"tab:{key}"] = button
        return button

    def _build_status_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("status-card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        dot = QLabel("●")
        dot.setObjectName("status-dot")
        self._status_title = QLabel()
        self._status_title.setObjectName("status-title")
        top.addWidget(dot)
        top.addWidget(self._status_title)
        top.addStretch()
        layout.addLayout(top)

        self._status_detail = QLabel()
        self._status_detail.setObjectName("status-detail")
        self._status_detail.setWordWrap(True)
        layout.addWidget(self._status_detail)
        self._refresh_status_card()
        return card

    def _bind_status_updates(self):
        self._backend_combo.currentTextChanged.connect(lambda _: self._refresh_status_card())
        self._backend_combo.currentTextChanged.connect(self._handle_backend_changed)

    def _handle_backend_changed(self, backend: str):
        if not hasattr(self, "_model_combo") or not hasattr(self, "_refresh_btn"):
            return

        if backend == FOUNDATION_BACKEND_KEY:
            current_model = self._model_combo.currentText().strip()
            if current_model and current_model != FOUNDATION_MODEL_ID:
                self._last_local_model = current_model
            if FOUNDATION_MODEL_ID not in [self._model_combo.itemText(i) for i in range(self._model_combo.count())]:
                self._model_combo.addItem(FOUNDATION_MODEL_ID)
            self._model_combo.setCurrentText(FOUNDATION_MODEL_ID)
            self._model_combo.setEditable(False)
            self._model_combo.setEnabled(False)
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setText("Apple managed")
        elif backend == HARPER_BACKEND_KEY:
            current_model = self._model_combo.currentText().strip()
            if current_model and current_model != HARPER_MODEL_ID:
                self._last_local_model = current_model
            if HARPER_MODEL_ID not in [self._model_combo.itemText(i) for i in range(self._model_combo.count())]:
                self._model_combo.addItem(HARPER_MODEL_ID)
            self._model_combo.setCurrentText(HARPER_MODEL_ID)
            self._model_combo.setEditable(False)
            self._model_combo.setEnabled(False)
            self._refresh_btn.setEnabled(False)
            self._refresh_btn.setText("Harper managed")
        else:
            if self._model_combo.currentText().strip() in (FOUNDATION_MODEL_ID, HARPER_MODEL_ID):
                self._model_combo.setCurrentText(self._last_local_model)
            self._model_combo.setEnabled(True)
            self._model_combo.setEditable(True)
            self._refresh_btn.setEnabled(True)
            self._refresh_btn.setText("Refresh")

    def _refresh_status_card(self):
        backend = self._config.get("backend", "auto")
        if hasattr(self, "_backend_combo"):
            backend = self._backend_combo.currentText()
        model = self._config.get("model", "qwen3.5:0.8b") or "Unspecified"
        if hasattr(self, "_model_combo") and self._model_combo.currentText().strip():
            model = self._model_combo.currentText().strip()

        if backend == FOUNDATION_BACKEND_KEY:
            self._status_title.setText("APPLE FOUNDATION · CONFIGURED")
            self._status_detail.setText("apple.foundation · on-device Apple Intelligence model")
            return
        if backend == HARPER_BACKEND_KEY:
            self._status_title.setText("HARPER · CONFIGURED")
            self._status_detail.setText("harper.english · local English grammar checker")
            return

        self._status_title.setText(f"{backend.upper()} · CONFIGURED")
        self._status_detail.setText(f"{model} · localhost dashboard available")

    def _switch_page(self, key: str):
        self._stack.setCurrentIndex(self._page_indexes[key])
        for button_key, button in self._nav_buttons.items():
            active = button_key.endswith(f":{key}")
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _save_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()
        save = QPushButton("Save Settings")
        save.setObjectName("save-btn")
        save.setAutoDefault(False)
        save.setDefault(False)
        save.clicked.connect(lambda _checked=False, btn=save: self._save(btn))
        row.addWidget(save)
        return row

    def _load_models(self):
        if self._backend_combo.currentText() in (FOUNDATION_BACKEND_KEY, HARPER_BACKEND_KEY):
            self._handle_backend_changed(self._backend_combo.currentText())
            return

        self._refresh_btn.setText("...")
        self._refresh_btn.setEnabled(False)

        class ModelLoader(QThread):
            done = pyqtSignal(list)

            def __init__(self, engine: GramEngine):
                super().__init__()
                self._engine = engine

            def run(self):
                loop = asyncio.new_event_loop()
                try:
                    ollama = loop.run_until_complete(self._engine.list_ollama_models())
                    lmstudio = loop.run_until_complete(self._engine.list_lmstudio_models())
                    foundation = loop.run_until_complete(self._engine.list_foundation_models())
                    harper = loop.run_until_complete(self._engine.list_harper_models())
                    self.done.emit(list(dict.fromkeys(ollama + lmstudio + foundation + harper)))
                finally:
                    loop.close()

        self._loader = ModelLoader(self._engine)

        def on_done(models: list[str]):
            self._model_combo.clear()
            if models:
                self._model_combo.addItems(models)
            current = self._config.get("model", "qwen3.5:0.8b")
            if current not in [self._model_combo.itemText(i) for i in range(self._model_combo.count())]:
                self._model_combo.addItem(current)
            self._model_combo.setCurrentText(current)
            self._refresh_btn.setText("Refresh")
            self._refresh_btn.setEnabled(True)

        self._loader.done.connect(on_done)
        self._loader.start()

    def _save(self, save_button: Optional[QPushButton] = None):
        self._config["backend"] = self._backend_combo.currentText()
        if self._config["backend"] == FOUNDATION_BACKEND_KEY:
            self._config["model"] = FOUNDATION_MODEL_ID
        elif self._config["backend"] == HARPER_BACKEND_KEY:
            self._config["model"] = HARPER_MODEL_ID
        else:
            self._config["model"] = self._model_combo.currentText().strip()
            if self._config["model"]:
                self._last_local_model = self._config["model"]
        self._config["sensitivity"] = SENSITIVITY_MAP[SENSITIVITY_LABELS[self._sensitivity_slider.value()]]
        self._config["system_prompt"] = self._prompt_edit.toPlainText().strip()
        self._config["strict_mode"] = self._strict_mode_checkbox.isChecked()
        self._config["debounce_seconds"] = self._parse_float(self._debounce_input.text(), 2.0, 0.1)
        self._config["max_context_chars"] = self._parse_int(self._max_context_input.text(), 300, 50)
        self._config["dashboard_port"] = self._parse_int(self._dashboard_port_input.text(), 7878, 1)

        try:
            import yaml

            config_path = self._config.get("_config_path", "config.yaml")
            save_data = {k: v for k, v in self._config.items() if not k.startswith("_")}
            with open(config_path, "w") as f:
                yaml.dump(save_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            logger.info("Config saved to %s", config_path)
        except Exception as exc:
            logger.warning("Could not save config: %s", exc)

        self._refresh_status_card()
        self.config_updated.emit(self._config)
        if save_button is not None:
            save_button.setText("Saved ✓")
            QTimer.singleShot(1800, lambda: save_button.setText("Save Settings"))

    @staticmethod
    def _parse_float(value: str, default: float, minimum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return max(parsed, minimum)

    @staticmethod
    def _parse_int(value: str, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(parsed, minimum)
