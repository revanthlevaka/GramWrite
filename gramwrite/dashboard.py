"""
dashboard.py — GramWrite Settings Panel
Minimal secondary UI for configuration.
Backend, model, sensitivity, system prompt.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFrame,
)

from .engine import GramEngine, Backend

logger = logging.getLogger(__name__)

SENSITIVITY_LABELS = ["Low", "Medium", "High"]
SENSITIVITY_MAP = {"Low": "low", "Medium": "medium", "High": "high"}
SENSITIVITY_REVERSE = {v: i for i, (k, v) in enumerate(SENSITIVITY_MAP.items())}


class DashboardWindow(QWidget):
    """
    Settings panel. Opens on demand (e.g., right-click tray or keyboard shortcut).
    Secondary to the main experience — never shown automatically.
    """

    config_updated = pyqtSignal(dict)

    def __init__(self, config: dict, engine: GramEngine):
        super().__init__(None)
        self._config = dict(config)
        self._engine = engine

        self.setWindowTitle("GramWrite — Settings")
        self.setFixedWidth(420)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        self._apply_theme()
        self._build_ui()

    def _apply_theme(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0d0d10;
                color: #c8c4bc;
                font-family: 'Courier Prime', 'Courier New', monospace;
                font-size: 11px;
            }
            QLabel {
                color: #5a5860;
                letter-spacing: 1px;
                text-transform: uppercase;
                font-size: 10px;
                margin-top: 8px;
            }
            QLabel#value-label {
                color: #c8c4bc;
                font-size: 11px;
                text-transform: none;
                letter-spacing: 0;
                margin-top: 0;
            }
            QComboBox {
                background: #1a1a24;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                padding: 6px 10px;
                color: #c8c4bc;
                font-size: 11px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a24;
                border: 1px solid rgba(255,255,255,0.12);
                selection-background-color: rgba(58,176,120,0.12);
            }
            QPlainTextEdit {
                background: #1a1a24;
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                padding: 8px;
                color: #c8c4bc;
                font-size: 10px;
                line-height: 1.5;
            }
            QSlider::groove:horizontal {
                height: 4px;
                background: #22222e;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #3ab078;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::sub-page:horizontal {
                background: #3ab078;
                border-radius: 2px;
            }
            QPushButton#save-btn {
                background: #3ab078;
                color: #fff;
                border: none;
                border-radius: 7px;
                padding: 9px 20px;
                font-size: 11px;
                font-weight: bold;
                letter-spacing: 1px;
            }
            QPushButton#save-btn:hover { background: #48c88a; }
            QPushButton#save-btn:pressed { background: #2e9060; }
            QPushButton#refresh-btn {
                background: transparent;
                color: #5a5860;
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 10px;
            }
            QPushButton#refresh-btn:hover { background: #1a1a24; }
            QFrame#divider {
                background: rgba(255,255,255,0.07);
                max-height: 1px;
            }
        """)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(6)

        # Title
        title = QLabel("GRAMWRITE")
        title.setFont(QFont("Courier Prime", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: #e8e4da; font-size: 14px; letter-spacing: 4px; margin-bottom: 4px;")
        subtitle = QLabel("The Invisible Editor")
        subtitle.setStyleSheet("color: #5a5860; font-size: 10px; letter-spacing: 2px; text-transform: none; margin-top: 0;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        layout.addWidget(self._divider())

        # Backend
        layout.addWidget(self._section_label("LLM Backend"))
        self._backend_combo = QComboBox()
        self._backend_combo.addItems(["auto", "ollama", "lmstudio"])
        current_backend = self._config.get("backend", "auto")
        idx = self._backend_combo.findText(current_backend)
        if idx >= 0:
            self._backend_combo.setCurrentIndex(idx)
        layout.addWidget(self._backend_combo)

        # Model
        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItem(self._config.get("model", "qwen3.5:0.8b"))
        model_row.addWidget(self._model_combo)

        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.setObjectName("refresh-btn")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._load_models)
        model_row.addWidget(self._refresh_btn)

        layout.addWidget(self._section_label("Model"))
        layout.addLayout(model_row)

        # Sensitivity
        layout.addWidget(self._section_label("Correction Sensitivity"))
        sens_row = QHBoxLayout()
        self._sensitivity_slider = QSlider(Qt.Orientation.Horizontal)
        self._sensitivity_slider.setRange(0, 2)
        self._sensitivity_slider.setTickPosition(QSlider.TickPosition.NoTicks)
        current_sens = self._config.get("sensitivity", "medium")
        self._sensitivity_slider.setValue(SENSITIVITY_REVERSE.get(current_sens, 1))
        self._sensitivity_label = QLabel(SENSITIVITY_LABELS[self._sensitivity_slider.value()])
        self._sensitivity_label.setObjectName("value-label")
        self._sensitivity_label.setFixedWidth(60)
        self._sensitivity_slider.valueChanged.connect(
            lambda v: self._sensitivity_label.setText(SENSITIVITY_LABELS[v])
        )
        sens_row.addWidget(self._sensitivity_slider)
        sens_row.addWidget(self._sensitivity_label)
        layout.addLayout(sens_row)

        sens_hint = QLabel("Low = major errors only  ·  High = all suggestions")
        sens_hint.setStyleSheet("color: #3a3840; font-size: 9px; margin-top: 2px;")
        layout.addWidget(sens_hint)

        # System Prompt
        layout.addWidget(self._section_label("System Prompt"))
        self._prompt_edit = QPlainTextEdit()
        self._prompt_edit.setPlainText(self._config.get("system_prompt", ""))
        self._prompt_edit.setFixedHeight(110)
        layout.addWidget(self._prompt_edit)

        layout.addWidget(self._divider())

        # Save button
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._save_btn = QPushButton("Save Settings")
        self._save_btn.setObjectName("save-btn")
        self._save_btn.clicked.connect(self._save)
        save_row.addWidget(self._save_btn)
        layout.addLayout(save_row)

        layout.addStretch()

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        return label

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("divider")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def _load_models(self):
        """Async load available models from active backend."""
        self._refresh_btn.setText("…")
        self._refresh_btn.setEnabled(False)

        class ModelLoader(QThread):
            done = pyqtSignal(list)

            def __init__(self, engine):
                super().__init__()
                self._engine = engine

            def run(self):
                loop = asyncio.new_event_loop()
                try:
                    ollama = loop.run_until_complete(self._engine.list_ollama_models())
                    lmstudio = loop.run_until_complete(self._engine.list_lmstudio_models())
                    self.done.emit(list(dict.fromkeys(ollama + lmstudio)))
                finally:
                    loop.close()

        self._loader = ModelLoader(self._engine)

        def on_done(models):
            self._model_combo.clear()
            if models:
                self._model_combo.addItems(models)
                current = self._config.get("model", "qwen3.5:0.8b")
                idx = self._model_combo.findText(current)
                if idx >= 0:
                    self._model_combo.setCurrentIndex(idx)
                else:
                    self._model_combo.addItem(current)
                    self._model_combo.setCurrentText(current)
            else:
                self._model_combo.addItem(self._config.get("model", "qwen3.5:0.8b"))
            self._refresh_btn.setText("↻ Refresh")
            self._refresh_btn.setEnabled(True)

        self._loader.done.connect(on_done)
        self._loader.start()

    def _save(self):
        self._config["backend"] = self._backend_combo.currentText()
        self._config["model"] = self._model_combo.currentText().strip()
        self._config["sensitivity"] = SENSITIVITY_MAP[
            SENSITIVITY_LABELS[self._sensitivity_slider.value()]
        ]
        self._config["system_prompt"] = self._prompt_edit.toPlainText().strip()

        # Persist to YAML
        try:
            import yaml
            config_path = self._config.get("_config_path", "config.yaml")
            save_data = {k: v for k, v in self._config.items() if not k.startswith("_")}
            with open(config_path, "w") as f:
                yaml.dump(save_data, f, default_flow_style=False, allow_unicode=True)
            logger.info("Config saved to %s", config_path)
        except Exception as e:
            logger.warning("Could not save config: %s", e)

        self.config_updated.emit(self._config)
        self._save_btn.setText("Saved ✓")
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(1500, lambda: self._save_btn.setText("Save Settings"))
